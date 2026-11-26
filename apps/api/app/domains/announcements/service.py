"""Service announcements (FR-087): planned works, outages and advisories.

An announcement covers one ward or the whole city (`ward_id` null), and
optionally one category. It is public between `starts_at` and `ends_at`
unless withdrawn. Withdrawing keeps the row; every change is audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import PageParams, paginate
from app.core.security import utcnow
from app.domains.analytics.schemas import WardRef
from app.domains.announcements.models import Announcement
from app.domains.announcements.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementState,
    AnnouncementUpdate,
    PublicAnnouncement,
)
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.schemas import CategoryRef
from app.domains.org.models import Jurisdiction, JurisdictionKind
from app.domains.org.schemas import UserRef
from app.domains.rbac.principal import Principal
from app.domains.users.models import User

PUBLIC_LIMIT = 50
_FIELDS = ("kind", "title_i18n", "body_i18n", "ward_id", "category_id", "starts_at", "ends_at")


def state_of(row: Announcement, now: datetime) -> AnnouncementState:
    if row.withdrawn_at is not None:
        return "withdrawn"
    if row.starts_at > now:
        return "scheduled"
    if row.ends_at <= now:
        return "ended"
    return "active"


def _state_clause(state: AnnouncementState, now: datetime) -> ColumnElement[bool]:
    live = Announcement.withdrawn_at.is_(None)
    match state:
        case "withdrawn":
            return Announcement.withdrawn_at.is_not(None)
        case "scheduled":
            return and_(live, Announcement.starts_at > now)
        case "ended":
            return and_(live, Announcement.ends_at <= now)
        case _:
            return and_(live, Announcement.starts_at <= now, Announcement.ends_at > now)


def _snapshot(row: Announcement) -> dict[str, Any]:
    return {
        "kind": row.kind,
        "title_i18n": row.title_i18n,
        "body_i18n": row.body_i18n,
        "ward_id": str(row.ward_id) if row.ward_id else None,
        "category_id": str(row.category_id) if row.category_id else None,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
        "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
    }


_Ward = aliased(Jurisdiction)


def _select():  # the inferred Select[...] row type is the useful annotation
    return (
        select(Announcement, _Ward, Category, User)
        .outerjoin(_Ward, _Ward.id == Announcement.ward_id)
        .outerjoin(Category, Category.id == Announcement.category_id)
        .outerjoin(User, User.id == Announcement.created_by)
    )


def _ward_ref(ward: Jurisdiction | None) -> WardRef | None:
    return WardRef(id=ward.id, code=ward.code, name=ward.name) if ward else None


def _category_ref(category: Category | None) -> CategoryRef | None:
    if category is None:
        return None
    return CategoryRef(
        id=category.id, code=category.code, name_i18n=category.name_i18n, icon=category.icon
    )


def _to_out(
    row: Announcement,
    ward: Jurisdiction | None,
    category: Category | None,
    author: User | None,
    now: datetime,
) -> AnnouncementOut:
    return AnnouncementOut(
        id=row.id,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        title_i18n=row.title_i18n,
        body_i18n=row.body_i18n,
        ward=_ward_ref(ward),
        category=_category_ref(category),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        state=state_of(row, now),
        withdrawn_at=row.withdrawn_at,
        created_by=UserRef(id=author.id, display_name=author.display_name) if author else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _check_refs(
    db: AsyncSession, ward_id: uuid.UUID | None, category_id: uuid.UUID | None
) -> None:
    # RLS keeps both lookups inside the tenant, so another tenant's ward is
    # simply unknown here.
    if ward_id is not None:
        kind = await db.scalar(select(Jurisdiction.kind).where(Jurisdiction.id == ward_id))
        if kind is not JurisdictionKind.WARD:
            raise ValidationFailed("Unknown ward.", details={"ward_id": str(ward_id)})
    if category_id is not None:
        found = await db.scalar(select(Category.id).where(Category.id == category_id))
        if found is None:
            raise ValidationFailed("Unknown category.", details={"category_id": str(category_id)})


async def _load(db: AsyncSession, announcement_id: uuid.UUID) -> AnnouncementOut:
    row = (await db.execute(_select().where(Announcement.id == announcement_id))).one_or_none()
    if row is None:
        raise NotFound("Announcement not found.")
    return _to_out(*row, now=utcnow())


async def _get(db: AsyncSession, announcement_id: uuid.UUID) -> Announcement:
    row = await db.get(Announcement, announcement_id)
    if row is None:
        raise NotFound("Announcement not found.")
    return row


async def list_admin(
    db: AsyncSession,
    params: PageParams,
    *,
    state: AnnouncementState | None = None,
    ward_id: uuid.UUID | None = None,
) -> tuple[list[AnnouncementOut], int]:
    now = utcnow()
    stmt = _select()
    if state is not None:
        stmt = stmt.where(_state_clause(state, now))
    if ward_id is not None:
        stmt = stmt.where(Announcement.ward_id == ward_id)
    stmt = stmt.order_by(Announcement.starts_at.desc(), Announcement.id.desc())
    rows, total = await paginate(db, stmt, params)
    return [_to_out(*row, now=now) for row in rows], total


async def get(db: AsyncSession, announcement_id: uuid.UUID) -> AnnouncementOut:
    return await _load(db, announcement_id)


async def create(
    db: AsyncSession, principal: Principal, body: AnnouncementCreate
) -> AnnouncementOut:
    assert principal.tenant_id is not None
    if body.ends_at <= utcnow():
        raise ValidationFailed("`ends_at` must be in the future.")
    await _check_refs(db, body.ward_id, body.category_id)
    row = Announcement(
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
        kind=body.kind.value,
        title_i18n=body.title_i18n,
        body_i18n=body.body_i18n,
        ward_id=body.ward_id,
        category_id=body.category_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        action="announcement.create",
        entity_type="announcement",
        entity_id=row.id,
        after=_snapshot(row),
        actor=principal,
    )
    return await _load(db, row.id)


async def update(
    db: AsyncSession, principal: Principal, announcement_id: uuid.UUID, body: AnnouncementUpdate
) -> AnnouncementOut:
    row = await _get(db, announcement_id)
    if row.withdrawn_at is not None:
        raise Conflict("A withdrawn announcement can't be edited.", code="withdrawn")
    changes = {f: getattr(body, f) for f in _FIELDS if f in body.model_fields_set}
    for required in ("kind", "title_i18n", "body_i18n", "starts_at", "ends_at"):
        if required in changes and changes[required] is None:
            raise ValidationFailed(f"`{required}` can't be null.")
    if not changes:
        return await _load(db, row.id)
    starts_at = changes.get("starts_at", row.starts_at)
    ends_at = changes.get("ends_at", row.ends_at)
    if ends_at <= starts_at:
        raise ValidationFailed("`ends_at` must be after `starts_at`.")
    await _check_refs(
        db,
        changes.get("ward_id") if "ward_id" in changes else None,
        changes.get("category_id") if "category_id" in changes else None,
    )
    before = _snapshot(row)
    for field, value in changes.items():
        setattr(row, field, value.value if field == "kind" else value)
    await db.flush()
    await audit.record(
        db,
        action="announcement.update",
        entity_type="announcement",
        entity_id=row.id,
        before=before,
        after=_snapshot(row),
        actor=principal,
    )
    return await _load(db, row.id)


async def withdraw(
    db: AsyncSession, principal: Principal, announcement_id: uuid.UUID
) -> AnnouncementOut:
    """Take a notice down now. Withdrawing twice is a no-op."""
    row = await _get(db, announcement_id)
    if row.withdrawn_at is None:
        before = _snapshot(row)
        row.withdrawn_at = utcnow()
        await db.flush()
        await audit.record(
            db,
            action="announcement.withdraw",
            entity_type="announcement",
            entity_id=row.id,
            before=before,
            after=_snapshot(row),
            actor=principal,
        )
    return await _load(db, row.id)


async def list_public(
    db: AsyncSession,
    *,
    ward_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
) -> list[PublicAnnouncement]:
    """Notices showing now. A ward (or category) filter keeps the city-wide
    (or all-category) notices too, since they apply there as well."""
    now = utcnow()
    stmt = _select().where(_state_clause("active", now))
    if ward_id is not None:
        stmt = stmt.where(or_(Announcement.ward_id.is_(None), Announcement.ward_id == ward_id))
    if category_id is not None:
        stmt = stmt.where(
            or_(Announcement.category_id.is_(None), Announcement.category_id == category_id)
        )
    stmt = stmt.order_by(Announcement.starts_at.desc(), Announcement.id.desc()).limit(PUBLIC_LIMIT)
    rows = (await db.execute(stmt)).all()
    return [
        PublicAnnouncement(
            id=row.id,
            kind=row.kind,  # pyright: ignore[reportArgumentType]
            title_i18n=row.title_i18n,
            body_i18n=row.body_i18n,
            ward=_ward_ref(ward),
            category=_category_ref(category),
            starts_at=row.starts_at,
            ends_at=row.ends_at,
        )
        for row, ward, category, _author in rows
    ]
