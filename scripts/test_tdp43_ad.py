"""TDP-43 × Alzheimer's Disease Agent Test Suite.

Implements three test plans (A/B/C) with full execution tracing.
Usage:
    python scripts/test_tdp43_ad.py --plan a
    python scripts/test_tdp43_ad.py --plan a,b,c
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from app.agent.agent import AgentState, _execute_tool_call, build_agent
from app.agent.context_manager import CompactTrackingState
from app.agent.llm_provider import AIResponse, GeminiProvider
from app.agent.subagent import make_deep_research_tool
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("test_tdp43")

RESULTS_DIR = Path(__file__).resolve().parent / "results"
FIXED_MODEL = "gemini-2.5-flash"

# ===================================================================
# 1. TraceCollector — collects events, persists to JSON + Markdown
# ===================================================================

@dataclass
class TraceEvent:
    timestamp: str
    event_type: str
    data: dict[str, Any]


@dataclass
class TraceCollector:
    plan_name: str
    events: list[TraceEvent] = field(default_factory=list)
    _start: float = field(default_factory=time.monotonic)

    def add(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append(TraceEvent(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            event_type=event_type,
            data=data,
        ))

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    # --- persistence -------------------------------------------------------

    def save(self, tag: str) -> tuple[Path, Path]:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = f"{self.plan_name}_{ts}"

        json_path = RESULTS_DIR / f"{base}.json"
        json_path.write_text(
            json.dumps(
                {"plan": self.plan_name, "tag": tag, "events": [asdict(e) for e in self.events]},
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf-8",
        )

        md_path = RESULTS_DIR / f"{base}_trace.md"
        md_path.write_text(self._render_markdown(tag), encoding="utf-8")
        return json_path, md_path

    def _render_markdown(self, tag: str) -> str:
        lines = [
            f"# Trace: {self.plan_name} ({tag})",
            f"\nElapsed: {self.elapsed():.1f}s | Events: {len(self.events)}\n",
        ]
        for i, ev in enumerate(self.events, 1):
            lines.append(f"## Step {i} — `{ev.event_type}` ({ev.timestamp})")
            for k, v in ev.data.items():
                txt = str(v)
                if len(txt) > 2000:
                    txt = txt[:2000] + "\n…[truncated]"
                lines.append(f"**{k}**:\n```\n{txt}\n```\n")
        return "\n".join(lines)


# ===================================================================
# 2. TracingProvider — wraps GeminiProvider, intercepts generate()
# ===================================================================

class TracingProvider:
    """Wraps a real GeminiProvider and records every LLM call."""

    def __init__(self, inner: GeminiProvider, collector: TraceCollector) -> None:
        self._inner = inner
        self._collector = collector
        self._call_count = 0

    async def generate(self, messages: list[BaseMessage], tools: list[Any] | None = None) -> AIResponse:
        self._call_count += 1
        call_id = self._call_count

        # Record request
        self._collector.add("LLM_REQUEST", {
            "call_id": call_id,
            "message_count": len(messages),
            "system_prompt": next(
                (m.content[:500] for m in messages if isinstance(m, SystemMessage)), ""
            ),
            "last_user_msg": next(
                (m.content[:500] for m in reversed(messages) if isinstance(m, HumanMessage)), ""
            ),
            "tool_names": [t.name for t in (tools or [])],
        })

        resp = await self._inner.generate(messages, tools)

        # Record response
        self._collector.add("LLM_RESPONSE", {
            "call_id": call_id,
            "text_length": len(resp.text),
            "text_preview": resp.text[:1000],
            "tool_calls": [{"name": tc.name, "args": tc.args} for tc in resp.tool_calls],
            "has_grounding": resp.grounding_metadata is not None,
        })
        return resp


# ===================================================================
# 3. Traced tool execution — monkey-patches _execute_tool_call
# ===================================================================

def make_traced_tool_executor(collector: TraceCollector):
    """Return a patched version of _execute_tool_call that logs everything."""
    original = _execute_tool_call

    def traced(name: str, args: dict[str, Any], extra_tools=None) -> Any:
        collector.add("TOOL_CALL", {"tool": name, "args": args})

        if name == "tool_search":
            collector.add("TOOL_SEARCH", {"query": args.get("query", "")})

        result = original(name, args, extra_tools=extra_tools)

        # Record result (may be awaitable — caller handles that)
        if not hasattr(result, "__await__"):
            content = str(result)
            collector.add("TOOL_RESULT", {
                "tool": name,
                "result_length": len(content),
                "result_preview": content[:1500],
            })

            if name == "tool_search":
                try:
                    payload = json.loads(content)
                    matches = [m.get("name") for m in payload.get("matches", [])]
                    if matches:
                        collector.add("HOT_LOAD", {"tools": matches})
                except Exception:
                    pass

        return result

    return traced


def make_traced_async_tool_executor(collector: TraceCollector):
    """Wraps async tool results for tracing."""
    original = _execute_tool_call

    async def traced_async(name: str, args: dict[str, Any], extra_tools=None) -> Any:
        collector.add("TOOL_CALL", {"tool": name, "args": args})
        if name == "tool_search":
            collector.add("TOOL_SEARCH", {"query": args.get("query", "")})

        result = original(name, args, extra_tools=extra_tools)
        if hasattr(result, "__await__"):
            content = await result
        else:
            content = result

        content_str = str(content)
        collector.add("TOOL_RESULT", {
            "tool": name,
            "result_length": len(content_str),
            "result_preview": content_str[:1500],
        })

        if name == "tool_search":
            try:
                payload = json.loads(content_str)
                matches = [m.get("name") for m in payload.get("matches", [])]
                if matches:
                    collector.add("HOT_LOAD", {"tools": matches})
            except Exception:
                pass

        return content

    return traced_async


# ===================================================================
# 4. Build a traced agent (patches tool_node)
# ===================================================================

def build_traced_agent(provider: TracingProvider, collector: TraceCollector):
    """Build a LangGraph agent where tool_node logs every call."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from typing import Annotated

    from app.agent.agent import AgentState, _strip_system
    from app.agent.citations import inject_citations
    from app.agent.context_manager import apply_compaction, maybe_compact, CompactTrackingState
    from app.agent.prompt_renderer import assistant_prefill, render_system_prompt
    from app.tools import default_registry, tool_search as ts_tool

    async def agent_node(state: AgentState) -> dict[str, Any]:
        tracking = state.get("compact_tracking") or CompactTrackingState()
        model = state.get("model") or FIXED_MODEL

        async def _summarizer(msgs):
            resp = await provider.generate(messages=msgs, tools=None)
            return resp.text

        compact_result = await maybe_compact(
            state["messages"], model=model, tracking=tracking,
            summarizer=_summarizer, session_memory=state.get("session_memory"),
        )
        compacted_messages = state["messages"]
        if compact_result is not None:
            compacted_messages = apply_compaction(list(state["messages"]), compact_result)
            collector.add("COMPACTION", {
                "method": compact_result.method,
                "before": len(state["messages"]),
                "after": len(compacted_messages),
            })

        hot = state.get("hot_loaded") or set()
        active_tools = default_registry.bind_active(hot_loaded=hot)
        extra_tools = state.get("extra_tools") or {}
        active_names = ["tool_search"] + [t.name for t in active_tools] + list(extra_tools.keys())

        system = SystemMessage(content=render_system_prompt(
            active_tools=active_names, hot_loaded=hot,
            session_memory=state.get("session_memory"),
        ))
        history = _strip_system(compacted_messages)
        prefill = AIMessage(content=assistant_prefill())

        result = await provider.generate(
            messages=[system, *history, prefill],
            tools=active_tools + list(extra_tools.values()),
        )

        ai_msg = AIMessage(
            content=result.text,
            tool_calls=[{"id": tc.id, "name": tc.name, "args": tc.args} for tc in result.tool_calls],
        )
        ai_msg.additional_kwargs["grounding_metadata"] = result.grounding_metadata

        out: dict[str, Any] = {"messages": [ai_msg], "compact_tracking": tracking}
        if compact_result is not None:
            from langchain_core.messages import RemoveMessage
            removals = []
            kept_ids = {id(m) for m in compact_result.messages_to_keep}
            for m in state["messages"]:
                if id(m) in kept_ids:
                    continue
                msg_id = getattr(m, "id", None)
                if msg_id:
                    removals.append(RemoveMessage(id=msg_id))
            out["messages"] = [*removals, *compact_result.summary_messages, ai_msg]
        return out

    async def tool_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        new_msgs: list[BaseMessage] = []
        new_hot = set(state.get("hot_loaded") or set())
        extra_tools = state.get("extra_tools") or {}
        traced_exec = make_traced_async_tool_executor(collector)

        for tc in getattr(last, "tool_calls", []) or []:
            name = tc["name"]
            args = tc.get("args", {}) or {}

            # Use traced executor
            content = await traced_exec(name, args, extra_tools=extra_tools)
            new_msgs.append(ToolMessage(content=str(content), name=name, tool_call_id=tc["id"]))

            if name == "tool_search":
                try:
                    payload = json.loads(str(content))
                    for m in payload.get("matches", []):
                        if m.get("name"):
                            new_hot.add(m["name"])
                except Exception:
                    pass

        return {"messages": new_msgs, "hot_loaded": new_hot}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tool"
        return "finalize"

    async def finalize_node(state: AgentState) -> dict[str, Any]:
        last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        if last_ai is None:
            return {"final_text": "", "citations": []}
        gm = last_ai.additional_kwargs.get("grounding_metadata")
        text, citations = inject_citations(last_ai.content, gm)
        return {"final_text": text, "citations": citations}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tool": "tool", "finalize": "finalize"})
    graph.add_edge("tool", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()


# ===================================================================
# 5. Plan A — Multi-tool ReAct chain (single turn)
# ===================================================================

PLAN_A_PROMPT = """\
我在研究 TDP-43 与阿尔茨海默症的关系。请帮我：
1. 搜索 PubMed 找到该领域的关键综述文章
2. 查询 UniProt 获取 TDP-43 (TARDBP) 的蛋白功能信息
3. 在 ChEMBL 中搜索是否有针对 TDP-43 的小分子化合物
4. 在 arXiv 搜索最新的 AI/ML 在 TDP-43 相关疾病中的应用

最后综合以上信息，给出一份结构化分析报告。"""


async def run_plan_a() -> dict[str, Any]:
    """Plan A: multi-tool ReAct in a single turn."""
    logger.info("=== Plan A: Multi-tool ReAct ===")
    collector = TraceCollector(plan_name="planA")
    inner = GeminiProvider(model=FIXED_MODEL)
    provider = TracingProvider(inner, collector)
    agent = build_traced_agent(provider, collector)

    initial: AgentState = {
        "messages": [HumanMessage(content=PLAN_A_PROMPT)],
        "hot_loaded": set(),
        "session_memory": "",
        "extra_tools": {},
        "compact_tracking": CompactTrackingState(),
        "model": FIXED_MODEL,
        "session_id": None,
    }

    try:
        state = await asyncio.wait_for(agent.ainvoke(
            initial, config={"recursion_limit": 40},
        ), timeout=300.0)
    except asyncio.TimeoutError:
        collector.add("ERROR", {"type": "TimeoutError", "msg": "Plan A exceeded 5min"})
        state = initial
    except Exception as exc:
        collector.add("ERROR", {"type": type(exc).__name__, "msg": str(exc)})
        state = initial

    elapsed = collector.elapsed()
    collector.add("PLAN_COMPLETE", {"elapsed_sec": elapsed})
    json_p, md_p = collector.save("plan_a")
    logger.info("Plan A done in %.1fs — %s", elapsed, json_p)
    return {
        "plan": "A", "state": state, "collector": collector,
        "elapsed": elapsed, "json_path": str(json_p), "md_path": str(md_p),
    }


# ===================================================================
# 6. Plan B — Deep Research subagent (single turn)
# ===================================================================

PLAN_B_PROMPT = """\
请启动深度研究子代理，全面调查 TDP-43 在阿尔茨海默症发病机制中的角色，
包括：
- TDP-43 的正常生理功能
- TDP-43 在 AD 脑中的病理表现（磷酸化、截断、聚集）
- TDP-43 病理与 Tau/Amyloid-β 病理的交互作用
- LATE（边缘系统为主的年龄相关 TDP-43 脑病）的概念及分期
- 潜在的治疗靶点和药物开发方向

需要交叉比对至少 PubMed 和 UniProt 的数据。"""


async def run_plan_b() -> dict[str, Any]:
    """Plan B: deep research sub-agent."""
    logger.info("=== Plan B: Deep Research Subagent ===")
    collector = TraceCollector(plan_name="planB")
    inner = GeminiProvider(model=FIXED_MODEL)
    provider = TracingProvider(inner, collector)

    def child_factory():
        child_inner = GeminiProvider(model=FIXED_MODEL)
        return TracingProvider(child_inner, collector)

    deep_tool = make_deep_research_tool(session_id=None, provider_factory=child_factory)
    collector.add("SUBAGENT_START", {"tool": "deep_research_agent"})

    agent = build_traced_agent(provider, collector)
    initial: AgentState = {
        "messages": [HumanMessage(content=PLAN_B_PROMPT)],
        "hot_loaded": set(),
        "session_memory": "",
        "extra_tools": {"deep_research_agent": deep_tool},
        "compact_tracking": CompactTrackingState(),
        "model": FIXED_MODEL,
        "session_id": None,
    }

    try:
        state = await asyncio.wait_for(agent.ainvoke(
            initial, config={"recursion_limit": 80},
        ), timeout=600.0)
    except asyncio.TimeoutError:
        collector.add("ERROR", {"type": "TimeoutError", "msg": "Plan B exceeded 10min"})
        state = initial
    except Exception as exc:
        collector.add("ERROR", {"type": type(exc).__name__, "msg": str(exc)})
        state = initial

    collector.add("SUBAGENT_END", {"done": True})
    elapsed = collector.elapsed()
    collector.add("PLAN_COMPLETE", {"elapsed_sec": elapsed})
    json_p, md_p = collector.save("plan_b")
    logger.info("Plan B done in %.1fs — %s", elapsed, json_p)
    return {
        "plan": "B", "state": state, "collector": collector,
        "elapsed": elapsed, "json_path": str(json_p), "md_path": str(md_p),
    }


# ===================================================================
# 7. Plan C — Multi-turn progressive exploration (5 turns)
# ===================================================================

PLAN_C_TURNS = [
    "TDP-43 是什么蛋白？它的主要功能是什么？",
    "这个蛋白在哪些神经退行性疾病中有病理作用？",
    "特别是在阿尔茨海默症中，TDP-43 的具体病理机制是什么？",
    "LATE 是什么概念？与传统 AD 有什么区别？",
    "基于以上讨论，有哪些针对 TDP-43 的药物研发策略？请引用最新的文献。",
]


async def run_plan_c() -> dict[str, Any]:
    """Plan C: 5-turn progressive exploration."""
    logger.info("=== Plan C: Multi-turn Exploration ===")
    collector = TraceCollector(plan_name="planC")
    inner = GeminiProvider(model=FIXED_MODEL)
    provider = TracingProvider(inner, collector)
    agent = build_traced_agent(provider, collector)

    messages: list[BaseMessage] = []
    hot_loaded: set[str] = set()
    session_memory = ""
    tracking = CompactTrackingState()
    state: dict[str, Any] = {}

    for turn_idx, user_msg in enumerate(PLAN_C_TURNS, 1):
        logger.info("  Turn %d/5: %s", turn_idx, user_msg[:60])
        collector.add("TURN_START", {"turn": turn_idx, "user_msg": user_msg})

        messages.append(HumanMessage(content=user_msg))
        current_state: AgentState = {
            "messages": messages,
            "hot_loaded": hot_loaded,
            "session_memory": session_memory,
            "extra_tools": {},
            "compact_tracking": tracking,
            "model": FIXED_MODEL,
            "session_id": None,
        }

        try:
            state = await asyncio.wait_for(agent.ainvoke(
                current_state, config={"recursion_limit": 40},
            ), timeout=180.0)
        except asyncio.TimeoutError:
            collector.add("ERROR", {"type": "TimeoutError", "turn": turn_idx})
            break
        except Exception as exc:
            collector.add("ERROR", {"type": type(exc).__name__, "msg": str(exc), "turn": turn_idx})
            break

        messages = list(state.get("messages", messages))
        hot_loaded = state.get("hot_loaded", hot_loaded)
        tracking = state.get("compact_tracking", tracking)

        collector.add("TURN_END", {
            "turn": turn_idx,
            "message_count": len(messages),
            "final_text_preview": (state.get("final_text") or "")[:500],
        })

    elapsed = collector.elapsed()
    collector.add("PLAN_COMPLETE", {"elapsed_sec": elapsed, "turns_completed": turn_idx})
    json_p, md_p = collector.save("plan_c")
    logger.info("Plan C done in %.1fs — %s", elapsed, json_p)
    return {
        "plan": "C", "state": state, "collector": collector,
        "elapsed": elapsed, "json_path": str(json_p), "md_path": str(md_p),
    }


# ===================================================================
# 8. Automated evaluation
# ===================================================================

@dataclass
class EvalResult:
    plan: str
    elapsed_sec: float
    has_tdp43_mention: bool
    has_late_mention: bool
    has_tau_interaction: bool
    citation_count: int
    tool_call_count: int
    hot_loaded_tools: list[str]
    llm_call_count: int
    answer_length_chars: int
    error_count: int


def evaluate_result(result: dict[str, Any]) -> EvalResult:
    state = result.get("state", {})
    collector: TraceCollector = result["collector"]
    final_text = state.get("final_text", "") or ""

    # Gather all AI message text as fallback
    all_text = final_text
    for m in state.get("messages", []):
        if isinstance(m, AIMessage):
            all_text += " " + m.content

    text_lower = all_text.lower()

    # Count events by type
    tool_calls = [e for e in collector.events if e.event_type == "TOOL_CALL"]
    llm_calls = [e for e in collector.events if e.event_type == "LLM_REQUEST"]
    errors = [e for e in collector.events if e.event_type == "ERROR"]
    hot_loads = []
    for e in collector.events:
        if e.event_type == "HOT_LOAD":
            hot_loads.extend(e.data.get("tools", []))

    # Citation count
    pmid_pattern = re.compile(r"PMID[:\s]*\d+", re.IGNORECASE)
    doi_pattern = re.compile(r"DOI[:\s]*10\.\d+", re.IGNORECASE)
    citation_count = len(pmid_pattern.findall(all_text)) + len(doi_pattern.findall(all_text))

    return EvalResult(
        plan=result["plan"],
        elapsed_sec=result["elapsed"],
        has_tdp43_mention="tdp-43" in text_lower or "tardbp" in text_lower or "tdp43" in text_lower,
        has_late_mention="late" in text_lower or "limbic-predominant" in text_lower,
        has_tau_interaction="tau" in text_lower,
        citation_count=citation_count,
        tool_call_count=len(tool_calls),
        hot_loaded_tools=sorted(set(hot_loads)),
        llm_call_count=len(llm_calls),
        answer_length_chars=len(final_text),
        error_count=len(errors),
    )


# ===================================================================
# 9. Report generation
# ===================================================================

def generate_report(evals: list[EvalResult]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / "tdp43_ad_report.md"

    plan_labels = {"A": "A-多工具", "B": "B-子代理", "C": "C-多轮"}

    lines = [
        "# TDP-43 × AD Agent 测试对比报告",
        f"\n生成时间: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"模型: `{FIXED_MODEL}`\n",
        "## 总览\n",
        "| 方案 | 用时 | LLM调用 | 工具调用 | 引用数 | TDP-43 ✓ | LATE ✓ | Tau ✓ | 回答长度 | 错误 |",
        "|------|------|---------|---------|--------|----------|--------|-------|---------|------|",
    ]

    for ev in evals:
        label = plan_labels.get(ev.plan, ev.plan)
        lines.append(
            f"| {label} | {ev.elapsed_sec:.0f}s | {ev.llm_call_count} | "
            f"{ev.tool_call_count} | {ev.citation_count} | "
            f"{'✅' if ev.has_tdp43_mention else '❌'} | "
            f"{'✅' if ev.has_late_mention else '❌'} | "
            f"{'✅' if ev.has_tau_interaction else '❌'} | "
            f"{ev.answer_length_chars} | {ev.error_count} |"
        )

    lines.append("\n## 详细评估\n")
    for ev in evals:
        label = plan_labels.get(ev.plan, ev.plan)
        lines.extend([
            f"### {label}\n",
            f"- **执行时间**: {ev.elapsed_sec:.1f}s",
            f"- **LLM 调用次数**: {ev.llm_call_count}",
            f"- **工具调用次数**: {ev.tool_call_count}",
            f"- **Hot-loaded 工具**: {', '.join(ev.hot_loaded_tools) or '无'}",
            f"- **引用数 (PMID/DOI)**: {ev.citation_count}",
            f"- **提及 TDP-43**: {'✅' if ev.has_tdp43_mention else '❌'}",
            f"- **提及 LATE**: {'✅' if ev.has_late_mention else '❌'}",
            f"- **提及 Tau 交互**: {'✅' if ev.has_tau_interaction else '❌'}",
            f"- **回答长度**: {ev.answer_length_chars} chars",
            f"- **错误数**: {ev.error_count}",
            "",
        ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report saved to %s", report_path)
    return report_path


# ===================================================================
# 10. CLI entry point
# ===================================================================

PLAN_RUNNERS = {
    "a": run_plan_a,
    "b": run_plan_b,
    "c": run_plan_c,
}


async def main(plans: list[str]) -> int:
    results: list[dict[str, Any]] = []
    for plan in plans:
        runner = PLAN_RUNNERS.get(plan)
        if not runner:
            logger.error("Unknown plan: %s (valid: a, b, c)", plan)
            return 1
        try:
            result = await runner()
            results.append(result)
        except Exception:
            logger.exception("Plan %s crashed", plan.upper())

    if results:
        evals = [evaluate_result(r) for r in results]
        report_path = generate_report(evals)
        print(f"\n{'='*60}")
        print(f"  Completed {len(results)} plan(s). Report: {report_path}")
        print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TDP-43 × AD Agent Test")
    parser.add_argument(
        "--plan", default="a",
        help="Comma-separated plans to run: a,b,c (default: a)",
    )
    args = parser.parse_args()
    plans = [p.strip().lower() for p in args.plan.split(",") if p.strip()]
    sys.exit(asyncio.run(main(plans)))
