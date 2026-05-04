"""Agent-Tool Duality — wraps a child LangGraph as a callable tool.

Design doc §7.3.2.

Key properties:
 * Full state isolation: subagent gets a fresh ``initial_state`` so the
   parent's chatter doesn't leak in (and the child's noisy intermediates
   don't pollute the parent).
 * Sidechain Transcript: the child's full message log is serialized to
   SeaweedFS at ``sessions/{session_id}/sidechain/{trace_id}.json`` for
   audit (design doc §3.3 / §9.8). When ``s3_storage`` is not started
   (e.g. unit tests), the call is silently skipped.
 * Tool schema: a Pydantic args model + LangChain ``StructuredTool``
   exposes the AgentTool to the parent LLM under the name
   ``deep_research_agent``.

The child's tool list is intentionally narrow (literature + database
queries) to keep the schema small and the budget bounded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class DeepResearchArgs(BaseModel):
    target: str = Field(
        ..., description="研究目标（如靶点名称、化合物 ID 或综述主题）。"
    )
    task_description: str = Field(
        ..., description="对子代理的任务说明，越具体越好。"
    )


def _serialize_message(m: BaseMessage) -> dict[str, Any]:
    return {
        "type": m.__class__.__name__,
        "content": m.content if isinstance(m.content, str) else str(m.content),
        "tool_calls": getattr(m, "tool_calls", None) or [],
        "name": getattr(m, "name", None),
    }


async def _archive_sidechain(
    session_id: str | None,
    trace_id: str,
    initial_state: dict[str, Any],
    final_state: dict[str, Any],
) -> str | None:
    """Best-effort archival to S3. Returns the object key or None."""
    if not session_id:
        return None
    try:
        # Lazy import to avoid pulling aiobotocore into pure-unit tests.
        from app.storage.s3 import s3_storage

        if s3_storage is None or s3_storage._client is None:  # noqa: SLF001
            return None
        key = f"sessions/{session_id}/sidechain/{trace_id}.json"
        payload = {
            "trace_id": trace_id,
            "initial_messages": [
                _serialize_message(m) for m in initial_state.get("messages", [])
            ],
            "final_messages": [
                _serialize_message(m) for m in final_state.get("messages", [])
            ],
            "hot_loaded": sorted(final_state.get("hot_loaded", []) or []),
        }
        await s3_storage.put_object(
            key, json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        return key
    except Exception:
        logger.exception("Sidechain archival failed for trace %s", trace_id)
        return None


async def _run_subagent(
    *,
    target: str,
    task_description: str,
    session_id: str | None,
    provider_factory,
) -> str:
    """Spin up an isolated agent and return its final answer text."""
    # Lazy import: build_agent imports default_registry which pulls in
    # heavy tool deps; keeping this lazy lets unit tests stub it cleanly.
    from app.agent.agent import build_agent

    provider = provider_factory()
    sub_graph = build_agent(provider)

    trace_id = uuid.uuid4().hex[:12]
    user_msg = HumanMessage(
        content=(
            f"研究目标：{target}\n"
            f"任务描述：{task_description}\n\n"
            "请独立完成检索与交叉比对，最终只返回提炼后的结论与来源。"
        )
    )
    initial_state: dict[str, Any] = {
        "messages": [user_msg],
        "hot_loaded": set(),
        "session_memory": "",
    }

    try:
        final_state = await asyncio.wait_for(
            sub_graph.ainvoke(
                initial_state,
                config={"recursion_limit": settings.SUBAGENT_MAX_TURNS * 4},
            ),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        return "[subagent] 子代理执行超时（>5min），未能返回结果。"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Subagent crashed")
        return f"[subagent] 子代理执行失败：{exc}"

    archive_key = await _archive_sidechain(
        session_id, trace_id, initial_state, final_state
    )

    final_text = final_state.get("final_text") or ""
    if not final_text:
        last_ai = next(
            (m for m in reversed(final_state.get("messages", [])) if isinstance(m, AIMessage)),
            None,
        )
        final_text = last_ai.content if last_ai else "(no answer produced)"

    suffix = (
        f"\n\n[sidechain_transcript: s3://{settings.S3_BUCKET}/{archive_key}]"
        if archive_key
        else ""
    )
    return f"{final_text}{suffix}"


def make_deep_research_tool(
    *,
    session_id: str | None = None,
    provider_factory=None,
) -> StructuredTool:
    """Build a ``StructuredTool`` exposing the subagent to a parent LLM.

    ``provider_factory`` is called once per subagent invocation to build a
    fresh LLM provider instance. Defaulting to ``get_default_provider``
    keeps offline behaviour consistent with the rest of the agent stack.
    """
    if provider_factory is None:
        from app.agent.llm_provider import get_default_provider

        provider_factory = get_default_provider

    async def _coroutine(target: str, task_description: str) -> str:
        return await _run_subagent(
            target=target,
            task_description=task_description,
            session_id=session_id,
            provider_factory=provider_factory,
        )

    return StructuredTool.from_function(
        coroutine=_coroutine,
        name="deep_research_agent",
        description=(
            "启动一个完全隔离的后台研究子代理，专门处理需要 10 轮以上检索 / "
            "跨多个数据库交叉比对的深度问题（如靶点全面综述、化合物多源活性汇总）。"
            "子代理会自行调用 PubMed / arXiv / UniProt / ChEMBL 等工具，"
            "返回提炼后的结论与来源；中间过程不会污染主对话上下文。"
        ),
        args_schema=DeepResearchArgs,
    )
