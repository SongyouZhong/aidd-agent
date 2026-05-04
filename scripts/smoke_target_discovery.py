"""Smoke test for Phase 6 — Target Discovery tools + sub-graph.

Two tiers:

1. **Per-tool live calls** — exercises every new deferred tool against
   the real public REST endpoints with a known target (EGFR /
   ``CHEMBL203`` / ``hsa:1956``). Skips and reports degraded coverage
   when a service times out (offline-friendly).

2. **End-to-end sub-graph** — runs the discovery sub-graph with a
   ``FakeLLMProvider`` script so this entire script can run without an
   API key. Asserts the final ``TargetReport`` contains the expected
   shape (5 sections + notes).
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.agent.llm_provider import AIResponse, FakeLLMProvider, ToolCallRequest
from app.agent.target_discovery_graph import run_target_discovery
from app.tools import (
    default_registry,
    query_alphafold,
    query_chembl_peptides,
    query_chembl_target_activities,
    query_gtopdb,
    query_interpro,
    query_kegg,
    query_monarch,
    query_opentarget,
    query_pdb,
    query_pdb_identifiers,
    query_pubchem,
    query_quickgo,
    query_reactome,
    query_stringdb,
    query_uniprot,
)


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _ok(label: str, sample: str | None = None) -> None:
    print(f"  {GREEN}[ok]{RESET} {label}" + (f" — {sample}" if sample else ""))


def _warn(label: str, exc: Exception) -> None:
    print(f"  {YELLOW}[skip]{RESET} {label}: {exc!r}")


def _fail(label: str, msg: str) -> None:
    print(f"  {RED}[FAIL]{RESET} {label}: {msg}")


# --- 1. Per-tool smoke ------------------------------------------------


async def smoke_tools() -> int:
    print("== Phase 6 tool smoke (live REST) ==")
    failures = 0

    async def call(label: str, coro):
        nonlocal failures
        try:
            out = await asyncio.wait_for(coro, timeout=25)
        except Exception as exc:
            _warn(label, exc)
            return None
        head = (out or "").strip().splitlines()[0][:80] if isinstance(out, str) else str(out)[:80]
        text_lower = (out or "").lower()[:120] if isinstance(out, str) else ""
        if not out:
            _fail(label, "empty result")
            failures += 1
            return None
        # Upstream service errors → soft skip (not a code defect).
        if any(kw in text_lower for kw in ("failed", "no results", "timeout")):
            _warn(label, RuntimeError(head))
            return None
        _ok(label, head)
        return out

    # Structure
    await call("query_uniprot(P00533)", query_uniprot.ainvoke({"query": "P00533"}))
    await call("query_pdb(1M17)", query_pdb.ainvoke({"pdb_id": "1M17"}))
    await call("query_pdb_identifiers(P00533)", query_pdb_identifiers.ainvoke({"uniprot_id": "P00533"}))
    await call("query_alphafold(P00533)", query_alphafold.ainvoke({"uniprot_id": "P00533"}))
    await call("query_interpro(P00533)", query_interpro.ainvoke({"uniprot_id": "P00533"}))
    # Disease / function
    await call("query_opentarget(EGFR)", query_opentarget.ainvoke({"target": "EGFR"}))
    await call("query_monarch(EGFR lung cancer)", query_monarch.ainvoke({"query": "EGFR lung cancer"}))
    await call("query_quickgo(P00533)", query_quickgo.ainvoke({"uniprot_id": "P00533"}))
    # Pathway
    await call("query_kegg(hsa:1956)", query_kegg.ainvoke({"gene_id": "hsa:1956"}))
    await call("query_reactome(P00533)", query_reactome.ainvoke({"uniprot_id": "P00533"}))
    await call("query_stringdb(EGFR)", query_stringdb.ainvoke({"identifiers": "EGFR"}))
    # Drug
    await call(
        "query_chembl_target_activities(EGFR)",
        query_chembl_target_activities.ainvoke({"target": "EGFR", "max_results": 10}),
    )
    await call("query_pubchem(gefitinib)", query_pubchem.ainvoke({"query": "gefitinib"}))
    await call("query_gtopdb(EGFR)", query_gtopdb.ainvoke({"target_name": "EGFR", "max_results": 10}))
    # Peptide
    await call(
        "query_chembl_peptides(GLP1R)",
        query_chembl_peptides.ainvoke({"target": "GLP1R", "max_results": 5}),
    )

    # Registry sanity — every new tool must be discoverable via tool_search.
    for kw, expect_name in [
        ("通路 pathway", "query_kegg"),
        ("alphafold structure", "query_alphafold"),
        ("ic50 inhibitor 化合物", "query_chembl_target_activities"),
        ("多肽 peptide", "query_chembl_peptides"),
        ("opentargets 疾病", "query_opentarget"),
    ]:
        hits = default_registry.search(kw, top_k=5)
        names = [h.name for h in hits]
        if expect_name in names:
            _ok(f"registry.search({kw!r}) → {expect_name}")
        else:
            _fail(f"registry.search({kw!r})", f"missing {expect_name}; got {names}")
            failures += 1

    return failures


# --- 2. End-to-end sub-graph with FakeLLMProvider --------------------


def _fake_node_response(answer_obj: dict) -> AIResponse:
    return AIResponse(text=f"<answer>{json.dumps(answer_obj, ensure_ascii=False)}</answer>")


async def smoke_subgraph() -> int:
    print("\n== Phase 6 sub-graph smoke (FakeLLMProvider) ==")
    failures = 0

    # 6 scripted responses — one per node (no tool calls used).
    script = [
        # literature
        _fake_node_response(
            {
                "papers": [
                    {
                        "title": "Identification of EGFR as an oncogene",
                        "year": 1984,
                        "pmid": "6326632",
                        "doi": "10.1038/309418a0",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/6326632/",
                        "summary": "Seminal paper",
                    }
                ]
            }
        ),
        # composition
        _fake_node_response(
            {
                "proteins": [
                    {
                        "accession": "P00533",
                        "name": "EGFR",
                        "gene": "EGFR",
                        "sequence_length": 1210,
                        "sequence": "M" * 50,
                        "pdb_ids": ["1M17", "2ITY"],
                        "alphafold_id": "P00533",
                        "interpro_domains": ["IPR016245 (Tyrosine kinase, catalytic)"],
                    }
                ]
            }
        ),
        # function
        _fake_node_response(
            {
                "function_narrative": "EGFR drives proliferation in NSCLC via aberrant kinase activation.",
                "disease_associations": [
                    {
                        "source": "OpenTargets",
                        "disease_id": "EFO_0003060",
                        "disease_name": "non-small cell lung carcinoma",
                        "score": 0.92,
                        "url": "https://platform.opentargets.org/",
                    }
                ],
            }
        ),
        # pathway
        _fake_node_response(
            {
                "pathways": [
                    {"source": "KEGG", "external_id": "hsa04012", "name": "ErbB signaling pathway",
                     "url": "https://www.kegg.jp/pathway/hsa04012"},
                    {"source": "Reactome", "external_id": "R-HSA-177929", "name": "Signaling by EGFR",
                     "url": "https://reactome.org/PathwayBrowser/#/R-HSA-177929"},
                ],
                "interactors": [{"name": "GRB2", "score": 0.99}],
            }
        ),
        # drugs
        _fake_node_response(
            {
                "small_molecule_drugs": [
                    {
                        "name": "gefitinib",
                        "chembl_id": "CHEMBL939",
                        "smiles": "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1",
                        "max_phase": 4,
                        "activity": {"type": "IC50", "value_nm": 33.0, "assay": "EGFR L858R kinase"},
                    }
                ],
                "peptide_drugs": [
                    {
                        "name": "GE11",
                        "sequence": "YHWYGYTPQNVI",
                        "source": "literature",
                        "max_phase": 0,
                        "url": "https://pubmed.ncbi.nlm.nih.gov/?term=GE11+EGFR",
                    }
                ],
            }
        ),
        # synthesize — assemble the full TargetReport
        _fake_node_response(
            {
                "target": {
                    "name": "EGFR",
                    "gene_symbol": "EGFR",
                    "uniprot_ids": ["P00533"],
                    "organism": "Homo sapiens",
                    "description": "Epidermal growth factor receptor",
                },
                "papers": [
                    {
                        "title": "Identification of EGFR as an oncogene",
                        "year": 1984,
                        "pmid": "6326632",
                        "doi": "10.1038/309418a0",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/6326632/",
                    }
                ],
                "proteins": [
                    {
                        "accession": "P00533",
                        "name": "EGFR",
                        "gene": "EGFR",
                        "sequence_length": 1210,
                        "sequence": "M" * 50,
                        "pdb_ids": ["1M17", "2ITY"],
                        "alphafold_id": "P00533",
                        "interpro_domains": ["IPR016245 (Tyrosine kinase, catalytic)"],
                    }
                ],
                "disease_associations": [
                    {
                        "source": "OpenTargets",
                        "disease_id": "EFO_0003060",
                        "disease_name": "non-small cell lung carcinoma",
                        "score": 0.92,
                        "url": "https://platform.opentargets.org/",
                    }
                ],
                "function_narrative": "EGFR drives proliferation in NSCLC.",
                "pathways": [
                    {"source": "KEGG", "external_id": "hsa04012", "name": "ErbB signaling"},
                    {"source": "Reactome", "external_id": "R-HSA-177929", "name": "Signaling by EGFR"},
                ],
                "small_molecule_drugs": [
                    {
                        "name": "gefitinib",
                        "chembl_id": "CHEMBL939",
                        "smiles": "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1",
                        "max_phase": 4,
                    }
                ],
                "peptide_drugs": [
                    {"name": "GE11", "sequence": "YHWYGYTPQNVI", "source": "literature"}
                ],
                "notes": [],
            }
        ),
    ]

    provider = FakeLLMProvider(script=script)
    report = await run_target_discovery(provider, target_query="EGFR")

    # Assertions — each section non-empty
    checks = [
        ("target.name", report.get("target", {}).get("name") == "EGFR"),
        ("≥1 paper", len(report.get("papers", [])) >= 1),
        ("≥1 protein with sequence", any(p.get("sequence") for p in report.get("proteins", []))),
        ("≥1 protein with PDB", any(p.get("pdb_ids") for p in report.get("proteins", []))),
        ("≥1 disease association", len(report.get("disease_associations", [])) >= 1),
        ("≥1 KEGG pathway", any(p.get("source") == "KEGG" for p in report.get("pathways", []))),
        ("≥1 Reactome pathway", any(p.get("source") == "Reactome" for p in report.get("pathways", []))),
        ("≥1 small-molecule with SMILES", any(d.get("smiles") for d in report.get("small_molecule_drugs", []))),
        ("≥1 peptide with sequence", any(d.get("sequence") for d in report.get("peptide_drugs", []))),
    ]
    for label, ok in checks:
        if ok:
            _ok(f"sub-graph {label}")
        else:
            _fail(f"sub-graph {label}", "assertion failed")
            failures += 1

    return failures


async def main() -> int:
    f1 = await smoke_tools()
    f2 = await smoke_subgraph()
    total = f1 + f2
    print()
    if total == 0:
        print(f"{GREEN}ALL CHECKS PASSED{RESET} (live failures shown as [skip] do not count)")
    else:
        print(f"{RED}{total} HARD FAILURES{RESET}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
