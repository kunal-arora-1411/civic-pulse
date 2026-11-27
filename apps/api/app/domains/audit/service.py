"""Writing and reading the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_client, get_request_id
from app.core.pagination import PageParams, paginate, sort_clauses
from app.core.tenancy import current_tenant, rls_bypass
from app.domains.audit import checkpoints, runs, verification
from app.domains.audit.models import AuditChainVerification, AuditCheckpoint, AuditEvent
from app.domains.audit.schemas import (
    AuditActor,
    AuditChainHeadOut,
    AuditChainStatus,
    AuditChainVerificationOut,
    AuditCheckpointOut,
    AuditEventOut,
    VerificationStatus,
)
from app.domains.rbac.principal import Principal
from app.domains.users.models import User

_UNSET: Any = object()


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor: Principal | None = None,
    actor_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = _UNSET,
) -> None:
    """Append an audit event in the current transaction.

    The event commits or rolls back together with the change it describes.
    The tenant defaults to the actor's, then to the session's current tenant.
    Platform-level events (tenant_id None) are written through the explicit
    bypass, since no tenant policy can match a NULL tenant.
    """
    if tenant_id is _UNSET:
        tenant_id = actor.tenant_id if actor is not None else current_tenant(db)
    client = get_client()
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor.user_id if actor is not None else actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
        request_id=get_request_id(),
        ip=client.ip,
        user_agent=client.user_agent[:400] if client.user_agent else None,
    )
    if tenant_id is None:
        async with rls_bypass(db, reason="platform audit event"):
            db.add(event)
            await db.flush()
    else:
        db.add(event)
        await db.flush()


SORTS = {"occurred_at": AuditEvent.occurred_at}


async def list_events(
    db: AsyncSession,
    params: PageParams,
    *,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    sort: str | None = None,
) -> tuple[list[AuditEventOut], int]:
    stmt = select(AuditEvent, User.display_name).outerjoin(User, User.id == AuditEvent.actor_id)
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if occurred_from is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(AuditEvent.occurred_at < occurred_to)
    stmt = stmt.order_by(
        *sort_clauses(sort, SORTS, default="-occurred_at", tiebreaker=AuditEvent.id)
    )

    rows, total = await paginate(db, stmt, params)
    items = [
        AuditEventOut(
            id=event.id,
            occurred_at=event.occurred_at,
            actor=AuditActor(id=event.actor_id, display_name=display_name)
            if event.actor_id is not None
            else None,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            before=event.before,
            after=event.after,
            request_id=event.request_id,
        )
        for event, display_name in rows
    ]
    return items, total


# --- the hash chain (A6.3) ---------------------------------------------------------------


def _checkpoint_out(checkpoint: Any, keys: dict[str, bytes]) -> AuditCheckpointOut:
    return AuditCheckpointOut(
        id=checkpoint.id,
        up_to_seq=checkpoint.up_to_seq,
        head_hash=bytes(checkpoint.head_hash).hex(),
        key_id=checkpoint.key_id,
        created_at=checkpoint.created_at,
        signature_valid=checkpoints.signature_valid(checkpoint, keys),
    )


def _verification_out(run: Any) -> AuditChainVerificationOut:
    return AuditChainVerificationOut(
        id=run.id,
        status=run.status,
        mode=run.mode,
        from_seq=run.from_seq,
        to_seq=run.to_seq,
        checked_count=run.checked_count,
        first_bad_seq=run.first_bad_seq,
        failure_reason=run.failure_reason,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def chain_status(db: AsyncSession) -> AuditChainStatus:
    """The head, the newest checkpoint and the last verification of this tenant."""
    head_seq, head_hash = await verification.chain_head(db, current_tenant(db))
    occurred_at = None
    if head_seq:
        occurred_at = (
            await db.execute(select(AuditEvent.occurred_at).where(AuditEvent.chain_seq == head_seq))
        ).scalar()

    keys = checkpoints.known_keys()
    newest = await checkpoints.latest(db, current_tenant(db))
    last_checkpoint = _checkpoint_out(newest, keys) if newest is not None else None

    previous = (
        await db.execute(
            select(AuditChainVerification)
            .order_by(AuditChainVerification.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    sealed = newest.up_to_seq if newest is not None else 0
    healthy = (
        (last_checkpoint is None or last_checkpoint.signature_valid)
        and (previous is None or previous.status == "passed")
        and head_seq >= sealed
    )
    return AuditChainStatus(
        events=head_seq,
        head=AuditChainHeadOut(
            seq=head_seq,
            hash=head_hash.hex(),
            occurred_at=occurred_at,
        ),
        last_checkpoint=last_checkpoint,
        unsealed_events=max(head_seq - sealed, 0),
        last_verification=_verification_out(previous) if previous is not None else None,
        healthy=healthy,
    )


async def start_verification(
    db: AsyncSession, principal: Principal, request: Any
) -> AuditChainVerificationOut:
    """Queue a run and record that it was asked for."""
    assert principal.tenant_id is not None
    run = await runs.start(
        db,
        tenant_id=principal.tenant_id,
        requested_by=principal.user_id,
        from_seq=request.from_seq,
        to_seq=request.to_seq,
        mode=request.mode,
    )
    await record(
        db,
        action="audit.chain.verification_requested",
        entity_type="audit_chain_verification",
        entity_id=run.id,
        after={"from_seq": run.from_seq, "to_seq": run.to_seq, "mode": run.mode},
        actor=principal,
    )
    return _verification_out(run)


async def abandon_verification(db: AsyncSession, verification_id: uuid.UUID) -> None:
    """Undo a run that could not be queued, so it does not block the next one."""
    run = await runs.get(db, verification_id)
    await runs.abandon(db, run)


async def list_verifications(
    db: AsyncSession,
    params: PageParams,
    *,
    status: VerificationStatus | None = None,
    sort: str | None = None,
) -> tuple[list[AuditChainVerificationOut], int]:
    rows, total = await runs.list_runs(db, params, status=status, sort=sort)
    return [_verification_out(row[0]) for row in rows], total


async def get_verification(
    db: AsyncSession, verification_id: uuid.UUID
) -> AuditChainVerificationOut:
    return _verification_out(await runs.get(db, verification_id))


async def list_checkpoints(
    db: AsyncSession, params: PageParams
) -> tuple[list[AuditCheckpointOut], int]:
    stmt = (
        select(AuditCheckpoint)
        .order_by(AuditCheckpoint.up_to_seq.desc())
        .limit(params.limit)
        .offset(params.offset)
    )
    rows = list((await db.execute(stmt)).scalars())
    total = int((await db.execute(select(func.count()).select_from(AuditCheckpoint))).scalar_one())
    keys = checkpoints.known_keys()
    return [_checkpoint_out(row, keys) for row in rows], total
