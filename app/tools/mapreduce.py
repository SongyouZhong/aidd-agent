"""Map-Reduce summarisation engine (design doc §7.2.1 step 3).

Used when a tool returns content whose total volume blows past the
3000-token cap even after pruning + chunking — e.g. "summarise these 20
PubMed abstracts about T790M". Cheap Gemini Flash workers digest each
document in parallel (Map), then a single reduce step stitches them.

If no Gemini API key is configured (``GEMINI_API_KEY`` empty), the
engine gracefully degrades to a deterministic heuristic reducer
(concatenated first/last sentences) so unit tests stay offline-friendly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from app.core.config import settings
from app.tools.preprocess import MAX_TOOL_TOKENS, cap_tokens, estimate_tokens

logger = logging.getLogger(__name__)

DEFAULT_WORKER_PROMPT = (
    "Extract the 3-5 most important findings from the document below "
    "that are directly relevant to: '{focus}'. "
    "Output a tight bullet list with citations (PMID/DOI/URL) where present.\n\n"
    "DOCUMENT:\n{doc}"
)

DEFAULT_REDUCE_PROMPT = (
    "Combine the partial extracts below into one dense markdown summary "
    "focused on: '{focus}'. Deduplicate and preserve every citation.\n\n"
    "PARTIAL EXTRACTS:\n{partials}"
)


# --- LLM client (lazy, optional) ---------------------------------------

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not settings.GEMINI_API_KEY:
        return None
    try:
        from google import genai  # type: ignore

        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return _client
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Gemini SDK unavailable: %s", exc)
        return None


async def _gemini_generate(prompt: str, model: str = "gemini-2.5-flash") -> str:
    client = _get_client()
    if client is None:
        # Heuristic fallback: first 6 sentences.
        sentences = prompt.split(". ")
        return ". ".join(sentences[:6]).strip() + ("." if sentences else "")
    resp = await asyncio.to_thread(
        client.models.generate_content, model=model, contents=prompt
    )
    return getattr(resp, "text", "") or ""


# --- Map-Reduce pipeline ----------------------------------------------

async def map_reduce_summarize(
    documents: Iterable[str],
    *,
    focus: str,
    max_tokens: int = MAX_TOOL_TOKENS,
    worker_concurrency: int = 8,
) -> str:
    """Summarise ``documents`` into a single string capped at ``max_tokens``.

    Args:
        documents: Per-document text blobs (e.g. one paper abstract each).
        focus:     What to keep / what to drop. Drives both Map and Reduce.
        max_tokens: Hard cap on the returned text.
        worker_concurrency: Max simultaneous Gemini Flash calls.
    """
    docs = [d for d in documents if d and d.strip()]
    if not docs:
        return "No documents to summarise."

    sem = asyncio.Semaphore(worker_concurrency)

    async def _map_one(doc: str) -> str:
        async with sem:
            prompt = DEFAULT_WORKER_PROMPT.format(focus=focus, doc=cap_tokens(doc, 1500))
            return await _gemini_generate(prompt)

    partials = await asyncio.gather(*(_map_one(d) for d in docs), return_exceptions=True)
    cleaned: list[str] = []
    for i, p in enumerate(partials):
        if isinstance(p, Exception):
            logger.warning("Map worker %d failed: %s", i, p)
            continue
        if isinstance(p, str) and p.strip():
            cleaned.append(p.strip())

    if not cleaned:
        return "Map-Reduce produced no usable extracts."

    # Reduce step — only call the LLM if joined extracts already overshoot.
    joined = "\n\n---\n\n".join(cleaned)
    if estimate_tokens(joined) <= max_tokens:
        return cap_tokens(joined, max_tokens)

    reduce_prompt = DEFAULT_REDUCE_PROMPT.format(focus=focus, partials=joined)
    final = await _gemini_generate(reduce_prompt)
    return cap_tokens(final or joined, max_tokens)
