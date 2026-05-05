"""Message API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata: dict[str, Any] | None = None
    token_count: int | None = None
    created_at: str | None = None  # ISO 8601 ts from JSONL
