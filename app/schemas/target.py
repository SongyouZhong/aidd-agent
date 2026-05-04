"""API request/response schemas for the Target Discovery feature."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TargetDiscoverRequest(BaseModel):
    query: str = Field(min_length=1, max_length=128, description="Gene symbol / target name")
    session_id: uuid.UUID | None = None


class TargetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gene_symbol: str | None = None
    organism: str
    uniprot_ids: list[str] = Field(default_factory=list)
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class TargetReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_id: uuid.UUID
    version: int
    content: dict[str, Any]
    notes: list[str] = Field(default_factory=list)
    created_at: datetime
