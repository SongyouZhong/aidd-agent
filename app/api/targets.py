"""Target Discovery REST API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.engine import get_db
from app.models.user import User
from app.schemas.target import (
    TargetDiscoverRequest,
    TargetReportResponse,
    TargetSummary,
)
from app.services import target_service

router = APIRouter(prefix="/targets", tags=["targets"])


def _get_provider() -> Any:
    """Lazy-import the LLM provider so module import stays cheap and
    test code can monkey-patch this dependency."""
    from app.agent.llm_provider import get_default_provider

    return get_default_provider()


@router.post(
    "/discover",
    response_model=TargetReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def discover(
    payload: TargetDiscoverRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: Any = Depends(_get_provider),
) -> TargetReportResponse:
    """Run the 6-node Target Discovery pipeline and persist the report."""
    snapshot = await target_service.discover_target(
        db,
        provider=provider,
        target_query=payload.query,
        user_id=user.id,
        session_id=payload.session_id,
    )
    return TargetReportResponse.model_validate(snapshot)


@router.get("", response_model=list[TargetSummary])
async def list_targets(
    limit: int = 50,
    offset: int = 0,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TargetSummary]:
    targets = await target_service.list_targets(db, limit=limit, offset=offset)
    return [TargetSummary.model_validate(t) for t in targets]


@router.get("/{target_id}", response_model=TargetSummary)
async def get_target(
    target_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TargetSummary:
    target = await target_service.get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return TargetSummary.model_validate(target)


@router.get("/{target_id}/report", response_model=TargetReportResponse)
async def get_report(
    target_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TargetReportResponse:
    snapshot = await target_service.get_latest_report(db, target_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No report yet for this target")
    return TargetReportResponse.model_validate(snapshot)
