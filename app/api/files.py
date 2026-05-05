"""File upload API — upload / list / download / delete files per session.

File content goes to SeaweedFS; metadata to PostgreSQL ``session_files``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.engine import get_db
from app.models.user import User
from app.schemas.file import FileResponse
from app.services import file_service, session_service

router = APIRouter(prefix="/sessions", tags=["files"])


@router.post(
    "/{session_id}/files",
    response_model=FileResponse,
    status_code=201,
)
async def upload_file(
    session_id: uuid.UUID,
    file: UploadFile = File(...),
    description: str | None = Form(default=None, max_length=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file to a session."""
    session = await session_service.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no name")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    mime = file.content_type or "application/octet-stream"

    record = await file_service.upload_file(
        db,
        session_id=session_id,
        user_id=user.id,
        filename=file.filename,
        content=content,
        mime_type=mime,
        description=description,
    )
    return record


@router.get(
    "/{session_id}/files",
    response_model=list[FileResponse],
)
async def list_files(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all files for a session."""
    session = await session_service.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return await file_service.list_files(db, session_id)


@router.get(
    "/{session_id}/files/{file_id}",
    response_model=FileResponse,
)
async def get_file(
    session_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get metadata for a single file."""
    return await file_service.get_file(db, file_id, user.id)


@router.get("/{session_id}/files/{file_id}/download")
async def download_file(
    session_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redirect to a pre-signed S3 download URL (valid 10 min)."""
    url = await file_service.get_download_url(db, file_id, user.id)
    return RedirectResponse(url=url, status_code=302)


@router.delete(
    "/{session_id}/files/{file_id}",
    status_code=204,
)
async def delete_file(
    session_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file (S3 object + DB record)."""
    await file_service.delete_file(db, file_id, user.id)
