"""Verification runs: starting one, executing it, and the nightly sweep.

A run is a row so that a caller can ask for a verification of a long chain and
come back for the answer. The database allows one `pending`/`running` run per
tenant (`uq_audit_chain_verifications_in_flight`), so two simultaneous requests
cannot both start one -- the loser gets an `IntegrityError`, which the router turns
into a 409 rather than the service doing a check-then-insert that both could pass.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.core.pagination import PageParams, paginate, sort_clauses
from app.core.tenancy import get_session_factory, set_tenant, system_session
from app.domains.audit import verification
from app.domains.audit.models import AuditChainVerification

logger = logging.getLogger(__name__)

Mode = verification.Mode
Status = Literal["pending", "running", "passed", "failed", "error"]
SORTS = {"started_at": AuditChainVerification.started_at}


async def start(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    requested_by: uuid.UUID | None,
    from_seq: int = 1,
    to_seq: int | None = None,
    mode: Mode = "db",
) -> AuditChainVerification:
    """Queue a run. Raises `ValidationFailed` for a range the chain cannot answer.

    `IntegrityError` is deliberately not caught: the in-flight unique index is the
    concurrency control, and the caller turns that into a conflict.
    """
    if mode not in ("db", "independent"):
        raise ValidationFailed("mode must be 'db' or 'independent'")
    if from_seq < 1:
        raise ValidationFailed("from_seq must be at least 1")

    head_seq, _ = await verification.chain_head(db, tenant_id)
    if head_seq == 0:
        raise ValidationFailed("this tenant has no audit events to verify")
    effective_to = head_seq if to_seq is None else to_seq
    if effective_to < from_seq:
        raise ValidationFailed(f"to_seq ({effective_to}) must not be before from_seq ({from_seq})")
    if effective_to > head_seq:
        raise ValidationFailed(
            f"to_seq ({effective_to}) is past the head of the chain ({head_seq})"
        )
    limit = get_settings().audit_verify_max_events
    if effective_to - from_seq + 1 > limit:
        raise ValidationFailed(
            f"a single range is limited to {limit} events; ask for a smaller window "
            "or use scripts/verify_audit_chain.py",
            details={"max_events": limit},
        )

    run = AuditChainVerification(
        tenant_id=tenant_id,
        from_seq=from_seq,
        to_seq=effective_to,
        mode=mode,
        status="pending",
        requested_by=requested_by,
    )
    db.add(run)
    await db.flush()
    return run


async def get(db: AsyncSession, verification_id: uuid.UUID) -> AuditChainVerification:
    run = await db.get(AuditChainVerification, verification_id)
    if run is None:
        # Invisible under RLS means "not yours" as well as "does not exist", and a
        # 404 is the right answer to both: no error may leak that it exists.
        raise NotFound("verification run not found")
    return run


async def list_runs(
    db: AsyncSession, params: PageParams, *, status: Status | None = None, sort: str | None = None
) -> tuple[Sequence[Row[AuditChainVerification]], int]:
    statement = select(AuditChainVerification)
    if status is not None:
        statement = statement.where(AuditChainVerification.status == status)
    statement = statement.order_by(
        *sort_clauses(sort, SORTS, default="-started_at", tiebreaker=AuditChainVerification.id)
    )
    rows, total = await paginate(db, statement, params)
    return rows, total


async def abandon(db: AsyncSession, run: AuditChainVerification) -> None:
    """Drop a run that could not be dispatched, so it does not block the next one."""
    await db.delete(run)
    await db.flush()


async def execute(verification_id: uuid.UUID) -> dict[str, Any]:
    """Run one queued verification. Called by the Celery task."""
    async with system_session(reason="audit verification: locate run") as db:
        located = await db.get(AuditChainVerification, verification_id)
        if located is None:
            logger.warning(
                "audit.chain.verification_missing",
                extra={"audit": {"verification_id": str(verification_id)}},
            )
            return {"found": 0}
        tenant_id = located.tenant_id
        from_seq, to_seq, mode = located.from_seq, located.to_seq, located.mode

    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        run = await db.get(AuditChainVerification, verification_id)
        assert run is not None  # located above, same tenant
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await db.commit()

        started = datetime.now(UTC)
        try:
            report = await verification.verify_range(
                db,
                tenant_id=tenant_id,
                from_seq=from_seq,
                to_seq=to_seq,
                mode=mode,  # type: ignore[arg-type]
                batch_size=get_settings().audit_verify_batch_size,
            )
        except Exception as exc:  # a broken run must not stay 'running' forever
            logger.exception(
                "audit.chain.verification_error",
                extra={"audit": {"verification_id": str(verification_id)}},
            )
            run.status = "error"
            run.failure_reason = f"{type(exc).__name__}: {exc}"[:300]
            run.finished_at = datetime.now(UTC)
            await db.commit()
            return {"passed": 0, "failed": 0, "error": 1}

        run.checked_count = report.checked
        finished = datetime.now(UTC)
        run.finished_at = finished
        if report.passed:
            run.status = "passed"
            duration_ms = int((finished - started).total_seconds() * 1000)
            logger.info(
                "audit.chain.verification_passed",
                extra={
                    "audit": {
                        "verification_id": str(verification_id),
                        "tenant_id": str(tenant_id),
                        "checked": report.checked,
                        "duration_ms": duration_ms,
                    }
                },
            )
        else:
            run.status = "failed"
            run.first_bad_seq = report.divergence.chain_seq if report.divergence else None
            run.failure_reason = report.divergence.detail[:300] if report.divergence else None
            logger.error(
                "audit.chain.broken",
                extra={
                    "audit": {
                        "verification_id": str(verification_id),
                        "tenant_id": str(tenant_id),
                        "chain_seq": run.first_bad_seq,
                        "reason": report.divergence.reason if report.divergence else None,
                    }
                },
            )
        await db.commit()
        return {"passed": 1 if report.passed else 0, "failed": 0 if report.passed else 1}


async def sweep(*, mode: Mode = "db") -> dict[str, int]:
    """Verify every tenant chain, incrementally, and the platform chain.

    Incremental from the last passing run keeps the nightly cost flat as the table
    grows; Mondays verify each chain from its first event. The platform chain has no
    row to record against (`tenant_id` is NOT NULL there), so it is verified and
    logged, and stays CLI-verifiable.
    """
    settings = get_settings()
    full = datetime.now(UTC).weekday() == 0
    async with system_session(reason="audit sweep: list tenants") as db:
        tenant_ids = [
            row[0] for row in (await db.execute(text("SELECT id FROM tenants ORDER BY id")))
        ]
        platform = await verification.verify_chain(db, tenant_id=None, mode=mode)

    passed = failed = skipped = 0
    for tenant_id in tenant_ids:
        async with get_session_factory()() as db:
            await set_tenant(db, tenant_id)
            from_seq = 1
            if not full:
                last = (
                    await db.execute(
                        select(AuditChainVerification.to_seq)
                        .where(AuditChainVerification.status == "passed")
                        .order_by(AuditChainVerification.to_seq.desc())
                        .limit(1)
                    )
                ).scalar()
                if last is not None:
                    from_seq = int(last) + 1
            run = AuditChainVerification(
                tenant_id=tenant_id,
                from_seq=max(from_seq, 1),
                to_seq=max(from_seq, 1),
                mode=mode,
                status="running",
                started_at=datetime.now(UTC),
            )
            db.add(run)
            try:
                await db.flush()
            except IntegrityError:
                # Somebody asked for a verification and it has not finished. One run
                # in flight per tenant is the rule, and a stuck request must not stop
                # the nightly sweep for everyone else.
                await db.rollback()
                skipped += 1
                logger.info(
                    "audit.chain.sweep_skipped_in_flight",
                    extra={"audit": {"tenant_id": str(tenant_id)}},
                )
                continue

            report = await verification.verify_range(
                db,
                tenant_id=tenant_id,
                from_seq=max(from_seq, 1),
                to_seq=None,
                mode=mode,
                batch_size=settings.audit_verify_batch_size,
            )
            run.to_seq = max(report.to_seq, run.from_seq)
            run.checked_count = report.checked
            run.finished_at = datetime.now(UTC)
            if report.passed:
                run.status = "passed"
                passed += 1
            else:
                run.status = "failed"
                run.first_bad_seq = report.divergence.chain_seq if report.divergence else None
                run.failure_reason = report.divergence.detail[:300] if report.divergence else None
                failed += 1
                logger.error(
                    "audit.chain.broken",
                    extra={
                        "audit": {
                            "tenant_id": str(tenant_id),
                            "chain_seq": run.first_bad_seq,
                            "reason": report.divergence.reason if report.divergence else None,
                        }
                    },
                )
            await db.commit()

    if not platform.passed:
        logger.error(
            "audit.chain.broken",
            extra={
                "audit": {
                    "tenant_id": None,
                    "chain_seq": platform.divergence.chain_seq if platform.divergence else None,
                    "reason": platform.divergence.reason if platform.divergence else None,
                }
            },
        )
        failed += 1

    return {
        "tenants": len(tenant_ids),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "full": int(full),
        "platform_passed": int(platform.passed),
    }


async def purge(*, older_than_days: int, now: datetime | None = None) -> int:
    """Delete verification runs past their retention. Called by housekeeping.

    Only the runs: the checkpoints and the log itself are evidence and are never
    deleted by a job.
    """
    moment = now or datetime.now(UTC)
    async with system_session(reason="audit verification retention") as db:
        statement = (
            select(AuditChainVerification)
            .where(AuditChainVerification.started_at < moment - timedelta(days=older_than_days))
            .where(AuditChainVerification.status.in_(("passed", "failed", "error")))
        )
        removed = 0
        for run in (await db.execute(statement)).scalars():
            await db.delete(run)
            removed += 1
        return removed
