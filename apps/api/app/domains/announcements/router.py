"""Administering service announcements. The public read is in app/domains/public."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.announcements import service
from app.domains.announcements.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementPage,
    AnnouncementState,
    AnnouncementUpdate,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

Reader = Annotated[Principal, require(Permission.CONFIG_READ)]
Manager = Annotated[Principal, require(Permission.CONFIG_MANAGE)]

router = APIRouter(prefix="/admin/announcements", tags=["admin", "announcements"])


@router.get(
    "",
    operation_id="admin_announcements_list",
    response_model=AnnouncementPage,
    responses=error_responses(401, 403, 422),
)
async def list_announcements(
    _: Reader,
    db: DbSession,
    page: PageParamsDep,
    state: AnnouncementState | None = None,
    ward_id: uuid.UUID | None = None,
) -> AnnouncementPage:
    """All announcements, latest start first, optionally by state or ward."""
    items, total = await service.list_admin(db, page, state=state, ward_id=ward_id)
    return AnnouncementPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    operation_id="admin_announcements_create",
    response_model=AnnouncementOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 422),
)
async def create_announcement(
    principal: Manager, db: DbSession, body: AnnouncementCreate
) -> AnnouncementOut:
    """Publish a notice for a ward (or the city when `ward_id` is omitted).
    It shows publicly from `starts_at` until `ends_at`, which must be in
    the future. Audited as `announcement.create`."""
    return await service.create(db, principal, body)


@router.get(
    "/{announcement_id}",
    operation_id="admin_announcements_get",
    response_model=AnnouncementOut,
    responses=error_responses(401, 403, 404),
)
async def get_announcement(_: Reader, db: DbSession, announcement_id: uuid.UUID) -> AnnouncementOut:
    return await service.get(db, announcement_id)


@router.patch(
    "/{announcement_id}",
    operation_id="admin_announcements_update",
    response_model=AnnouncementOut,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_announcement(
    principal: Manager, db: DbSession, announcement_id: uuid.UUID, body: AnnouncementUpdate
) -> AnnouncementOut:
    """Edit a notice that hasn't been withdrawn (409 `withdrawn` otherwise).
    Audited as `announcement.update` with before and after."""
    return await service.update(db, principal, announcement_id, body)


@router.post(
    "/{announcement_id}/withdraw",
    operation_id="admin_announcements_withdraw",
    response_model=AnnouncementOut,
    responses=error_responses(401, 403, 404),
)
async def withdraw_announcement(
    principal: Manager, db: DbSession, announcement_id: uuid.UUID
) -> AnnouncementOut:
    """Take a notice down immediately; the row and its history are kept.
    Repeating it changes nothing. Audited as `announcement.withdraw`."""
    return await service.withdraw(db, principal, announcement_id)
