"""SLA targets and the breach scanner (FR-056, FR-057, AC-09).

Deadlines are set by the `sla_schedule` trigger (migration 0010). The
scanner, run by Beat, marks issues that went past theirs and escalates in
two steps: first to the supervisors of the category's department (or
supervisors without a department), then, `escalate_after_hours` after the
breach, to the municipal admins.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session_factory
from app.core.errors import ValidationFailed
from app.core.logging import log_fields
from app.core.tenancy import set_tenant, system_session
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.issues.models import CivicIssue, EventType, IssueEvent, Visibility
from app.domains.notifications.models import Notification, NotificationKind
from app.domains.rbac.models import UserRole
from app.domains.rbac.principal import Principal
from app.domains.rbac.roles import Role
from app.domains.sla.models import SlaTarget
from app.domains.sla.rules import FINISHED, overdue_clause
from app.domains.sla.schemas import SlaTargetIn, SlaTargetOut, SlaTargets, SlaTargetsUpdate
from app.domains.users.models import User

logger = logging.getLogger(__name__)


def _out(row: SlaTarget) -> SlaTargetOut:
    return SlaTargetOut.model_validate(row, from_attributes=True)


async def list_targets(db: AsyncSession) -> SlaTargets:
    rows = await db.scalars(
        select(SlaTarget).order_by(
            SlaTarget.category_id, SlaTarget.priority_band.nulls_first(), SlaTarget.id
        )
    )
    return SlaTargets(items=[_out(r) for r in rows])


def _dump(items: list[Any]) -> list[dict[str, Any]]:
    return [
        SlaTargetIn.model_validate(i, from_attributes=True).model_dump(mode="json") for i in items
    ]


async def replace_targets(db: AsyncSession, actor: Principal, body: SlaTargetsUpdate) -> SlaTargets:
    """Replace the tenant's whole set of targets, audited with both versions,
    and reschedule every open issue against the new set."""
    assert actor.tenant_id is not None
    wanted = {i.category_id for i in body.items}
    known = set(await db.scalars(select(Category.id).where(Category.id.in_(wanted))))
    if unknown := wanted - known:
        raise ValidationFailed(
            "The request is invalid.",
            details={
                "errors": [
                    {
                        "loc": ["body", "items"],
                        "msg": f"Unknown category {sorted(map(str, unknown))[0]}.",
                        "type": "value_error",
                    }
                ]
            },
        )
    # Lock the current set so two admins saving at once are audited in order.
    before = list(await db.scalars(select(SlaTarget).with_for_update()))
    before_json = _dump(before)
    await db.execute(delete(SlaTarget))
    db.add_all(
        SlaTarget(
            tenant_id=actor.tenant_id,
            category_id=i.category_id,
            priority_band=i.priority_band.value if i.priority_band else None,
            resolve_hours=i.resolve_hours,
            escalate_after_hours=i.escalate_after_hours,
            updated_by=actor.user_id,
        )
        for i in body.items
    )
    await db.flush()
    # Touching `sla_started_at` fires the trigger, which looks the target up
    # again. `updated_at` is kept: nothing about the issue itself changed.
    await db.execute(
        update(CivicIssue)
        .where(CivicIssue.status.notin_([s.value for s in FINISHED]))
        .values(sla_started_at=CivicIssue.sla_started_at, updated_at=CivicIssue.updated_at)
        .execution_options(synchronize_session=False)
    )
    await audit.record(
        db,
        action="config.sla_targets_updated",
        entity_type="sla_targets",
        actor=actor,
        before={"items": before_json},
        after={"items": _dump(body.items)},
    )
    return await list_targets(db)


async def scan(now: datetime | None = None) -> int:
    """Mark and escalate breached issues in every tenant; returns how many
    escalations were made. Idempotent: an issue moves up each level once."""
    now = now or datetime.now(UTC)
    async with system_session(reason="sla scan: find tenants") as db:
        tenant_ids = list(
            await db.scalars(
                select(CivicIssue.tenant_id)
                .where(overdue_clause(now), CivicIssue.escalation_level < 2)
                .distinct()
            )
        )
    escalated = 0
    for tenant_id in tenant_ids:
        try:
            escalated += await _scan_tenant(tenant_id, now)
        except Exception as exc:  # one tenant's failure mustn't stop the others
            logger.exception(
                "sla scan failed", extra=log_fields(tenant_id=str(tenant_id), error=repr(exc))
            )
    return escalated


async def _recipients(
    db: AsyncSession, level: int, department_id: uuid.UUID | None
) -> list[uuid.UUID]:
    stmt = (
        select(UserRole.user_id)
        .join(User, User.id == UserRole.user_id)
        .where(User.is_active.is_(True))
        .distinct()
    )
    if level == 1:
        stmt = stmt.where(
            UserRole.role == Role.SUPERVISOR,
            or_(UserRole.department_id.is_(None), UserRole.department_id == department_id),
        )
    else:
        stmt = stmt.where(UserRole.role == Role.MUNICIPAL_ADMIN)
    return list(await db.scalars(stmt))


async def _scan_tenant(tenant_id: uuid.UUID, now: datetime) -> int:
    # Tenant-scoped, not the bypass: role and target reads must only see
    # this tenant's rows.
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        rows = (
            await db.execute(
                select(CivicIssue, Category.default_department_id)
                .join(Category, Category.id == CivicIssue.category_id)
                .where(
                    CivicIssue.tenant_id == tenant_id,
                    CivicIssue.merged_into_id.is_(None),
                    CivicIssue.escalation_level < 2,
                    overdue_clause(now),
                )
                .with_for_update(of=CivicIssue, skip_locked=True)
            )
        ).all()
        delays = {
            (t.category_id, t.priority_band): t.escalate_after_hours
            for t in await db.scalars(select(SlaTarget))
        }
        done = 0
        for issue, department_id in rows:
            if issue.escalation_level == 0:
                level = 1
            else:
                band = issue.priority_override_band or issue.priority_band
                hours = delays.get((issue.category_id, band)) or delays.get(
                    (issue.category_id, None)
                )
                breached = issue.breached_at or issue.due_at
                if hours is None or breached is None or now < breached + timedelta(hours=hours):
                    continue
                level = 2
            await _escalate(db, issue, level, department_id, now)
            done += 1
        await db.commit()
        return done


async def _escalate(
    db: AsyncSession,
    issue: CivicIssue,
    level: int,
    department_id: uuid.UUID | None,
    now: datetime,
) -> None:
    if issue.breached_at is None:
        issue.breached_at = now
    issue.escalation_level = level
    due = issue.due_at.isoformat() if issue.due_at else None
    db.add(
        IssueEvent(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            type=EventType.SLA_BREACHED if level == 1 else EventType.SLA_ESCALATED,
            visibility=Visibility.INTERNAL,
            actor_id=None,
            data={"level": level, "due_at": due},
        )
    )
    db.add_all(
        Notification(
            tenant_id=issue.tenant_id,
            user_id=user_id,
            kind=NotificationKind.SLA_BREACH,
            title_key="sla_breach.title",
            body_key=f"sla_breach.body_level_{level}",
            params={"issue": issue.reference, "level": level},
            link=f"/admin/issues/{issue.id}",
            issue_id=issue.id,
        )
        for user_id in await _recipients(db, level, department_id)
    )
    await audit.record(
        db,
        action="issue.sla_escalated",
        entity_type="issue",
        entity_id=issue.id,
        tenant_id=issue.tenant_id,
        after={"level": level, "due_at": due},
    )
    await db.flush()
