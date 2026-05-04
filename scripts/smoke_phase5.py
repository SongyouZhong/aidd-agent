"""Phase 5 smoke test — Subagent + Auto-Compaction + Circuit Breaker.

Runs entirely against ``FakeLLMProvider``; no Gemini/network/S3 needed.
"""

from __future__ import annotations

import asyncio
import sys

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.agent import run_once
from app.agent.context_manager import (
    CompactTrackingState,
    apply_compaction,
    count_tokens_messages,
    get_auto_compact_threshold,
    maybe_compact,
    should_auto_compact,
)
from app.agent.llm_provider import AIResponse, FakeLLMProvider, ToolCallRequest
from app.agent.subagent import make_deep_research_tool


def _ok(label: str) -> None:
    print(f"  [ok] {label}")


# --- 1. Dynamic threshold + token counting ----------------------------

def test_threshold() -> None:
    print("== dynamic threshold ==")
    qwen_th = get_auto_compact_threshold("Qwen3.6-35B-A3B-FP8")
    flash_th = get_auto_compact_threshold("gemini-2.5-flash")
    # Qwen has a 128K window; threshold must be < that.
    assert 80_000 < qwen_th < 131_072, qwen_th
    # Gemini has 1M window; threshold should be much larger.
    assert flash_th > qwen_th
    _ok(f"Qwen threshold={qwen_th}, Gemini threshold={flash_th}")


# --- 2. Session-memory (Level 1) compaction ---------------------------

async def test_session_memory_compaction() -> None:
    print("== Level-1 (session memory) compaction ==")
    # Build oversized history: 60 messages, each ~5K tokens of filler.
    chunk = "X" * 15_000  # 5000 tokens per message via len/3 estimate
    msgs = []
    for i in range(60):
        msgs.append(HumanMessage(content=f"u-{i} {chunk}"))
        msgs.append(AIMessage(content=f"a-{i} {chunk}"))

    tracking = CompactTrackingState()
    assert should_auto_compact(msgs, model="Qwen3.6-35B-A3B-FP8", tracking=tracking)

    result = await maybe_compact(
        msgs,
        model="Qwen3.6-35B-A3B-FP8",
        tracking=tracking,
        summarizer=None,  # forces Level 1
        session_memory="先前讨论：EGFR T790M 突变与第三代 TKI 耐药相关 (PMID: 12345678)",
    )
    assert result is not None and result.method == "session_memory", result
    new_msgs = apply_compaction(list(msgs), result)
    # Summary system message + retained tail < original count.
    assert len(new_msgs) < len(msgs)
    assert isinstance(new_msgs[0], SystemMessage)
    assert "EGFR T790M" in new_msgs[0].content
    assert tracking.compacted is True
    assert tracking.consecutive_failures == 0
    _ok(f"reduced {len(msgs)} → {len(new_msgs)} messages via Session Memory")


# --- 3. LLM (Level 2) compaction ---------------------------------------

async def test_llm_compaction() -> None:
    print("== Level-2 (LLM) compaction ==")
    chunk = "Y" * 15_000
    msgs = [HumanMessage(content=f"u-{i} {chunk}") for i in range(80)]
    tracking = CompactTrackingState()

    calls = {"n": 0}

    async def fake_summarizer(_):
        calls["n"] += 1
        return "<summary>压缩后摘要：80 条对话 → 1 段</summary>"

    result = await maybe_compact(
        msgs,
        model="Qwen3.6-35B-A3B-FP8",
        tracking=tracking,
        summarizer=fake_summarizer,
        session_memory=None,  # forces Level 2
    )
    assert result is not None and result.method == "llm_summary"
    assert calls["n"] == 1
    assert "压缩后摘要" in result.summary_messages[0].content
    _ok("LLM summarizer invoked once; summary captured")


# --- 4. Circuit breaker --------------------------------------------------

async def test_circuit_breaker() -> None:
    print("== circuit breaker ==")
    chunk = "Z" * 15_000
    msgs = [HumanMessage(content=f"u-{i} {chunk}") for i in range(80)]
    tracking = CompactTrackingState()

    async def boom(_):
        raise RuntimeError("simulated LLM failure")

    for i in range(1, 5):
        await maybe_compact(
            msgs,
            model="Qwen3.6-35B-A3B-FP8",
            tracking=tracking,
            summarizer=boom,
            session_memory=None,
        )
        if i <= 3:
            assert tracking.consecutive_failures == i, (i, tracking)
        else:
            # After 3 failures the breaker trips and short-circuits.
            assert tracking.consecutive_failures == 3
    _ok(f"trip at {tracking.consecutive_failures} failures; further calls no-op")


# --- 5. Subagent end-to-end (with patched executor) --------------------

async def test_subagent_e2e() -> None:
    print("== subagent (Agent-Tool Duality) ==")

    # Provider for the CHILD agent — answers in one turn.
    def child_provider_factory():
        return FakeLLMProvider(script=[
            AIResponse(text="<thought>child done</thought>"
                            "<answer>EGFR 是受体酪氨酸激酶 (PMID: 12345678)。</answer>")
        ])

    deep_tool = make_deep_research_tool(
        session_id=None,
        provider_factory=child_provider_factory,
    )

    # Provider for the PARENT agent — first turn calls the AgentTool,
    # second turn produces the final answer.
    parent = FakeLLMProvider(script=[
        AIResponse(
            text="<thought>delegate</thought>",
            tool_calls=[ToolCallRequest(
                name="deep_research_agent",
                args={"target": "EGFR", "task_description": "What is EGFR?"},
                id="call-sub",
            )],
        ),
        AIResponse(
            text="<thought>got it</thought><answer>子代理已确认: EGFR 是 RTK。</answer>",
        ),
    ])

    state = await run_once(
        parent,
        "请使用深度研究子代理回答 EGFR 是什么。",
        extra_tools={"deep_research_agent": deep_tool},
    )
    assert "子代理" in state["final_text"]
    # Parent's history must contain a ToolMessage carrying the child's answer.
    tool_msgs = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs, "no ToolMessage from subagent"
    assert "EGFR" in tool_msgs[0].content
    _ok("parent → AgentTool → child agent → ToolMessage → final answer")


# --- 6. Compaction integrates into the live agent loop ----------------

async def test_compaction_in_agent_loop() -> None:
    print("== compaction triggers inside agent loop ==")

    chunk = "W" * 15_000
    big_history = [HumanMessage(content=f"u-{i} {chunk}") for i in range(80)]

    # Provider always answers final.
    parent = FakeLLMProvider(script=[
        AIResponse(text="<thought>ok</thought><answer>明白。</answer>"),
    ])

    # Build agent + manually inject big history.
    from app.agent.agent import build_agent
    from app.agent.context_manager import CompactTrackingState as CTS

    agent = build_agent(parent)
    tracking = CTS()
    state = await agent.ainvoke({
        "messages": big_history,
        "hot_loaded": set(),
        "session_memory": "Memory: prior discussion about kinase inhibitors.",
        "extra_tools": {},
        "compact_tracking": tracking,
        "model": "Qwen3.6-35B-A3B-FP8",
    })

    assert tracking.compacted is True, tracking
    # After compaction the message list is small (summary + tail + AI reply).
    assert len(state["messages"]) <= 30, len(state["messages"])
    _ok(f"history compacted in-flight (final size={len(state['messages'])})")


async def main() -> int:
    test_threshold()
    await test_session_memory_compaction()
    await test_llm_compaction()
    await test_circuit_breaker()
    await test_subagent_e2e()
    await test_compaction_in_agent_loop()
    print("\nAll Phase 5 smoke checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
