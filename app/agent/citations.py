"""Citation post-processing (design doc §10.1).

Two responsibilities:

1. ``extract_grounding`` — pull ``grounding_chunks`` + ``grounding_supports``
   out of a Gemini response and convert them into a clean ``[Citation]``
   list keyed by ordinal (1, 2, 3 ...).
2. ``inject_citations`` — rewrite the answer text by appending ``[N]``
   markers next to each grounded segment. For non-Gemini outputs we
   degrade gracefully: if no grounding metadata is supplied, the text
   is returned unchanged.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Citation:
    index: int
    title: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_grounding(grounding_metadata: Any) -> list[Citation]:
    """Convert Gemini ``grounding_metadata`` into ordered ``Citation``s.

    Accepts either the SDK object (with ``grounding_chunks`` attribute)
    or a plain dict (test-friendly).
    """
    if grounding_metadata is None:
        return []

    chunks = (
        getattr(grounding_metadata, "grounding_chunks", None)
        or (grounding_metadata.get("grounding_chunks") if isinstance(grounding_metadata, dict) else None)
        or []
    )

    citations: list[Citation] = []
    for i, chunk in enumerate(chunks, start=1):
        web = getattr(chunk, "web", None) or (chunk.get("web") if isinstance(chunk, dict) else None) or {}
        title = getattr(web, "title", None) or (web.get("title") if isinstance(web, dict) else "") or "untitled"
        url = getattr(web, "uri", None) or (web.get("uri") if isinstance(web, dict) else "") or ""
        citations.append(Citation(index=i, title=str(title), url=str(url)))
    return citations


def inject_citations(text: str, grounding_metadata: Any) -> tuple[str, list[Citation]]:
    """Append ``[N]`` markers to grounded passages.

    Strategy: for each ``grounding_support`` we have ``segment.end_index``
    (char offset in the original answer) and a list of chunk indices.
    We walk supports in reverse offset order so insertions don't shift
    earlier offsets.
    """
    citations = extract_grounding(grounding_metadata)
    if not citations or not text:
        return text, citations

    supports = (
        getattr(grounding_metadata, "grounding_supports", None)
        or (grounding_metadata.get("grounding_supports") if isinstance(grounding_metadata, dict) else None)
        or []
    )
    if not supports:
        # Fallback: append a citations block at the end.
        block = "\n\n参考文献:\n" + "\n".join(
            f"[{c.index}] {c.title} — {c.url}" for c in citations
        )
        return text + block, citations

    insertions: list[tuple[int, str]] = []
    for sup in supports:
        seg = getattr(sup, "segment", None) or (sup.get("segment") if isinstance(sup, dict) else {}) or {}
        end_idx = (
            getattr(seg, "end_index", None)
            if not isinstance(seg, dict)
            else seg.get("end_index")
        )
        chunk_indices = (
            getattr(sup, "grounding_chunk_indices", None)
            or (sup.get("grounding_chunk_indices") if isinstance(sup, dict) else None)
            or []
        )
        if end_idx is None or not chunk_indices:
            continue
        marker = "".join(f"[{i + 1}]" for i in chunk_indices)
        insertions.append((int(end_idx), marker))

    insertions.sort(key=lambda kv: kv[0], reverse=True)
    out = text
    for offset, marker in insertions:
        offset = min(max(offset, 0), len(out))
        out = out[:offset] + marker + out[offset:]

    block = "\n\n参考文献:\n" + "\n".join(
        f"[{c.index}] {c.title} — {c.url}" for c in citations
    )
    return out + block, citations
