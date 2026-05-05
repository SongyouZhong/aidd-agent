"""Chat API request schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    content: str = Field(min_length=1, max_length=50000)
    plan_mode: bool = False
    file_ids: list[uuid.UUID] = Field(default_factory=list)
