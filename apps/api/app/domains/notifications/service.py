"""Reading and acknowledging the caller's own notifications.

Rows are tenant-scoped by RLS and user-scoped here: nobody, staff included,
reads or marks another person's notifications.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.domains.notifications.models import Notification
from app.domains.notifications.schemas import NotificationOut, NotificationPage
from app.domains.rbac.principal import Principal


async def unread_count(db: AsyncSession, principal: Principal) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
    )
    return int(total or 0)


async def list_for(
    db: AsyncSession, principal: Principal, page: PageParams, *, unread_only: bool
) -> NotificationPage:
    stmt = select(Notification).where(Notification.user_id == principal.user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows, total = await paginate(db, stmt, page)
    return NotificationPage(
        items=[NotificationOut.model_validate(row[0]) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
        unread=await unread_count(db, principal),
    )


async def mark_read(
    db: AsyncSession, principal: Principal, notification_id: uuid.UUID
) -> NotificationOut:
    row = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == principal.user_id
        )
    )
    if row is None:
        raise NotFound()
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await db.flush()
    return NotificationOut.model_validate(row)


async def mark_all_read(db: AsyncSession, principal: Principal) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return int(getattr(result, "rowcount", 0) or 0)
