"""LangGraph Studio entrypoint.

Exposes the compiled graph at module level so ``langgraph dev`` /
LangGraph Studio can discover it via ``langgraph.json``.

The Gemini provider is instantiated here using settings from ``.env``.
"""

from __future__ import annotations

from app.agent.agent import build_agent
from app.agent.llm_provider import get_default_provider

provider = get_default_provider()
graph = build_agent(provider)
