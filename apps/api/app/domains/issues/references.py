"""Human-friendly references: `R-26-000123` for reports, `CP-26-000123` for
issues. Sequential per tenant, kind and year, unique, never reused.

The counter row is bumped with an upsert inside the caller's transaction.
The row lock that takes is what makes concurrent submissions safe: a second
transaction waits for the first to commit or roll back and then sees the
new value. A rolled-back submission rolls its increment back too, so in
practice there are no gaps; nothing relies on that, though, and the unique
constraints on (tenant_id, reference) are the final guarantee. Callers
should allocate as late as possible, after validation, because the lock is
held until commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.issues.models import ReferenceKind

PREFIXES = {ReferenceKind.REPORT: "R", ReferenceKind.ISSUE: "CP"}

_NEXT = text(
    """
    INSERT INTO reference_counters (tenant_id, kind, year, last_value)
    VALUES (:tenant_id, :kind, :year, 1)
    ON CONFLICT (tenant_id, kind, year)
    DO UPDATE SET last_value = reference_counters.last_value + 1
    RETURNING last_value
    """
)


def format_reference(kind: ReferenceKind, year: int, value: int) -> str:
    return f"{PREFIXES[kind]}-{year % 100:02d}-{value:06d}"


async def allocate(
    db: AsyncSession, tenant_id: uuid.UUID, kind: ReferenceKind, *, now: datetime | None = None
) -> str:
    local = (now or datetime.now(ZoneInfo(get_settings().local_timezone))).astimezone(
        ZoneInfo(get_settings().local_timezone)
    )
    year = local.year % 100
    value = await db.scalar(_NEXT, {"tenant_id": tenant_id, "kind": kind.value, "year": year})
    assert value is not None
    return format_reference(kind, year, int(value))
