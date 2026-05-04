"""``ToolSearchTool`` — the always-on entry point for deferred tool discovery.

The model calls this when the default core tools are insufficient. The
returned text contains the JSON Schema (name + description + signature)
for each candidate so that the orchestrator can hot-mount them on the
next turn (design doc §7.3.1).
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.tools.registry import default_registry


@tool
def tool_search(query: str, top_k: int = 3) -> str:
    """Search for additional specialised tools (databases, calculators).

    Use this when the currently loaded tools cannot answer the user's
    request. The returned tools become callable on the *next* turn after
    the orchestrator mounts them. Call this BEFORE giving up on a query.

    Args:
        query: Description of the capability you need
               (e.g. "compound bioactivity database").
        top_k: Number of candidate tools to return (1-5).
    """
    top_k = max(1, min(int(top_k), 5))
    hits = default_registry.search(query, top_k=top_k)
    if not hits:
        return json.dumps(
            {"matches": [], "note": "No deferred tools matched this query."},
            ensure_ascii=False,
        )

    payload = {
        "matches": [
            {
                "name": e.name,
                "description": e.description,
                "args_schema": (
                    e.impl.args_schema.model_json_schema()
                    if getattr(e.impl, "args_schema", None) is not None
                    else {}
                ),
                "mount_instruction": (
                    f"Reply with a tool call to mount: {e.name}. "
                    "It will be available on the next turn."
                ),
            }
            for e in hits
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
