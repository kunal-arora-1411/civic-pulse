"""Per-tenant status transitions: defaults, listing and lookup."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.pagination import PageParams, paginate
from app.domains.rbac.roles import Role
from app.domains.workflow.models import StatusTransition
from app.domains.workflow.schemas import TransitionOut
from app.domains.workflow.statuses import IssueStatus as S


@dataclass(frozen=True, slots=True)
class DefaultTransition:
    from_status: S
    to_status: S
    roles: tuple[Role, ...] = ()
    requires_reason: bool = False
    system_only: bool = False


_STAFF = (Role.OPERATOR, Role.SUPERVISOR, Role.MUNICIPAL_ADMIN)
_SENIOR = (Role.SUPERVISOR, Role.MUNICIPAL_ADMIN)

# Phase 1 defaults (docs/api/phase-1-contract.md §7). Later phases add the
# rest of the lifecycle. Migration 0002 holds a frozen copy for backfill.
DEFAULT_TRANSITIONS: tuple[DefaultTransition, ...] = (
    DefaultTransition(S.REPORTED, S.UNDER_REVIEW, _STAFF),
    DefaultTransition(S.REPORTED, S.VERIFIED, _STAFF),
    DefaultTransition(S.UNDER_REVIEW, S.VERIFIED, _STAFF),
    DefaultTransition(S.REPORTED, S.REJECTED, _STAFF, requires_reason=True),
    DefaultTransition(S.UNDER_REVIEW, S.REJECTED, _STAFF, requires_reason=True),
    DefaultTransition(S.REJECTED, S.UNDER_REVIEW, _SENIOR, requires_reason=True),
    DefaultTransition(S.VERIFIED, S.ASSIGNED, system_only=True),
)

_LIFECYCLE_ORDER = {status.value: index for index, status in enumerate(S)}


async def install_default_transitions(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Add any missing default transitions for a tenant; returns how many.

    Existing rows are left alone, so a tenant's own changes survive a re-run.
    The caller needs that tenant's context or the RLS bypass.
    """
    stmt = (
        pg_insert(StatusTransition)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "from_status": t.from_status.value,
                    "to_status": t.to_status.value,
                    "allowed_roles": [r.value for r in t.roles],
                    "requires_reason": t.requires_reason,
                    "system_only": t.system_only,
                }
                for t in DEFAULT_TRANSITIONS
            ]
        )
        .on_conflict_do_nothing(constraint="uq_status_transitions_tenant_id_from_status_to_status")
        .returning(StatusTransition.id)
    )
    return len((await db.execute(stmt)).all())


def to_out(transition: StatusTransition) -> TransitionOut:
    return TransitionOut.model_validate(transition)


def _lifecycle(column: InstrumentedAttribute[str]) -> ColumnElement[int]:
    return case(_LIFECYCLE_ORDER, value=column, else_=len(_LIFECYCLE_ORDER))


async def list_transitions(db: AsyncSession, params: PageParams) -> tuple[list[TransitionOut], int]:
    stmt = select(StatusTransition).order_by(
        _lifecycle(StatusTransition.from_status),
        _lifecycle(StatusTransition.to_status),
        StatusTransition.id,
    )
    rows, total = await paginate(db, stmt, params)
    return [to_out(row[0]) for row in rows], total


async def transitions_from(db: AsyncSession, status: str) -> list[StatusTransition]:
    rows = await db.scalars(
        select(StatusTransition)
        .where(StatusTransition.from_status == status)
        .order_by(_lifecycle(StatusTransition.to_status))
    )
    return list(rows)


def permits(transition: StatusTransition, roles: Iterable[Role]) -> bool:
    """Whether someone holding `roles` may perform `transition` via the API."""
    if transition.system_only:
        return False
    return bool(set(transition.allowed_roles) & {r.value for r in roles})
