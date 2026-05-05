"""Traces API — read agent execution trace steps for a message.

Traces are stored as JSONL files in SeaweedFS:
    s3://aidd-data/sessions/{session_id}/traces/{message_id}.jsonl
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.engine import get_db
from app.models.user import User
from app.schemas.trace import TraceStepResponse
from app.storage.manager import load_messages
from app.storage.s3 import s3_storage, trace_key

router = APIRouter(prefix="/messages", tags=["traces"])


@router.get(
    "/{message_id}/traces",
    response_model=list[TraceStepResponse],
)
async def get_message_traces(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return trace steps for a given assistant message.

    Searches all user sessions for the message_id, then reads the
    trace JSONL from S3.
    """
    # We need session_id to locate the trace file.
    # The message_id is embedded in the stored messages.
    # Strategy: check all sessions for this user.
    from sqlalchemy import select
    from app.models.session import Session

    sessions = await db.execute(
        select(Session).where(Session.user_id == user.id)
    )
    for session in sessions.scalars():
        # Try to load trace directly from S3
        key = trace_key(str(session.id), message_id)
        raw = await s3_storage.get_object(key)
        if raw:
            steps = []
            for line in raw.decode("utf-8").splitlines():
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
            return steps

    raise HTTPException(status_code=404, detail="Traces not found for this message")
