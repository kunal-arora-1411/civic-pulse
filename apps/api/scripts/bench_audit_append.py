"""Measure what the audit hash chain costs an audited write (A6.3, AC-7).

    python scripts/bench_audit_append.py                 # 1000 serial, 100 concurrent
    python scripts/bench_audit_append.py --rows 5000 --concurrency 200 --baseline

This is a script, not a test: CI runners are noisy enough that a latency
threshold there would be a coin flip, and a flaky performance test gets deleted
rather than fixed.

Two numbers matter, and the plan's budget covers both:

* **Added latency per audited INSERT.** The chain adds one row-lock `UPDATE` and
  one SHA-256 to a transaction that was going to happen anyway. Budget: <= 2 ms
  p95, measured against `--baseline`.
* **Behaviour under contention.** `--concurrency` writers in *one* tenant all
  serialise on that tenant's head row, by design. The p95 of the concurrent run
  therefore *includes* queue time and is not comparable to the serial p95 -- what
  it is for is showing that nothing deadlocks or errors, and that throughput
  holds up. Read the `inserts/s` column for that run.

It writes into the database you point it at, in a tenant of its own that it
deletes at the end, so run it against a scratch or staging database, **never
production**:

    DATABASE_URL=postgresql+asyncpg://civicpulse:...@localhost:5432/civicpulse \\
        python scripts/bench_audit_append.py --baseline

`--baseline` needs owner rights: it briefly drops the three `NOT NULL`s, disables
the append trigger, and then deletes its own rows and puts both back. The `try`
in `_chain_disabled` is what guarantees the trigger is enabled again.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  (every mapper configured)
from app.core.db import get_engine
from app.core.tenancy import get_session_factory, set_tenant, system_session

ACTION = "bench.audit.append"
CHAIN_COLUMNS = ("chain_seq", "prev_hash", "hash")
INSERT = text(
    "INSERT INTO audit_events (tenant_id, action, entity_type, entity_id, "
    "before, after, request_id, ip, user_agent) VALUES "
    "(:t, :a, 'bench', 'ent-1', CAST(:b AS jsonb), CAST(:af AS jsonb), "
    "'req-bench', '10.0.0.1', 'bench-agent')"
)
PAYLOAD = {
    "b": '{"n": 1, "note": "a payload of realistic size"}',
    "af": '{"n": 2}',
}


@dataclass
class Stats:
    label: str
    count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    wall_s: float
    errors: int
    #: Only meaningful for the concurrent run; 0 means "not reported".
    per_second: float = 0.0


def _summarise(label: str, samples: list[float], wall: float, errors: int) -> Stats:
    ordered = sorted(samples)
    if not ordered:
        return Stats(label, 0, 0.0, 0.0, 0.0, wall, errors)

    def percentile(fraction: float) -> float:
        # Nearest-rank: no interpolation, which would invent a number that was
        # never measured.
        return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))] * 1000

    return Stats(
        label=label,
        count=len(ordered),
        p50_ms=round(statistics.median(ordered) * 1000, 3),
        p95_ms=round(percentile(0.95), 3),
        max_ms=round(ordered[-1] * 1000, 3),
        wall_s=round(wall, 3),
        errors=errors,
        per_second=round(len(ordered) / wall, 1) if wall > 0 else 0.0,
    )


async def _new_tenant(name: str) -> uuid.UUID:
    slug = f"bench-{uuid.uuid4().hex[:12]}"
    async with system_session(reason="audit append benchmark: tenant") as db:
        return (
            await db.execute(
                text("INSERT INTO tenants (slug, name) VALUES (:slug, :name) RETURNING id"),
                {"slug": slug, "name": name},
            )
        ).scalar_one()


async def _drop_tenant(tenant_id: uuid.UUID) -> None:
    """Best effort. Removing chained rows needs owner rights; the numbers are the point."""
    try:
        async with system_session(reason="audit append benchmark: cleanup") as db:
            # The log is append-only and references tenants ON DELETE RESTRICT, so
            # the rows have to go with the append-only trigger bypassed.
            await db.execute(text("SET LOCAL session_replication_role = 'replica'"))
            await db.execute(
                text("DELETE FROM audit_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await db.execute(
                text("DELETE FROM audit_chain_heads WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    except Exception as exc:
        print(
            f"  note: could not remove the benchmark tenant {tenant_id} "
            f"({type(exc).__name__}: {exc}); clean it up by hand",
            file=sys.stderr,
        )


async def _insert_row(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await db.execute(INSERT, {"t": tenant_id, "a": ACTION, **PAYLOAD})


async def _one_insert(tenant_id: uuid.UUID) -> float:
    """One audited write in its own transaction, the way a request makes it."""
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        started = time.perf_counter()
        await _insert_row(db, tenant_id)
        await db.commit()
        return time.perf_counter() - started


async def serial_run(tenant_id: uuid.UUID, rows: int, label: str) -> Stats:
    samples: list[float] = []
    errors = 0
    wall = time.perf_counter()
    for _ in range(rows):
        try:
            samples.append(await _one_insert(tenant_id))
        except Exception as exc:
            errors += 1
            print(f"  error: {type(exc).__name__}: {exc}", file=sys.stderr)
    return _summarise(label, samples, time.perf_counter() - wall, errors)


async def concurrent_run(tenant_id: uuid.UUID, rows: int, concurrency: int) -> Stats:
    """`rows` inserts, `concurrency` at a time, all into the same chain.

    Everything serialises on that one head row, which is the point: this is the
    shape a burst of logins in a single municipality takes. The samples therefore
    include time spent waiting for the lock, so read `inserts/s`.
    """
    semaphore = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0

    async def worker() -> None:
        nonlocal errors
        async with semaphore:
            try:
                samples.append(await _one_insert(tenant_id))
            except Exception as exc:
                errors += 1
                print(f"  error: {type(exc).__name__}: {exc}", file=sys.stderr)

    wall = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(rows)))
    return _summarise(
        f"{rows} inserts, {concurrency} at a time, one chain",
        samples,
        time.perf_counter() - wall,
        errors,
    )


@asynccontextmanager
async def _chain_disabled() -> AsyncIterator[None]:
    """Temporarily write audit rows the way a pre-0017 deployment did.

    Both halves are needed: without the trigger nothing assigns the chain
    columns, and with `NOT NULL` still in place the row would be rejected. Both
    are put back in the `finally`, including after a failure.
    """
    async with system_session(reason="benchmark: disable the chain") as db:
        await db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_chain_assign"))
        for column in CHAIN_COLUMNS:
            await db.execute(text(f"ALTER TABLE audit_events ALTER COLUMN {column} DROP NOT NULL"))
    try:
        yield
    finally:
        # The unchained rows have to go before NOT NULL can come back.
        async with system_session(reason="benchmark: drop unchained rows") as db:
            await db.execute(text("SET LOCAL session_replication_role = 'replica'"))
            await db.execute(text("DELETE FROM audit_events WHERE chain_seq IS NULL"))
        async with system_session(reason="benchmark: restore the chain") as db:
            for column in CHAIN_COLUMNS:
                await db.execute(
                    text(f"ALTER TABLE audit_events ALTER COLUMN {column} SET NOT NULL")
                )
            await db.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_chain_assign"))


async def _chain_health(tenant_id: uuid.UUID) -> str:
    """Contiguous and distinct, or the benchmark is not measuring what it claims."""
    async with system_session(reason="benchmark: check the chain") as db:
        row = (
            await db.execute(
                text(
                    "SELECT count(*) AS n, count(DISTINCT chain_seq) AS distinct_seq, "
                    "       max(chain_seq) AS head FROM audit_events WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).one()
    count, distinct, head = int(row.n), int(row.distinct_seq), int(row.head)
    if count == distinct == head:
        return f"chain: {count} rows, contiguous 1..{head} -- OK"
    return f"chain: {count} rows, {distinct} distinct, head at {head} -- BROKEN"


def _print(stats: list[Stats]) -> None:
    width = max(len(s.label) for s in stats)
    print(
        f"{'run':<{width}}  {'n':>6}  {'p50 ms':>8}  {'p95 ms':>8}  {'max ms':>8}  "
        f"{'wall s':>7}  {'ins/s':>8}  errors"
    )
    for s in stats:
        rate = f"{s.per_second:.1f}" if s.per_second else "-"
        print(
            f"{s.label:<{width}}  {s.count:>6}  {s.p50_ms:>8.3f}  {s.p95_ms:>8.3f}  "
            f"{s.max_ms:>8.3f}  {s.wall_s:>7.3f}  {rate:>8}  {s.errors}"
        )


async def main_async(args: argparse.Namespace) -> int:
    baseline: Stats | None = None
    chained_tenant = await _new_tenant("Bench chained")
    stats: list[Stats] = []
    try:
        if args.baseline:
            baseline_tenant = await _new_tenant("Bench baseline")
            try:
                async with _chain_disabled():
                    baseline = await serial_run(
                        baseline_tenant, args.rows, "serial, no chain (baseline)"
                    )
            finally:
                await _drop_tenant(baseline_tenant)
            stats.append(baseline)

        stats.append(await serial_run(chained_tenant, args.rows, "serial, chained"))
        stats.append(await concurrent_run(chained_tenant, args.concurrency, args.concurrency))

        health = await _chain_health(chained_tenant)
        print()
        _print(stats)
        print()
        print(health)
        if baseline is not None:
            added_p95 = round(stats[1].p95_ms - baseline.p95_ms, 3)
            added_p50 = round(stats[1].p50_ms - baseline.p50_ms, 3)
            print(
                f"added by the chain: p50 {added_p50} ms, p95 {added_p95} ms (budget <= 2 ms p95)"
            )
        print("the concurrent p95 includes waiting for the per-chain head lock; read inserts/s")
        ok = not any(s.errors for s in stats) and health.endswith("OK")
        return 0 if ok else 1
    finally:
        await _drop_tenant(chained_tenant)
        await get_engine().dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the cost of the audit hash chain.")
    parser.add_argument("--rows", type=int, default=1000, help="serial inserts")
    parser.add_argument(
        "--concurrency", type=int, default=100, help="concurrent inserts into one chain"
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="also time the same inserts with the chain off (needs owner rights)",
    )
    args = parser.parse_args(argv)
    if args.rows < 1 or args.concurrency < 1:
        parser.error("--rows and --concurrency must be at least 1")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
