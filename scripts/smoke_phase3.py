"""Phase 3 smoke test — tool layer + preprocessing pipeline.

Verifies (per `功能测试与验收文档.md`):
  * AC §2.2 — every tool payload ≤ 3000 tokens (offline check)
  * TC-2.1.1 / TC-2.1.2 — only core tools by default; deferred tools
    surface via ``tool_search`` and become bindable.
  * TC-2.2.1 — UniProt response is hard-pruned through Pydantic.
  * Map-Reduce engine returns within the cap even with huge inputs.

Network is mocked via httpx.MockTransport so the test is deterministic.
Run:  PYTHONPATH=. python scripts/smoke_phase3.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from unittest.mock import patch

import httpx

from app.tools import (
    CORE_TOOL_NAMES,
    DEFERRED_TOOL_NAMES,
    default_registry,
    query_chembl,
    query_uniprot,
    tool_search,
)
from app.tools.mapreduce import map_reduce_summarize
from app.tools.preprocess import MAX_TOOL_TOKENS, cap_tokens, estimate_tokens


def _ok(label: str) -> None:
    print(f"  [ok] {label}")


# --- 1. Token guard -----------------------------------------------------

def test_token_cap() -> None:
    print("== token cap ==")
    huge = "lorem ipsum dolor sit amet. " * 5000  # ~ 35 K tokens
    capped = cap_tokens(huge)
    assert estimate_tokens(capped) <= MAX_TOOL_TOKENS, estimate_tokens(capped)
    assert "truncated by preprocessing" in capped
    _ok("cap_tokens enforces 3000-token ceiling")


# --- 2. Registry / tool search -----------------------------------------

def test_registry_segmentation() -> None:
    print("== registry ==")
    core_names = {t.name for t in default_registry.core_tools()}
    deferred_names = {t.name for t in default_registry.deferred_tools()}
    assert core_names == CORE_TOOL_NAMES, core_names
    assert deferred_names == DEFERRED_TOOL_NAMES, deferred_names
    assert len(default_registry.bind_active()) == len(core_names)
    _ok(f"default System Prompt sees only {len(core_names)} core tools (AC §2.1)")

    # TC-2.1.2: model-style search for chemistry → mounts query_chembl
    raw = tool_search.invoke({"query": "化合物活性数据库 chembl bioactivity"})
    payload = json.loads(raw)
    matched_names = {m["name"] for m in payload["matches"]}
    assert "query_chembl" in matched_names, payload
    _ok("tool_search surfaces query_chembl for 'chemistry activity' query")

    # Hot-mount and confirm bind_active includes it
    active = default_registry.bind_active(hot_loaded={"query_chembl"})
    assert any(t.name == "query_chembl" for t in active)
    _ok("hot-loaded query_chembl now bindable for next turn")


# --- 3. UniProt hard pruning (TC-2.2.1) --------------------------------

UNIPROT_RAW = {
    "primaryAccession": "P00533",
    "uniProtkbId": "EGFR_HUMAN",
    # Tons of irrelevant metadata that MUST be dropped.
    "secondaryAccessions": ["O00688", "O00732"] * 20,
    "annotationScore": 5.0,
    "internalSection": {"junk": "x" * 5000},
    "comments": [
        {
            "commentType": "FUNCTION",
            "texts": [{"value": "Receptor tyrosine kinase binding ligands of the EGF family."}],
        },
        {"commentType": "ALTERNATIVE PRODUCTS", "events": ["Alternative splicing"]},
    ],
    "genes": [{"geneName": {"value": "EGFR"}}],
    "organism": {"scientificName": "Homo sapiens"},
    "sequence": {"length": 1210, "value": "M" + "X" * 5000},
    "keywords": [{"name": "Kinase"}, {"name": "Membrane"}, {"name": "Tyrosine-protein kinase"}],
    "proteinDescription": {"recommendedName": {"fullName": {"value": "Epidermal growth factor receptor"}}},
}


async def test_uniprot_pruning() -> None:
    print("== uniprot pruning ==")

    async def handler(req: httpx.Request) -> httpx.Response:
        assert "uniprot.org" in req.url.host
        return httpx.Response(200, json=UNIPROT_RAW)

    transport = httpx.MockTransport(handler)

    real_AsyncClient = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_AsyncClient(*args, **kwargs)

    with patch("app.tools.base.httpx.AsyncClient", patched_client):
        out = await query_uniprot.ainvoke({"query": "P00533"})

    assert estimate_tokens(out) <= MAX_TOOL_TOKENS
    assert "P00533" in out and "EGFR" in out and "1210" in out
    # NONE of the dropped junk should leak through:
    forbidden = ["secondaryAccessions", "annotationScore", "internalSection",
                 "ALTERNATIVE PRODUCTS", "X" * 50]
    for f in forbidden:
        assert f not in out, f"leaked: {f}"
    _ok("UniProt response shrunk to 5 curated fields (TC-2.2.1)")


# --- 4. ChEMBL pruning -------------------------------------------------

CHEMBL_RAW = {
    "molecule_chembl_id": "CHEMBL25",
    "pref_name": "ASPIRIN",
    "molecule_structures": {
        "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O",
        "standard_inchi_key": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "molfile": "x" * 8000,  # huge raw blob — must NOT survive
    },
    "max_phase": 4,
    "biotherapeutic": {"helm_notation": "y" * 4000},  # also dropped
    "atc_classifications": ["N02BA01"] * 30,
}


async def test_chembl_pruning() -> None:
    print("== chembl pruning ==")

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CHEMBL_RAW)

    transport = httpx.MockTransport(handler)
    real_AsyncClient = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_AsyncClient(*args, **kwargs)

    with patch("app.tools.base.httpx.AsyncClient", patched_client):
        out = await query_chembl.ainvoke({"query": "CHEMBL25"})

    assert "CHEMBL25" in out and "ASPIRIN" in out
    assert "molfile" not in out and "helm_notation" not in out
    assert estimate_tokens(out) <= MAX_TOOL_TOKENS
    _ok("ChEMBL response pruned to 4 core fields (TC-2.2.1)")


# --- 5. Map-Reduce engine (offline fallback) ---------------------------

async def test_mapreduce() -> None:
    print("== map-reduce ==")
    docs = [
        f"Paper {i}: We studied EGFR T790M resistance to gefitinib. "
        f"Our results show that osimertinib retains efficacy (PMID: 1000{i}). "
        + ("filler context " * 200)
        for i in range(20)
    ]
    out = await map_reduce_summarize(docs, focus="T790M resistance and third-generation TKIs")
    assert out and isinstance(out, str)
    assert estimate_tokens(out) <= MAX_TOOL_TOKENS
    _ok(f"Map-Reduce 20×heavy docs → {estimate_tokens(out)} tokens (≤ {MAX_TOOL_TOKENS})")


async def main() -> int:
    test_token_cap()
    test_registry_segmentation()
    await test_uniprot_pruning()
    await test_chembl_pruning()
    await test_mapreduce()
    print("\nAll Phase 3 smoke checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
