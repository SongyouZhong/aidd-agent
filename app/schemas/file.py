"""File upload API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/json",
    "image/png",
    "image/jpeg",
    "chemical/x-mol",
    "chemical/x-sdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB
MAX_FILES_PER_SESSION: int = 20


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    filename: str
    original_filename: str
    mime_type: str
    size: int
    description: str | None = None
    s3_key: str
    created_at: datetime
