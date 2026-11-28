"""Verify the audit hash chain, and report the first row that breaks it.

    python scripts/verify_audit_chain.py --tenant demo-city
    python scripts/verify_audit_chain.py --all-tenants --mode independent
    python scripts/verify_audit_chain.py --platform --checkpoints

This is the operator's tool (A6.3). The API endpoint and the nightly task walk
one tenant's chain through RLS; this script is the only way to verify the
platform chain, because reaching tenant-less rows needs the bypass and no
tenant-scoped endpoint is allowed to hold one.

Exit codes are the contract, so a cron line or a CI step can depend on them:

    0   every chain checked passed
    1   a divergence was found, or a signed checkpoint no longer holds
    2   usage error, or the database could not be reached

`--mode independent` recomputes every hash in Python instead of asking Postgres
to do it, so it still reports a break if somebody rewrote `audit_hash_v1` to
agree with edited rows. That is why it is the default here; the nightly job
uses `db` mode because it is much cheaper.

What this never prints is a row's `before`/`after` payload. Those can hold
personal data (PRD §12.2). A failed verification needs the sequence, the
action and the instant to be actionable, and nothing more.

With `--checkpoints`, a signature failure is folded into the verdict of the
chain it belongs to rather than reported as a separate row: a tenant whose
signed head no longer holds has not passed, whatever its rows say.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  (every mapper configured)
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.tenancy import get_session_factory, rls_bypass, set_tenant, system_session
from app.domains.audit import checkpoints as checkpoint_engine
from app.domains.audit import verification

EXIT_OK = 0
EXIT_BROKEN = 1
EXIT_USAGE = 2

PLATFORM_LABEL = "—"


@dataclass(frozen=True, slots=True)
class Target:
    """One chain to walk: a tenant's, or the platform one when `tenant_id` is None."""

    label: str
    scope: str
    tenant_id: uuid.UUID | None


@dataclass(slots=True)
class Outcome:
    """What one chain produced, ready to be printed as a row or as JSON."""

    target: Target
    report: verification.ChainReport | None = None
    context: dict[str, str] | None = None
    signatures_checked: int = 0
    signature_failures: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.report is not None
            and self.report.passed
            and not self.signature_failures
        )

    @property
    def bad_seq(self) -> int | None:
        return self.report.divergence.chain_seq if self.report and self.report.divergence else None

    def line(self) -> str:
        """The human row, plus detail lines under it when it did not pass."""
        events = self.report.head_seq if self.report else 0
        span = f"{self.report.from_seq}..{self.report.to_seq}" if self.report else "—"
        mode = self.report.mode if self.report else "—"
        if self.error is not None:
            verdict = f"ERROR: {self.error}"
        elif self.passed:
            verdict = "PASS"
        elif self.signature_failures:
            verdict = "FAIL at checkpoint"
        else:
            verdict = f"FAIL at chain_seq {self.bad_seq}"
        head = (
            f"{self.target.label:<12} {self.target.scope:<10} {events:>8}  "
            f"{span:<14} {mode:<12} {verdict}"
        )
        if self.passed or self.error is not None:
            return head

        lines = [head]
        for failure in self.signature_failures:
            lines.append(
                f"  checkpoint {failure['checkpoint_id']} at seq {failure['up_to_seq']}: "
                f"{failure['reason']}"
            )
        if self.report is not None and self.report.divergence is not None:
            divergence = self.report.divergence
            lines.append(f"  reason: {divergence.reason} — {divergence.detail}")
            if self.context is not None:
                lines.append(
                    f"  row: action={self.context['action']} "
                    f"entity_type={self.context['entity_type']} "
                    f"occurred_at={self.context['occurred_at']}"
                )
        lines.append("  next: docs/runbooks/audit-chain-recovery.md")
        return "\n".join(lines)

    def as_json(self) -> dict[str, Any]:
        body: dict[str, Any] = (
            verification.summary(self.report)
            if self.report is not None
            else {"tenant_id": _scope_id(self.target), "passed": False}
        )
        body.update(
            {
                "label": self.target.label,
                "scope": self.target.scope,
                "ok": self.passed,
                "signatures_checked": self.signatures_checked,
                "signature_failures": self.signature_failures,
            }
        )
        if self.context is not None:
            body["row"] = self.context
        if self.error is not None:
            body["error"] = self.error
        return body


def _scope_id(target: Target) -> str | None:
    return str(target.tenant_id) if target.tenant_id is not None else None


@asynccontextmanager
async def scoped(tenant_id: uuid.UUID | None, *, reason: str) -> AsyncIterator[AsyncSession]:
    """A session scoped to one chain: the tenant's under RLS, the platform's under bypass.

    Going through `set_tenant` for a tenant means the CLI exercises the same
    policy an operator's request would, rather than only ever working because
    the bypass happens to be on.
    """
    async with get_session_factory()() as db:
        if tenant_id is None:
            async with rls_bypass(db, reason=reason):
                yield db
        else:
            await set_tenant(db, tenant_id)
            yield db
        await db.rollback()


async def _row_context(
    db: AsyncSession, tenant_id: uuid.UUID | None, seq: int | None
) -> dict[str, str] | None:
    """`action`, `entity_type` and `occurred_at` of a row — never its payload."""
    if seq is None:
        return None
    row = (
        await db.execute(
            text(
                "SELECT action, entity_type, occurred_at FROM audit_events "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant AND chain_seq = :seq"
            ),
            {"tenant": tenant_id, "seq": seq},
        )
    ).first()
    if row is None:
        return None
    return {
        "action": str(row.action),
        "entity_type": str(row.entity_type),
        "occurred_at": row.occurred_at.astimezone(UTC).isoformat(),
    }


async def verify_target(
    target: Target,
    *,
    from_seq: int,
    to_seq: int | None,
    mode: verification.Mode,
    batch_size: int,
    checkpoints: bool,
) -> Outcome:
    """Walk one chain, and check its signed checkpoints when asked."""
    outcome = Outcome(target=target)
    async with scoped(target.tenant_id, reason="audit chain CLI") as db:
        if checkpoints:
            for checkpoint in await checkpoint_engine.checkpoints_for(db, target.tenant_id):
                outcome.signatures_checked += 1
                ok, reason = await checkpoint_engine.verify_checkpoint(db, checkpoint)
                if not ok:
                    outcome.signature_failures.append(
                        {
                            "checkpoint_id": str(checkpoint.id),
                            "up_to_seq": checkpoint.up_to_seq,
                            "key_id": checkpoint.key_id,
                            "reason": reason,
                        }
                    )

        report = await verification.verify_range(
            db,
            tenant_id=target.tenant_id,
            from_seq=from_seq,
            to_seq=to_seq,
            mode=mode,
            batch_size=batch_size,
        )
        context = (
            await _row_context(db, target.tenant_id, report.divergence.chain_seq)
            if report.divergence is not None
            else None
        )

    outcome.report = report
    outcome.context = context
    return outcome


async def resolve_targets(args: argparse.Namespace) -> list[Target]:
    """Turn the scope flags into the chains to walk."""
    if args.tenant is not None:
        async with system_session(reason="audit chain CLI: resolve a tenant") as db:
            tenant_id = (
                await db.execute(
                    text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": args.tenant}
                )
            ).scalar()
        if tenant_id is None:
            raise LookupError(f"no tenant with slug {args.tenant!r}")
        return [Target(label=args.tenant, scope="tenant", tenant_id=tenant_id)]

    if args.platform:
        return [Target(label=PLATFORM_LABEL, scope="platform", tenant_id=None)]

    async with system_session(reason="audit chain CLI: list tenants") as db:
        tenants = (await db.execute(text("SELECT id, slug FROM tenants ORDER BY slug"))).all()
    targets = [Target(label=row.slug, scope="tenant", tenant_id=row.id) for row in tenants]
    targets.append(Target(label=PLATFORM_LABEL, scope="platform", tenant_id=None))
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the tamper-evident audit chain (A6.3).",
        epilog="exit 0 passed, 1 broken, 2 usage error or no database",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--tenant", metavar="SLUG", help="one tenant, by slug")
    scope.add_argument(
        "--all-tenants", action="store_true", help="every tenant chain, then the platform one"
    )
    scope.add_argument(
        "--platform", action="store_true", help="only the tenant-less chain (needs the bypass)"
    )
    parser.add_argument("--from-seq", type=int, default=1, metavar="N")
    parser.add_argument("--to-seq", type=int, default=None, metavar="N")
    parser.add_argument(
        "--mode",
        choices=("db", "independent"),
        default="independent",
        help="independent recomputes in Python and does not trust the SQL function (default)",
    )
    parser.add_argument("--batch-size", type=int, default=None, metavar="N")
    parser.add_argument(
        "--checkpoints", action="store_true", help="verify the signed checkpoints too"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--fail-fast",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="stop at the first broken chain (--no-fail-fast walks all of them)",
    )
    return parser


def _print_human(outcomes: list[Outcome]) -> None:
    print(f"{'tenant':<12} {'chain':<10} {'events':>8}  {'range':<14} {'mode':<12} result")
    for outcome in outcomes:
        print(outcome.line())
    print()


def _print_summary(outcomes: list[Outcome], elapsed_ms: int) -> None:
    events = sum(o.report.checked if o.report else 0 for o in outcomes)
    signatures = sum(o.signatures_checked for o in outcomes)
    seal_note = f", {signatures} signatures checked" if signatures else ""
    verdict = "PASS" if all(o.passed for o in outcomes) else "FAIL"
    print(f"{len(outcomes)} chains, {events} events{seal_note}: {verdict} ({elapsed_ms} ms)")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    batch_size = args.batch_size or settings.audit_verify_batch_size
    if batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.from_seq < 1:
        raise ValueError("--from-seq must be at least 1")
    if args.to_seq is not None and args.to_seq < args.from_seq:
        raise ValueError("--to-seq must not be before --from-seq")

    targets = await resolve_targets(args)
    if not targets:
        raise LookupError("no tenants to verify")

    started = datetime.now(UTC)
    outcomes: list[Outcome] = []
    for target in targets:
        try:
            outcome = await verify_target(
                target,
                from_seq=args.from_seq,
                to_seq=args.to_seq,
                mode=args.mode,
                batch_size=batch_size,
                checkpoints=args.checkpoints,
            )
        except SQLAlchemyError as exc:
            outcome = Outcome(target=target, error=f"{type(exc).__name__}: {exc}")
        outcomes.append(outcome)
        if not outcome.passed and args.fail_fast:
            break

    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    if args.json:
        for outcome in outcomes:
            print(json.dumps(outcome.as_json(), default=str))
        print(
            json.dumps(
                {
                    "summary": {
                        "chains": len(outcomes),
                        "passed": sum(1 for o in outcomes if o.passed),
                        "failed": sum(1 for o in outcomes if not o.passed),
                        "ok": all(o.passed for o in outcomes),
                        "duration_ms": elapsed_ms,
                    }
                }
            )
        )
    else:
        _print_human(outcomes)
        _print_summary(outcomes, elapsed_ms)

    return EXIT_OK if all(outcome.passed for outcome in outcomes) else EXIT_BROKEN


async def run(args: argparse.Namespace) -> int:
    """The whole command apart from process teardown, so a test can call it.

    Every exit code lives here: a caller that only wants the verdict (a test, or
    a wrapper script) never has to catch anything.
    """
    try:
        return await _run(args)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        # Settings validation and argument checks both land here.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (SQLAlchemyError, OSError) as exc:
        # A database that cannot be reached is a usage-class failure for whoever
        # ran this, and never the same finding as a broken chain.
        print(f"error: the database could not be reached: {exc}", file=sys.stderr)
        return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    async def _main() -> int:
        try:
            return await run(args)
        finally:
            # Only a real process tears down the engine; a test shares it.
            await get_engine().dispose()

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
