"""Saved analytics views (FR-077): a staff member's named dashboard filters.

Views are personal. Every query is narrowed to the caller's own rows, so
another person's view is indistinguishable from one that doesn't exist.
They hold preferences, not data, so they aren't audited.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import DbSession
from app.core.errors import Conflict, NotFound, ValidationFailed, error_responses
from app.domains.analytics.models import AnalyticsView
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.workflow.statuses import IssueStatus

MAX_VIEWS_PER_USER = 20

ViewName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class SavedFilters(BaseModel):
    """The dashboard's filters, in the same vocabulary as its URL."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    range: Literal["7d", "30d", "90d", "mtd", "custom"] = "30d"
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    category_id: uuid.UUID | None = None
    ward_id: uuid.UUID | None = None
    status: list[IssueStatus] = Field(default_factory=list, max_length=len(IssueStatus))
    interval: Literal["day", "week"] = "day"

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.range != "custom" and (self.from_ or self.to):
            raise ValueError("`from` and `to` apply only to a custom range.")
        if self.from_ and self.to and self.from_ > self.to:
            raise ValueError("`from` must not be after `to`.")
        return self


class AnalyticsViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ViewName
    filters: SavedFilters
    is_default: bool = False


class AnalyticsViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ViewName | None = None
    filters: SavedFilters | None = None
    is_default: bool | None = None


class AnalyticsViewOut(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    id: uuid.UUID
    name: str
    filters: SavedFilters
    is_default: bool
    created_at: datetime
    updated_at: datetime


def _to_out(view: AnalyticsView) -> AnalyticsViewOut:
    return AnalyticsViewOut(
        id=view.id,
        name=view.name,
        filters=SavedFilters.model_validate(view.filters),
        is_default=view.is_default,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _filters_json(filters: SavedFilters) -> dict[str, object]:
    return filters.model_dump(mode="json", by_alias=True)


async def _own(db: AsyncSession, principal: Principal, view_id: uuid.UUID) -> AnalyticsView:
    view = await db.scalar(
        select(AnalyticsView).where(
            AnalyticsView.id == view_id, AnalyticsView.user_id == principal.user_id
        )
    )
    if view is None:
        raise NotFound("Saved view not found.")
    return view


async def _clear_default(db: AsyncSession, principal: Principal) -> None:
    await db.execute(
        update(AnalyticsView)
        .where(AnalyticsView.user_id == principal.user_id, AnalyticsView.is_default.is_(True))
        .values(is_default=False)
        .execution_options(synchronize_session="fetch")
    )


async def _flush(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        if "uq_analytics_views_user_name" in str(exc.orig):
            raise Conflict(
                "You already have a saved view with this name.", code="name_taken"
            ) from exc
        raise


async def list_views(db: AsyncSession, principal: Principal) -> list[AnalyticsViewOut]:
    rows = await db.scalars(
        select(AnalyticsView)
        .where(AnalyticsView.user_id == principal.user_id)
        .order_by(AnalyticsView.is_default.desc(), func.lower(AnalyticsView.name))
    )
    return [_to_out(v) for v in rows]


async def create_view(
    db: AsyncSession, principal: Principal, body: AnalyticsViewCreate
) -> AnalyticsViewOut:
    assert principal.tenant_id is not None
    count = await db.scalar(
        select(func.count())
        .select_from(AnalyticsView)
        .where(AnalyticsView.user_id == principal.user_id)
    )
    if (count or 0) >= MAX_VIEWS_PER_USER:
        raise ValidationFailed(
            f"You can keep at most {MAX_VIEWS_PER_USER} saved views.",
            code="too_many_views",
        )
    if body.is_default:
        await _clear_default(db, principal)
    view = AnalyticsView(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        name=body.name,
        filters=_filters_json(body.filters),
        is_default=body.is_default,
    )
    db.add(view)
    await _flush(db)
    await db.refresh(view)
    return _to_out(view)


async def update_view(
    db: AsyncSession, principal: Principal, view_id: uuid.UUID, body: AnalyticsViewUpdate
) -> AnalyticsViewOut:
    view = await _own(db, principal, view_id)
    if body.is_default is not None and body.is_default != view.is_default:
        if body.is_default:
            await _clear_default(db, principal)
        view.is_default = body.is_default
    if body.name is not None:
        view.name = body.name
    if body.filters is not None:
        view.filters = _filters_json(body.filters)
    await _flush(db)
    await db.refresh(view)
    return _to_out(view)


async def delete_view(db: AsyncSession, principal: Principal, view_id: uuid.UUID) -> None:
    view = await _own(db, principal, view_id)
    await db.delete(view)
    await db.flush()


Reader = Annotated[Principal, require(Permission.ANALYTICS_READ)]

router = APIRouter(prefix="/analytics/views", tags=["analytics"])


@router.get("", operation_id="analytics_views_list", responses=error_responses(401, 403))
async def list_saved_views(principal: Reader, db: DbSession) -> list[AnalyticsViewOut]:
    """The caller's saved views, the default first, then by name."""
    return await list_views(db, principal)


@router.post(
    "",
    operation_id="analytics_views_create",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_saved_view(
    principal: Reader, db: DbSession, body: AnalyticsViewCreate
) -> AnalyticsViewOut:
    """Save filters under a name. Making it the default un-defaults any
    other. 409 `name_taken` when the name (ignoring case) is in use;
    422 `too_many_views` past the limit of 20."""
    return await create_view(db, principal, body)


@router.patch(
    "/{view_id}",
    operation_id="analytics_views_update",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_saved_view(
    principal: Reader, db: DbSession, view_id: uuid.UUID, body: AnalyticsViewUpdate
) -> AnalyticsViewOut:
    return await update_view(db, principal, view_id, body)


@router.delete(
    "/{view_id}",
    operation_id="analytics_views_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
)
async def delete_saved_view(principal: Reader, db: DbSession, view_id: uuid.UUID) -> Response:
    await delete_view(db, principal, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
