"""Phase 4 smoke test — Prompt rendering + LangGraph ReAct loop + citations.

All scenarios run against ``FakeLLMProvider`` so no network is required.

Verifies:
  * System Prompt has all dynamic slots filled (time, tools, memory).
  * <thought> pre-fill is injected on every turn.
  * Conditional edge: tool_calls → tool node; no calls → finalize.
  * Tool search → auto hot-mount → next turn sees the new tool.
  * inject_citations adds [N] markers + reference block from
    Gemini-style grounding metadata.
"""

from __future__ import annotations

import asyncio
import sys

from langchain_core.messages import AIMessage

from app.agent.agent import run_once
from app.agent.citations import inject_citations
from app.agent.llm_provider import AIResponse, FakeLLMProvider, ToolCallRequest
from app.agent.prompt_renderer import assistant_prefill, render_system_prompt


def _ok(label: str) -> None:
    print(f"  [ok] {label}")


def test_prompt_renderer() -> None:
    print("== prompt renderer ==")
    text = render_system_prompt(
        active_tools=["query_pubmed", "tool_search"],
        hot_loaded={"query_chembl"},
        session_memory="先前讨论的核心靶点：EGFR T790M",
        system_status="ready",
    )
    assert "Antigravity" in text
    assert "query_pubmed" in text and "tool_search" in text
    assert "query_chembl" in text  # hot_loaded_hint rendered
    assert "EGFR T790M" in text
    assert "<critical_rules>" in text
    _ok("System Prompt fills active_tools / hot_loaded / memory slots")

    assert assistant_prefill() == "<thought>\n"
    _ok("Assistant pre-fill = '<thought>\\n'")


async def test_simple_answer() -> None:
    print("== simple answer (no tools) ==")
    provider = FakeLLMProvider(script=[
        AIResponse(text="<thought>simple</thought><answer>EGFR 是受体酪氨酸激酶。</answer>")
    ])
    state = await run_once(provider, "EGFR 是什么？")
    assert "EGFR" in state["final_text"]
    assert isinstance(state["citations"], list) and state["citations"] == []
    _ok("no-tool path → finalize directly")


async def test_react_with_tool_search() -> None:
    print("== ReAct + hot-mount via tool_search ==")
    provider = FakeLLMProvider(script=[
        # Turn 1: model asks tool_search to find a chemistry tool.
        AIResponse(
            text="<thought>need chemistry db</thought>",
            tool_calls=[ToolCallRequest(
                name="tool_search",
                args={"query": "化合物活性 chembl bioactivity"},
                id="call-1",
            )],
        ),
        # Turn 2: now the model calls the freshly-mounted query_chembl.
        AIResponse(
            text="<thought>using new tool</thought>",
            tool_calls=[ToolCallRequest(
                name="query_chembl",
                args={"query": "CHEMBL25"},
                id="call-2",
            )],
        ),
        # Turn 3: final answer.
        AIResponse(
            text="<thought>done</thought><answer>CHEMBL25 是阿司匹林。</answer>",
        ),
    ])

    # Patch query_chembl so the test stays offline.
    import app.agent.agent as agent_mod
    orig = agent_mod._execute_tool_call

    def fake_exec(name: str, args: dict) -> str:
        if name == "query_chembl":
            return "| ChEMBL ID | Name |\n|---|---|\n| CHEMBL25 | ASPIRIN |"
        return orig(name, args)

    agent_mod._execute_tool_call = fake_exec
    try:
        state = await run_once(provider, "请帮我查 CHEMBL25 是什么。")
    finally:
        agent_mod._execute_tool_call = orig

    assert "query_chembl" in state["hot_loaded"], state["hot_loaded"]
    assert "阿司匹林" in state["final_text"]
    # We should have seen 3 AI turns (initial, post-search, post-chembl).
    ai_turns = [m for m in state["messages"] if isinstance(m, AIMessage)]
    assert len(ai_turns) == 3, len(ai_turns)
    _ok("tool_search → auto hot-mount → query_chembl callable next turn")


def test_citation_injection() -> None:
    print("== citation injection ==")
    answer = "EGFR T790M 突变与第三代 TKI 耐药相关。"
    end_idx = len(answer)  # after the period
    grounding = {
        "grounding_chunks": [
            {"web": {"title": "Ref A", "uri": "https://example.com/a"}},
            {"web": {"title": "Ref B", "uri": "https://example.com/b"}},
        ],
        "grounding_supports": [
            {"segment": {"end_index": end_idx}, "grounding_chunk_indices": [0, 1]},
        ],
    }
    text, citations = inject_citations(answer, grounding)
    assert "[1][2]" in text, text
    assert "参考文献" in text
    assert citations[0].url == "https://example.com/a"
    _ok("grounding_metadata → [1][2] markers + reference block")


async def main() -> int:
    test_prompt_renderer()
    await test_simple_answer()
    await test_react_with_tool_search()
    test_citation_injection()
    print("\nAll Phase 4 smoke checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
