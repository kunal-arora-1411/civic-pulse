"""The caller's in-app notifications."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.notifications import service
from app.domains.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    NotificationPreferences,
    PreferencesUpdate,
    PushSubscriptionIn,
    PushSubscriptionOut,
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


@router.get(
    "/preferences",
    operation_id="notifications_get_preferences",
    response_model=NotificationPreferences,
    responses=error_responses(401, 403),
)
async def get_preferences(principal: CurrentPrincipal, db: DbSession) -> NotificationPreferences:
    """Which kinds go out by email, SMS and Web Push. The in-app inbox
    always gets every notification."""
    return await service.get_preferences(db, principal)


@router.put(
    "/preferences",
    operation_id="notifications_update_preferences",
    response_model=NotificationPreferences,
    responses=error_responses(401, 403, 422),
)
async def update_preferences(
    principal: CurrentPrincipal, db: DbSession, body: PreferencesUpdate
) -> NotificationPreferences:
    """Change the listed choices only. A kind the caller cannot receive, or a
    channel the kind is never sent on, is a 422."""
    return await service.update_preferences(db, principal, body)


@router.post(
    "/push-subscriptions",
    operation_id="notifications_subscribe_push",
    status_code=status.HTTP_201_CREATED,
    response_model=PushSubscriptionOut,
    responses=error_responses(401, 403, 422, 503),
)
async def subscribe_push(
    principal: CurrentPrincipal, db: DbSession, body: PushSubscriptionIn
) -> PushSubscriptionOut:
    """Register this browser for Web Push. Re-subscribing the same endpoint
    updates it (and moves it to the caller). 503 when push is not configured."""
    return await service.subscribe_push(db, principal, body)


@router.delete(
    "/push-subscriptions",
    operation_id="notifications_unsubscribe_push",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403),
)
async def unsubscribe_push(
    principal: CurrentPrincipal,
    db: DbSession,
    endpoint: Annotated[str, Query(min_length=1, max_length=1000)],
) -> None:
    """Stop pushing to this browser. Idempotent."""
    await service.unsubscribe_push(db, principal, endpoint)
