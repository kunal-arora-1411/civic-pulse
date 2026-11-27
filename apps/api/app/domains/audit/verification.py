"""Walk a chain and report the first place it breaks.

Two modes, because they answer different questions:

* `db` asks Postgres to recompute each hash with `audit_hash_v1` and compares it
  to the stored one. One statement per batch, one SHA-256 per row, all inside the
  database -- fast enough for the nightly sweep.
* `independent` fetches the framed columns and recomputes in Python
  (`app.domains.audit.chain`), never calling the SQL function. This is what
  catches somebody who rewrote `audit_hash_v1` to agree with edited rows, which
  `db` mode cannot see by construction.

Both walk the chain in `chain_seq` order and stop at the first divergence: the
tail after a break is not evidence of anything, and an operator wants the earliest
row to investigate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit import chain

Mode = Literal["db", "independent"]
#: `head` is a rewritten row in audit_chain_heads rather than in the log.
Reason = Literal["gap", "link", "hash", "range", "head"]

DEFAULT_BATCH_SIZE = 5_000


@dataclass(frozen=True, slots=True)
class Divergence:
    chain_seq: int
    reason: Reason
    detail: str


@dataclass(frozen=True, slots=True)
class ChainReport:
    tenant_id: uuid.UUID | None
    from_seq: int
    to_seq: int
    mode: Mode
    checked: int
    head_seq: int
    head_hash: bytes
    divergence: Divergence | None = None

    @property
    def passed(self) -> bool:
        return self.divergence is None


async def chain_head(db: AsyncSession, tenant_id: uuid.UUID | None) -> tuple[int, bytes]:
    """The last `(sequence, hash)` of a chain, or `(0, GENESIS)` when it is empty.

    Read from `audit_chain_heads`, the row the append trigger keeps in step with
    the log. For the platform chain the session must hold the RLS bypass, like
    any other read of a tenant-less row.
    """
    row = (
        await db.execute(
            text(
                "SELECT next_seq, last_hash FROM audit_chain_heads "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant"
            ),
            {"tenant": tenant_id},
        )
    ).first()
    if row is None:
        return 0, chain.GENESIS_HASH
    return int(row.next_seq) - 1, bytes(row.last_hash)


async def _hash_at(db: AsyncSession, tenant_id: uuid.UUID | None, seq: int) -> bytes | None:
    value = (
        await db.execute(
            text(
                "SELECT hash FROM audit_events "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant AND chain_seq = :seq"
            ),
            {"tenant": tenant_id, "seq": seq},
        )
    ).scalar()
    return None if value is None else bytes(value)


async def _first_gap(db: AsyncSession, tenant_id: uuid.UUID | None, lo: int, hi: int) -> int | None:
    """The lowest missing sequence in `[lo, hi]`, if any."""
    found = (
        await db.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant AND chain_seq BETWEEN :lo AND :hi"
            ),
            {"tenant": tenant_id, "lo": lo, "hi": hi},
        )
    ).scalar_one()
    if int(found) == hi - lo + 1:
        return None
    return (
        await db.execute(
            text(
                "SELECT g FROM generate_series(CAST(:lo AS bigint), CAST(:hi AS bigint)) AS g "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM audit_events e "
                "   WHERE e.tenant_id IS NOT DISTINCT FROM :tenant AND e.chain_seq = g) "
                "ORDER BY g LIMIT 1"
            ),
            {"tenant": tenant_id, "lo": lo, "hi": hi},
        )
    ).scalar_one()


# `lag()` needs one row of context before the window, or every batch would look
# like it begins a chain and the link between batches would never be checked.
_DB_BATCH = text(
    """
    WITH scanned AS (
        SELECT chain_seq, prev_hash, hash,
               audit_hash_v1(prev_hash, tenant_id, chain_seq, occurred_at, actor_id, action,
                             entity_type, entity_id, before, after, request_id, ip,
                             user_agent) AS expected,
               lag(hash) OVER (ORDER BY chain_seq) AS prior_hash
          FROM audit_events
         WHERE tenant_id IS NOT DISTINCT FROM :tenant
           AND chain_seq BETWEEN :seed AND :hi
    )
    SELECT chain_seq, prev_hash, hash, prior_hash, expected
      FROM scanned
     WHERE chain_seq >= :lo
       AND (
            (prior_hash IS NOT NULL AND prev_hash <> prior_hash)
         OR hash <> expected
         OR (chain_seq = 1 AND prev_hash <> decode(repeat('00', 32), 'hex'))
       )
     ORDER BY chain_seq
     LIMIT 1
    """
)

_INDEPENDENT_BATCH = text(
    """
    SELECT tenant_id, chain_seq, prev_hash, hash, occurred_at, actor_id, action,
           entity_type, entity_id, before::text AS before_text,
           after::text AS after_text, request_id, ip, user_agent
      FROM audit_events
     WHERE tenant_id IS NOT DISTINCT FROM :tenant
       AND chain_seq BETWEEN :lo AND :hi
     ORDER BY chain_seq
    """
)


def _db_reason(
    prev_hash: bytes, prior_hash: bytes | None, seq: int, stored: bytes, expected: bytes
) -> tuple[Reason, str]:
    if seq == 1 and prev_hash != chain.GENESIS_HASH:
        return "link", "the first event does not start from the genesis hash"
    if prior_hash is not None and prev_hash != prior_hash:
        return "link", (
            f"prev_hash {prev_hash.hex()[:16]}… does not match the previous row's hash "
            f"{prior_hash.hex()[:16]}…"
        )
    return "hash", (
        f"stored hash {stored.hex()[:16]}… does not match the recomputed {expected.hex()[:16]}…"
    )


async def verify_range(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    from_seq: int = 1,
    to_seq: int | None = None,
    mode: Mode = "db",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ChainReport:
    """Verify `[from_seq, to_seq]` inclusive, in batches, stopping at the first break.

    `to_seq` past the head is clamped to the head, and the clamped value is what
    the report carries: a report must describe the range it actually checked. An
    empty chain passes with `checked == 0` -- there is nothing to disagree with,
    and an empty chain is not an error.
    """
    if from_seq < 1:
        raise ValueError("from_seq must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if to_seq is not None and to_seq < from_seq:
        raise ValueError("to_seq must not be before from_seq")

    head_seq, head_hash = await chain_head(db, tenant_id)
    effective_to = head_seq if to_seq is None else min(to_seq, head_seq)
    report = ChainReport(
        tenant_id=tenant_id,
        from_seq=from_seq,
        to_seq=effective_to,
        mode=mode,
        checked=0,
        head_seq=head_seq,
        head_hash=head_hash,
    )
    if head_seq == 0:
        return report
    if from_seq > effective_to:
        return replace(
            report,
            divergence=Divergence(
                from_seq, "range", f"the window starts at {from_seq} but the head is {head_seq}"
            ),
        )

    # The window's predecessor: without it the first row's prev_hash has nothing
    # to be compared against.
    prior: bytes | None = None
    if from_seq > 1:
        prior = await _hash_at(db, tenant_id, from_seq - 1)
        if prior is None:
            return replace(
                report,
                divergence=Divergence(from_seq - 1, "gap", "the row before the window is missing"),
            )

    checked = 0
    lo = from_seq
    while lo <= effective_to:
        hi = min(lo + batch_size - 1, effective_to)

        gap = await _first_gap(db, tenant_id, lo, hi)
        if gap is not None:
            return replace(
                report,
                checked=checked,
                divergence=Divergence(gap, "gap", f"no event at chain_seq {gap}"),
            )

        if mode == "db":
            # The whole batch in one statement; `prior` is not needed here because
            # the SQL carries it (the `seed` row) across the batch boundary.
            row = (
                await db.execute(
                    _DB_BATCH,
                    {"tenant": tenant_id, "seed": max(lo - 1, 1), "lo": lo, "hi": hi},
                )
            ).first()
            if row is not None:
                reason, detail = _db_reason(
                    bytes(row.prev_hash),
                    None if row.prior_hash is None else bytes(row.prior_hash),
                    int(row.chain_seq),
                    bytes(row.hash),
                    bytes(row.expected),
                )
                checked += int(row.chain_seq) - lo + 1
                return replace(
                    report,
                    checked=checked,
                    divergence=Divergence(int(row.chain_seq), reason, detail),
                )
            checked += hi - lo + 1
        else:
            rows = (
                await db.execute(_INDEPENDENT_BATCH, {"tenant": tenant_id, "lo": lo, "hi": hi})
            ).all()
            for row in rows:
                seq = int(row.chain_seq)
                stored = bytes(row.hash)
                prev_hash = bytes(row.prev_hash)
                expected = chain.hash_row(dict(row._mapping))
                if seq == 1 and prev_hash != chain.GENESIS_HASH:
                    checked += 1
                    return replace(
                        report,
                        checked=checked,
                        divergence=Divergence(
                            seq, "link", "the first event does not start from the genesis hash"
                        ),
                    )
                if prior is not None and prev_hash != prior:
                    checked += 1
                    return replace(
                        report,
                        checked=checked,
                        divergence=Divergence(
                            seq,
                            "link",
                            f"prev_hash {prev_hash.hex()[:16]}… does not match the previous "
                            f"row's hash {prior.hex()[:16]}…",
                        ),
                    )
                if stored != expected:
                    checked += 1
                    return replace(
                        report,
                        checked=checked,
                        divergence=Divergence(
                            seq,
                            "hash",
                            f"stored hash {stored.hex()[:16]}… does not match the recomputed "
                            f"{expected.hex()[:16]}…",
                        ),
                    )
                checked += 1
                prior = stored

        lo = hi + 1

    # The head row is mutable and the log is not: if they disagree, something
    # rewrote one of them. Only meaningful when the window reaches the head.
    if effective_to == head_seq and head_seq > 0:
        last = await _hash_at(db, tenant_id, head_seq)
        if last is None or last != head_hash:
            return replace(
                report,
                checked=checked,
                divergence=Divergence(
                    head_seq,
                    "head",
                    "audit_chain_heads does not match the last event in the log",
                ),
            )

    return replace(report, checked=checked)


async def verify_chain(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    mode: Mode = "db",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ChainReport:
    """Verify a whole chain from its first event."""
    return await verify_range(
        db, tenant_id=tenant_id, from_seq=1, to_seq=None, mode=mode, batch_size=batch_size
    )


def summary(report: ChainReport) -> dict[str, Any]:
    """The shape tasks and the CLI log."""
    return {
        "tenant_id": str(report.tenant_id) if report.tenant_id else None,
        "from_seq": report.from_seq,
        "to_seq": report.to_seq,
        "mode": report.mode,
        "checked": report.checked,
        "passed": report.passed,
        "head_seq": report.head_seq,
        "first_bad_seq": report.divergence.chain_seq if report.divergence else None,
        "reason": report.divergence.reason if report.divergence else None,
        "detail": report.divergence.detail if report.divergence else None,
    }
