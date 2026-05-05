"""Session CRUD service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.session import Session
from app.storage.s3 import session_prefix


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.updated_at.desc())
    )
    return list(result.scalars().all())


async def create_session(
    db: AsyncSession, user_id: uuid.UUID, title: str | None = None
) -> Session:
    session = Session(user_id=user_id, title=title or "新对话")
    db.add(session)
    await db.flush()
    session.s3_prefix = session_prefix(str(session.id))
    await db.commit()
    await db.refresh(session)
    return session


async def _get_owned(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> Session:
    session = await db.get(Session, session_id)
    if session is None:
        raise NotFoundError("Session not found")
    if session.user_id != user_id:
        raise ForbiddenError("You do not own this session")
    return session


async def rename_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> Session:
    session = await _get_owned(db, session_id, user_id)
    session.title = title
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    session = await _get_owned(db, session_id, user_id)
    await db.delete(session)
    await db.commit()


async def get_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> Session | None:
    """Return session if owned by user, else None."""
    session = await db.get(Session, session_id)
    if session is None or session.user_id != user_id:
        return None
    return session
