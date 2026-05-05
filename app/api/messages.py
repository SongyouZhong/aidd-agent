"""Messages API — read conversation history.

Messages are stored in Redis (hot) + SeaweedFS (cold),
not in PostgreSQL.  We read via ``storage/manager``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.engine import get_db
from app.models.user import User
from app.schemas.message import MessageResponse
from app.services import session_service
from app.storage.manager import load_messages

router = APIRouter(prefix="/sessions", tags=["messages"])


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
)
async def get_session_messages(
    session_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return conversation history for the given session."""
    session = await session_service.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await load_messages(str(session_id), limit=limit)
    return messages
