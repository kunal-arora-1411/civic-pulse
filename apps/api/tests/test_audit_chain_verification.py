"""The verifier: it passes a clean chain and reports the first row that breaks.

Tampering is done as the schema owner with the append-only trigger disabled,
which is exactly the adversary this feature exists for: somebody who can rewrite a
row, or rewrite the hash function that the database-side check would rely on.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import system_session
from app.domains.audit import chain, verification
from tests.factories import create_tenant

Mode = verification.Mode


async def _tenant(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        return (await create_tenant(conn)).id


async def _chain_of(owner_engine: AsyncEngine, tenant_id: uuid.UUID, count: int) -> list[int]:
    """`count` audited events; returns their ids, oldest first."""
    ids: list[int] = []
    async with owner_engine.begin() as conn:
        for index in range(count):
            ids.append(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO audit_events "
                            "(tenant_id, action, entity_type, entity_id, before, after) "
                            "VALUES (:tenant, :action, 'test', :entity, :before, :after) "
                            "RETURNING id"
                        ),
                        {
                            "tenant": tenant_id,
                            "action": f"test.event.{index}",
                            "entity": str(index),
                            "before": json.dumps({"n": index}),
                            "after": json.dumps({"n": index + 1}),
                        },
                    )
                ).scalar_one()
            )
    return ids


async def _tamper(owner_engine: AsyncEngine, statement: str, params: dict[str, Any]) -> None:
    """Perform a write the append-only trigger would refuse."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(text(statement), params)
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )


async def _verify(tenant_id: uuid.UUID, mode: Mode, **kwargs: Any) -> verification.ChainReport:
    async with system_session(reason="test verification") as db:
        return await verification.verify_chain(db, tenant_id=tenant_id, mode=mode, **kwargs)


@pytest.mark.parametrize("mode", ["db", "independent"])
async def test_a_clean_chain_passes_in_both_modes(owner_engine: AsyncEngine, mode: Mode) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 10)

    report = await _verify(tenant_id, mode)
    assert report.passed
    assert report.checked == 10
    assert report.head_seq == 10
    assert report.divergence is None


@pytest.mark.parametrize("mode", ["db", "independent"])
async def test_the_two_modes_agree_on_a_clean_chain(owner_engine: AsyncEngine, mode: Mode) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 5)

    reports = [await _verify(tenant_id, m) for m in ("db", "independent")]
    assert [r.passed for r in reports] == [True, True]
    assert reports[0].checked == reports[1].checked == 5
    assert reports[0].head_hash == reports[1].head_hash


async def test_an_empty_chain_passes_with_nothing_checked(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    report = await _verify(tenant_id, "db")
    assert report.passed
    assert report.checked == 0
    assert report.head_seq == 0


async def test_a_rewritten_payload_is_reported_at_its_own_row(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 6)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET after = :after WHERE id = :id",
        {"after": json.dumps({"n": 999}), "id": ids[3]},
    )

    for mode in ("db", "independent"):
        report = await _verify(tenant_id, mode)
        assert not report.passed
        assert report.divergence is not None
        assert (report.divergence.chain_seq, report.divergence.reason) == (4, "hash")


async def test_a_rewritten_hash_breaks_the_link_to_the_next_row(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 5)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET hash = decode(repeat('77', 32), 'hex') WHERE id = :id",
        {"id": ids[1]},
    )

    report = await _verify(tenant_id, "db")
    assert not report.passed
    assert report.divergence is not None
    assert (report.divergence.chain_seq, report.divergence.reason) == (2, "hash")


async def test_a_deleted_middle_row_is_a_gap(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 5)
    await _tamper(owner_engine, "DELETE FROM audit_events WHERE id = :id", {"id": ids[2]})

    for mode in ("db", "independent"):
        report = await _verify(tenant_id, mode)
        assert not report.passed
        assert report.divergence is not None
        assert (report.divergence.chain_seq, report.divergence.reason) == (3, "gap")


async def test_a_deleted_tail_is_a_gap_up_to_the_head(owner_engine: AsyncEngine) -> None:
    """The head row still says 5, so the missing rows are visible without a checkpoint."""
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 5)
    for event_id in ids[3:]:
        await _tamper(owner_engine, "DELETE FROM audit_events WHERE id = :id", {"id": event_id})

    report = await _verify(tenant_id, "db")
    assert not report.passed
    assert report.divergence is not None
    assert (report.divergence.chain_seq, report.divergence.reason) == (4, "gap")


async def test_a_rewritten_head_row_is_reported(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 3)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE audit_chain_heads SET last_hash = decode(repeat('99', 32), 'hex') "
                "WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )

    report = await _verify(tenant_id, "db")
    assert not report.passed
    assert report.divergence is not None
    assert report.divergence.reason == "head"


async def test_a_window_links_to_the_row_before_it(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 8)

    async with system_session(reason="test verification") as db:
        report = await verification.verify_range(db, tenant_id=tenant_id, from_seq=4, to_seq=8)
    assert report.passed
    assert (report.from_seq, report.to_seq, report.checked) == (4, 8, 5)


async def test_a_window_past_the_head_is_clamped_and_reported(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 3)

    async with system_session(reason="test verification") as db:
        report = await verification.verify_range(db, tenant_id=tenant_id, from_seq=1, to_seq=99)
    assert report.passed
    assert report.to_seq == 3


async def test_a_window_beyond_the_head_reports_a_range_problem(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 3)

    async with system_session(reason="test verification") as db:
        report = await verification.verify_range(db, tenant_id=tenant_id, from_seq=10, to_seq=20)
    assert not report.passed
    assert report.divergence is not None
    assert report.divergence.reason == "range"


async def test_batching_does_not_hide_a_break(owner_engine: AsyncEngine) -> None:
    """A tampered row in a later batch is found with `batch_size=2`."""
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 7)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET before = :before WHERE id = :id",
        {"before": json.dumps({"n": -1}), "id": ids[5]},
    )

    for mode in ("db", "independent"):
        report = await _verify(tenant_id, mode, batch_size=2)
        assert not report.passed
        assert report.divergence is not None
        assert report.divergence.chain_seq == 6


async def test_batching_still_checks_the_link_between_batches(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 7)

    for mode in ("db", "independent"):
        report = await _verify(tenant_id, mode, batch_size=2)
        assert report.passed, f"{mode}: {report.divergence}"


async def test_db_mode_does_not_use_the_python_mirror(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`db` mode is entirely database-side; `independent` is not."""
    tenant_id = await _tenant(owner_engine)
    await _chain_of(owner_engine, tenant_id, 4)

    def explode(_: Any) -> bytes:
        raise AssertionError("db mode must not call the Python framing")

    monkeypatch.setattr(chain, "hash_row", explode)
    assert (await _verify(tenant_id, "db")).passed

    monkeypatch.setattr(chain, "hash_row", lambda _: b"\x00" * 32)
    report = await _verify(tenant_id, "independent")
    assert not report.passed
    assert report.divergence is not None
    assert report.divergence.reason == "hash"


async def _rechain(conn: Any, tenant_id: uuid.UUID) -> None:
    """Recompute every row's link and hash with the function currently installed.

    Used by the test below to make a tampered chain self-consistent for anything
    that trusts the database's own hash function.
    """
    rows = (
        (
            await conn.execute(
                text("SELECT id FROM audit_events WHERE tenant_id = :t ORDER BY chain_seq"),
                {"t": tenant_id},
            )
        )
        .scalars()
        .all()
    )
    previous: bytes = bytes(32)
    for event_id in rows:
        stored = (
            await conn.execute(
                text(
                    "UPDATE audit_events SET prev_hash = :prev, "
                    "hash = audit_hash_v1(:prev, tenant_id, chain_seq, occurred_at, actor_id, "
                    "    action, entity_type, entity_id, before, after, request_id, ip, "
                    "    user_agent) "
                    "WHERE id = :id RETURNING hash"
                ),
                {"prev": previous, "id": event_id},
            )
        ).scalar_one()
        previous = stored
    await conn.execute(
        text(
            "UPDATE audit_chain_heads SET last_hash = :hash, "
            "updated_at = clock_timestamp() WHERE tenant_id = :t"
        ),
        {"hash": previous, "t": tenant_id},
    )


TAMPERED_FRAMING = """
CREATE OR REPLACE FUNCTION audit_framing_v1(
    p_prev bytea, p_tenant uuid, p_seq bigint, p_occurred timestamptz, p_actor uuid,
    p_action text, p_entity_type text, p_entity_id text, p_before jsonb, p_after jsonb,
    p_request_id text, p_ip text, p_user_agent text
) RETURNS text LANGUAGE sql STABLE AS $fn$
    SELECT 'civicpulse.audit.v1'
        || '|prev:' || encode(p_prev, 'hex')
        || '|tenant:' || coalesce(p_tenant::text, '~')
        || '|seq:' || p_seq::text
        || '|occurred_at_us:' || ((extract(epoch FROM p_occurred) * 1000000)::bigint)::text
        || '|actor:' || coalesce(p_actor::text, '~')
        || '|action:' || coalesce(audit_frame_field(p_action), '~')
        || '|entity_type:' || coalesce(audit_frame_field(p_entity_type), '~')
        || '|entity_id:' || coalesce(audit_frame_field(p_entity_id), '~')
        || '|before:~|after:~'
        || '|request_id:' || coalesce(audit_frame_field(p_request_id), '~')
        || '|ip:' || coalesce(audit_frame_field(p_ip), '~')
        || '|user_agent:' || coalesce(audit_frame_field(p_user_agent), '~')
$fn$
"""

FRAMING_OID = (
    "audit_framing_v1(bytea, uuid, bigint, timestamptz, uuid, text, text, text, "
    "jsonb, jsonb, text, text, text)"
)


async def test_independent_mode_catches_a_rewritten_hash_function(
    owner_engine: AsyncEngine,
) -> None:
    """The reason `independent` exists.

    An attacker with owner rights edits a payload and then rewrites
    `audit_framing_v1` so the payload is no longer part of the hash. `db` mode
    recomputes with that same function and therefore agrees; `independent` mode
    frames the row itself and does not.
    """
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 4)
    original = None
    try:
        async with owner_engine.begin() as conn:
            original = (
                await conn.execute(
                    text("SELECT pg_get_functiondef(CAST(:oid AS regprocedure))"),
                    {"oid": FRAMING_OID},
                )
            ).scalar_one()
            await conn.execute(text(TAMPERED_FRAMING))
            await conn.execute(
                text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
            )
            # The payload the attacker wants to hide. Under the tampered framing it
            # is no longer part of the hash.
            await conn.execute(
                text("UPDATE audit_events SET before = CAST(:before AS jsonb) WHERE id = :id"),
                {"before": json.dumps({"n": 666}), "id": ids[-1]},
            )
            # Re-chain every row through the tampered function, so the chain is
            # internally consistent for anything that trusts that function.
            await _rechain(conn, tenant_id)
            await conn.execute(
                text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
            )

        db_report = await _verify(tenant_id, "db")
        independent_report = await _verify(tenant_id, "independent")

        assert db_report.passed, "the database-side check cannot see this by construction"
        assert not independent_report.passed, "the Python mirror must catch it"
        assert independent_report.divergence is not None
        # Every row was re-chained through the rewritten function, so Python already
        # disagrees with the very first one. What matters is that it disagrees at
        # all while the database-side check reports a clean chain.
        assert independent_report.divergence.chain_seq == 1
        assert independent_report.divergence.reason == "hash"
    finally:
        if original is not None:
            async with owner_engine.begin() as conn:
                await conn.execute(text(original))


async def test_the_platform_chain_is_verified_under_the_bypass(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        for index in range(3):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type) "
                    "VALUES (NULL, :action, 'tenant')"
                ),
                {"action": f"platform.test.{index}"},
            )

    for mode in ("db", "independent"):
        async with system_session(reason="test verification") as db:
            report = await verification.verify_chain(db, tenant_id=None, mode=mode)
        assert report.passed, f"{mode}: {report.divergence}"
        assert report.checked >= 3


async def test_one_tenant_never_verifies_anothers_chain(owner_engine: AsyncEngine) -> None:
    first = await _tenant(owner_engine)
    second = await _tenant(owner_engine)
    await _chain_of(owner_engine, first, 3)

    async with system_session(reason="test verification") as db:
        report = await verification.verify_chain(db, tenant_id=second)
    assert report.passed
    assert report.checked == 0, "the verifier must not see another tenant's rows"


async def test_the_summary_carries_the_first_bad_row(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _chain_of(owner_engine, tenant_id, 3)
    await _tamper(
        owner_engine, "UPDATE audit_events SET action = 'x' WHERE id = :id", {"id": ids[1]}
    )
    report = await _verify(tenant_id, "db")
    logged = verification.summary(report)
    assert logged["passed"] is False
    assert logged["first_bad_seq"] == 2
    assert logged["reason"] == "hash"
    assert logged["tenant_id"] == str(tenant_id)


async def test_the_range_guards_are_enforced() -> None:
    async with system_session(reason="test verification") as db:
        with pytest.raises(ValueError, match="from_seq"):
            await verification.verify_range(db, tenant_id=None, from_seq=0)
        with pytest.raises(ValueError, match="to_seq"):
            await verification.verify_range(db, tenant_id=None, from_seq=5, to_seq=4)
