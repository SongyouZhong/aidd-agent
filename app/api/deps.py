"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import CredentialsError
from app.core.security import decode_access_token
from app.db.engine import get_db
from app.models.user import User
from app.services import auth_service

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login"
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(token)
    sub = payload.get("sub")
    if not sub:
        raise CredentialsError()
    try:
        user_id = uuid.UUID(sub)
    except (TypeError, ValueError) as exc:
        raise CredentialsError() from exc

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise CredentialsError()
    return user
