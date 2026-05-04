"""Target-Discovery LangGraph sub-graph (design doc §7.4 — Phase 6).

Fixed-node pipeline:

    START
      → literature_node    (PubMed / arXiv)
      → composition_node   (UniProt / PDB / AlphaFold / InterPro)
      → function_node      (OpenTargets / Monarch / QuickGO)
      → pathway_node       (KEGG / Reactome / STRING)
      → drugs_node         (ChEMBL target-act / PubChem / GtoPdb / peptides)
      → synthesize_node    (no tools — assembles TargetReport)
      → END

Each node runs a bounded ReAct loop (max ``MAX_NODE_STEPS`` LLM turns)
binding only its allowed tool subset. On any error / timeout the node
stores a ``notes`` entry and the pipeline still proceeds — the design
goal is "always produce a partial report" (plan §Further Considerations).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.llm_provider import AIResponse
from app.agent.prompts.target_discovery import (
    COMPOSITION_NODE_PROMPT,
    DRUGS_NODE_PROMPT,
    FUNCTION_NODE_PROMPT,
    LITERATURE_NODE_PROMPT,
    PATHWAY_NODE_PROMPT,
    SYNTHESIZE_PROMPT,
)
from app.tools import default_registry

logger = logging.getLogger(__name__)


MAX_NODE_STEPS = 5
NODE_TIMEOUT_SECONDS = 60.0


# Tool subsets per node — names must match registered tool names.
LITERATURE_TOOLS = ["query_pubmed", "query_arxiv"]
COMPOSITION_TOOLS = [
    "query_uniprot",
    "query_pdb",
    "query_pdb_identifiers",
    "query_alphafold",
    "query_interpro",
]
FUNCTION_TOOLS = ["query_opentarget", "query_monarch", "query_quickgo"]
PATHWAY_TOOLS = ["query_kegg", "query_reactome", "query_stringdb"]
DRUGS_TOOLS = [
    "query_chembl_target_activities",
    "query_pubchem",
    "query_gtopdb",
    "query_chembl_peptides",
]


class TargetDiscoveryState(TypedDict, total=False):
    target_query: str
    messages: Annotated[list[BaseMessage], add_messages]
    sub_results: dict[str, Any]
    notes: list[str]
    final_report: dict[str, Any]


# --- helpers ----------------------------------------------------------


def _resolve_tools(names: list[str]) -> list[Any]:
    out = []
    for n in names:
        impl = default_registry.get(n)
        if impl is not None:
            out.append(impl)
    return out


def _render(template: str, **kwargs: Any) -> str:
    text = template
    for k, v in kwargs.items():
        text = text.replace("{{ " + k + " }}", str(v))
    return text


async def _invoke_tool(name: str, args: dict[str, Any]) -> str:
    impl = default_registry.get(name)
    if impl is None:
        return f"[error] tool '{name}' not loaded"
    if getattr(impl, "coroutine", None) is not None:
        result = await impl.ainvoke(args)
    else:
        result = impl.invoke(args)
    return str(result)


def _extract_answer_json(text: str) -> dict[str, Any] | None:
    """Pull the first ``{...}`` JSON object out of an <answer> block."""
    if not text:
        return None
    blob = text
    if "<answer>" in text:
        start = text.find("<answer>") + len("<answer>")
        end = text.find("</answer>", start)
        blob = text[start:end] if end > start else text[start:]
    # Greedy match the outermost {...}
    first = blob.find("{")
    last = blob.rfind("}")
    if first == -1 or last <= first:
        return None
    try:
        return json.loads(blob[first : last + 1])
    except Exception:
        return None


async def _run_node_loop(
    *,
    provider: Any,
    system_prompt: str,
    user_prompt: str,
    tool_names: list[str],
    max_steps: int = MAX_NODE_STEPS,
) -> tuple[str, list[BaseMessage]]:
    """Bounded ReAct loop scoped to ``tool_names``. Returns (last_text, msgs)."""
    tools = _resolve_tools(tool_names)
    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    last_text = ""
    for _ in range(max_steps):
        resp: AIResponse = await provider.generate(messages=messages, tools=tools)
        last_text = resp.text or ""
        ai_msg = AIMessage(
            content=last_text,
            tool_calls=[
                {"id": tc.id, "name": tc.name, "args": tc.args}
                for tc in resp.tool_calls
            ],
        )
        messages.append(ai_msg)
        if not resp.tool_calls:
            break
        for tc in resp.tool_calls:
            try:
                tool_out = await _invoke_tool(tc.name, tc.args)
            except Exception as exc:
                tool_out = f"[tool error] {exc}"
            messages.append(
                ToolMessage(content=tool_out, name=tc.name, tool_call_id=tc.id)
            )
    return last_text, messages


async def _safe_node(
    *,
    name: str,
    provider: Any,
    target_query: str,
    template: str,
    tool_names: list[str],
    prior_context: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Run one node, catch exceptions and timeouts, return (result, notes)."""
    sys_prompt = _render(template, target_query=target_query)
    user_prompt = f"开始执行节点 [{name}]，目标靶点：{target_query}。"
    if prior_context:
        user_prompt += f"\n\n先前节点已确认的信息（请直接使用这些 ID，不要自行推测）：\n{prior_context}"
    try:
        last_text, _ = await asyncio.wait_for(
            _run_node_loop(
                provider=provider,
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                tool_names=tool_names,
            ),
            timeout=NODE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return {}, [f"节点 [{name}] 超时（>{NODE_TIMEOUT_SECONDS:.0f}s），跳过。"]
    except Exception as exc:
        logger.exception("Node %s failed", name)
        return {}, [f"节点 [{name}] 异常：{exc!r}"]
    parsed = _extract_answer_json(last_text)
    if parsed is None:
        return {}, [f"节点 [{name}] 未输出可解析的 JSON。"]
    return parsed, []


# --- node definitions -------------------------------------------------


def _resolved_accession_context(sub_results: dict[str, Any]) -> str | None:
    """Extract a short context string from the composition node's output.

    Returns e.g. "UniProt accession: Q13148 (gene: TARDBP)" so that
    downstream nodes can call tools with the correct IDs rather than
    relying on the LLM to guess them.
    """
    comp = sub_results.get("composition") or {}
    proteins = comp.get("proteins") or []
    if not proteins:
        return None
    parts = []
    for p in proteins[:3]:  # at most 3 chains
        acc = p.get("accession")
        gene = p.get("gene")
        if acc:
            parts.append(f"UniProt accession: {acc}" + (f" (gene: {gene})" if gene else ""))
    return "\n".join(parts) if parts else None


def build_target_discovery_graph(provider: Any):
    """Compile the target-discovery sub-graph bound to ``provider``."""

    async def literature_node(state: TargetDiscoveryState) -> dict[str, Any]:
        result, notes = await _safe_node(
            name="literature",
            provider=provider,
            target_query=state["target_query"],
            template=LITERATURE_NODE_PROMPT,
            tool_names=LITERATURE_TOOLS,
        )
        sub = dict(state.get("sub_results") or {})
        sub["literature"] = result
        return {"sub_results": sub, "notes": (state.get("notes") or []) + notes}

    async def composition_node(state: TargetDiscoveryState) -> dict[str, Any]:
        result, notes = await _safe_node(
            name="composition",
            provider=provider,
            target_query=state["target_query"],
            template=COMPOSITION_NODE_PROMPT,
            tool_names=COMPOSITION_TOOLS,
        )
        sub = dict(state.get("sub_results") or {})
        sub["composition"] = result
        return {"sub_results": sub, "notes": (state.get("notes") or []) + notes}

    async def function_node(state: TargetDiscoveryState) -> dict[str, Any]:
        result, notes = await _safe_node(
            name="function",
            provider=provider,
            target_query=state["target_query"],
            template=FUNCTION_NODE_PROMPT,
            tool_names=FUNCTION_TOOLS,
            prior_context=_resolved_accession_context(state.get("sub_results") or {}),
        )
        sub = dict(state.get("sub_results") or {})
        sub["function"] = result
        return {"sub_results": sub, "notes": (state.get("notes") or []) + notes}

    async def pathway_node(state: TargetDiscoveryState) -> dict[str, Any]:
        result, notes = await _safe_node(
            name="pathway",
            provider=provider,
            target_query=state["target_query"],
            template=PATHWAY_NODE_PROMPT,
            tool_names=PATHWAY_TOOLS,
            prior_context=_resolved_accession_context(state.get("sub_results") or {}),
        )
        sub = dict(state.get("sub_results") or {})
        sub["pathway"] = result
        return {"sub_results": sub, "notes": (state.get("notes") or []) + notes}

    async def drugs_node(state: TargetDiscoveryState) -> dict[str, Any]:
        result, notes = await _safe_node(
            name="drugs",
            provider=provider,
            target_query=state["target_query"],
            template=DRUGS_NODE_PROMPT,
            tool_names=DRUGS_TOOLS,
            prior_context=_resolved_accession_context(state.get("sub_results") or {}),
        )
        sub = dict(state.get("sub_results") or {})
        sub["drugs"] = result
        return {"sub_results": sub, "notes": (state.get("notes") or []) + notes}

    async def synthesize_node(state: TargetDiscoveryState) -> dict[str, Any]:
        sub_results = state.get("sub_results") or {}
        sub_json = json.dumps(sub_results, ensure_ascii=False, indent=2)
        sys_prompt = _render(SYNTHESIZE_PROMPT, sub_results_json=sub_json)
        user_prompt = (
            f"靶点：{state['target_query']}。请整合上述子节点结果输出 TargetReport。"
        )
        try:
            resp = await asyncio.wait_for(
                provider.generate(
                    messages=[
                        SystemMessage(content=sys_prompt),
                        HumanMessage(content=user_prompt),
                    ],
                    tools=None,
                ),
                timeout=NODE_TIMEOUT_SECONDS,
            )
            text = resp.text
        except asyncio.TimeoutError:
            text = ""

        report = _extract_answer_json(text) or {}
        # Always carry forward node-level notes.
        existing_notes = list(report.get("notes") or [])
        existing_notes.extend(state.get("notes") or [])
        report["notes"] = existing_notes
        # Ensure target field is at minimum set.
        report.setdefault(
            "target",
            {
                "name": state["target_query"],
                "gene_symbol": None,
                "uniprot_ids": [],
                "organism": "Homo sapiens",
            },
        )
        return {"final_report": report}

    graph = StateGraph(TargetDiscoveryState)
    graph.add_node("literature", literature_node)
    graph.add_node("composition", composition_node)
    graph.add_node("function", function_node)
    graph.add_node("pathway", pathway_node)
    graph.add_node("drugs", drugs_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "literature")
    graph.add_edge("literature", "composition")
    graph.add_edge("composition", "function")
    graph.add_edge("function", "pathway")
    graph.add_edge("pathway", "drugs")
    graph.add_edge("drugs", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


async def run_target_discovery(
    provider: Any, target_query: str
) -> dict[str, Any]:
    """One-shot helper. Returns the final ``TargetReport`` dict."""
    graph = build_target_discovery_graph(provider)
    initial: TargetDiscoveryState = {
        "target_query": target_query,
        "messages": [],
        "sub_results": {},
        "notes": [],
        "final_report": {},
    }
    final_state = await graph.ainvoke(initial)
    return final_state.get("final_report") or {}
