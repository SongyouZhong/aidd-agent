"""Auth service — registration, login, user lookup."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, CredentialsError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User


async def register_user(
    db: AsyncSession, *, username: str, password: str
) -> tuple[User, str]:
    existing = await db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise ConflictError("Username already taken")

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id))


async def authenticate(
    db: AsyncSession, *, username: str, password: str
) -> tuple[User, str]:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise CredentialsError("Invalid username or password")
    return user, create_access_token(str(user.id))


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)
