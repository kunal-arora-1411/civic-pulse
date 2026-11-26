"""The caller's in-app notifications."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.notifications import service
from app.domains.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    ReadAllResult,
    UnreadCount,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    operation_id="notifications_list",
    response_model=NotificationPage,
    responses=error_responses(401, 422),
)
async def list_notifications(
    principal: CurrentPrincipal, db: DbSession, page: PageParamsDep, unread: bool = False
) -> NotificationPage:
    """Newest first. `unread=true` keeps only unread ones; `unread` in the
    body is always the full unread count."""
    return await service.list_for(db, principal, page, unread_only=unread)


@router.get(
    "/unread-count",
    operation_id="notifications_unread_count",
    response_model=UnreadCount,
    responses=error_responses(401),
)
async def unread_count(principal: CurrentPrincipal, db: DbSession) -> UnreadCount:
    """Cheap enough to poll for the header badge."""
    return UnreadCount(unread=await service.unread_count(db, principal))


@router.post(
    "/read-all",
    operation_id="notifications_read_all",
    response_model=ReadAllResult,
    responses=error_responses(401),
)
async def read_all(principal: CurrentPrincipal, db: DbSession) -> ReadAllResult:
    """Mark every unread notification read; returns how many changed."""
    return ReadAllResult(updated=await service.mark_all_read(db, principal))


@router.post(
    "/{notification_id}/read",
    operation_id="notifications_read",
    response_model=NotificationOut,
    responses=error_responses(401, 404, 422),
)
async def read_one(
    principal: CurrentPrincipal, db: DbSession, notification_id: uuid.UUID
) -> NotificationOut:
    """Idempotent. Someone else's notification is a 404."""
    return await service.mark_read(db, principal, notification_id)
