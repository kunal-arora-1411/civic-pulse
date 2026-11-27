"""Checkpoints: sealing a head, signing it, and catching a truncated tail.

The signature is the part a database attacker cannot reproduce, so these tests
sign with a key they pass in explicitly and verify that a wrong key, a swapped
signature, or a rewritten head all fail.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import set_tenant, system_session
from app.domains.audit import checkpoints, runs, verification
from app.domains.audit.checkpoints import AnchorKey, AnchorKeyMissing
from app.domains.audit.models import AuditChainVerification, AuditCheckpoint
from tests.factories import create_tenant

KEY = AnchorKey(key_id="k1", secret=b"a-test-anchor-key-that-is-long-enough")
OTHER = AnchorKey(key_id="k1", secret=b"a-different-key-of-the-same-length!!")
KEYS = {KEY.key_id: KEY.secret}


async def _tenant(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        return (await create_tenant(conn)).id


async def _events(owner_engine: AsyncEngine, tenant_id: uuid.UUID, count: int) -> list[int]:
    ids: list[int] = []
    async with owner_engine.begin() as conn:
        for index in range(count):
            ids.append(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO audit_events (tenant_id, action, entity_type) "
                            "VALUES (:tenant, :action, 'test') RETURNING id"
                        ),
                        {"tenant": tenant_id, "action": f"test.event.{index}"},
                    )
                ).scalar_one()
            )
    return ids


async def _seal(tenant_id: uuid.UUID, **kwargs: Any) -> checkpoints.SealResult | None:
    async with system_session(reason="test sealing") as db:
        await set_tenant(db, tenant_id)
        return await checkpoints.seal(db, tenant_id=tenant_id, key=KEY, **kwargs)


async def _rows(tenant_id: uuid.UUID) -> list[AuditCheckpoint]:
    async with system_session(reason="test checkpoints") as db:
        await set_tenant(db, tenant_id)
        return await checkpoints.checkpoints_for(db, tenant_id)


async def test_sealing_records_the_head_and_a_valid_signature(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 4)

    result = await _seal(tenant_id)
    assert result is not None
    assert (result.up_to_seq, result.created, result.refused) == (4, True, False)

    [checkpoint] = await _rows(tenant_id)
    assert checkpoint.up_to_seq == 4
    assert checkpoint.key_id == "k1"
    assert checkpoints.signature_valid(checkpoint, KEYS)
    assert len(checkpoint.signature) == 32


async def test_sealing_twice_adds_nothing(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 3)
    assert await _seal(tenant_id) is not None

    assert await _seal(tenant_id) is None
    assert len(await _rows(tenant_id)) == 1


async def test_sealing_again_after_more_events_moves_the_head(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    await _seal(tenant_id)
    await _events(owner_engine, tenant_id, 3)
    await _seal(tenant_id)

    sealed = await _rows(tenant_id)
    assert [c.up_to_seq for c in sealed] == [5, 2]
    assert all(checkpoints.signature_valid(c, KEYS) for c in sealed)


async def test_an_empty_chain_is_not_sealed(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    assert await _seal(tenant_id) is None


async def test_a_broken_chain_is_not_sealed(owner_engine: AsyncEngine) -> None:
    """The seal is refused, so the evidence stays at the last good state."""
    tenant_id = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant_id, 4)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"), {"id": ids[2]}
        )
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )

    result = await _seal(tenant_id)
    assert result is not None
    assert result.refused is True
    assert result.created is False
    assert await _rows(tenant_id) == []


async def test_no_key_means_no_seal(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 1)
    async with system_session(reason="test sealing") as db:
        await set_tenant(db, tenant_id)
        with pytest.raises(AnchorKeyMissing):
            await checkpoints.seal(db, tenant_id=tenant_id)


async def test_a_wrong_key_does_not_verify(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    await _seal(tenant_id)

    [checkpoint] = await _rows(tenant_id)
    assert checkpoints.signature_valid(checkpoint, KEYS)
    assert not checkpoints.signature_valid(checkpoint, {OTHER.key_id: OTHER.secret})


async def test_an_unknown_key_id_does_not_verify(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    await _seal(tenant_id)

    [checkpoint] = await _rows(tenant_id)
    assert not checkpoints.signature_valid(checkpoint, {"k9": KEY.secret})


async def test_a_swapped_signature_does_not_verify(owner_engine: AsyncEngine) -> None:
    """Copying one checkpoint's signature onto another is detected."""
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    await _seal(tenant_id)
    await _events(owner_engine, tenant_id, 2)
    await _seal(tenant_id)
    # `checkpoints_for` is newest first, so the *first* row is the newer seal.
    newer, older = await _rows(tenant_id)

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_checkpoints DISABLE TRIGGER audit_checkpoints_no_update_delete")
        )
        await conn.execute(
            text("UPDATE audit_checkpoints SET signature = :sig WHERE id = :id"),
            {"sig": older.signature, "id": newer.id},
        )
        await conn.execute(
            text("ALTER TABLE audit_checkpoints ENABLE TRIGGER audit_checkpoints_no_update_delete")
        )

    async with system_session(reason="test verification") as db:
        await set_tenant(db, tenant_id)
        fresh = await checkpoints.latest(db, tenant_id)
        assert fresh is not None
        ok, reason = await checkpoints.verify_checkpoint(db, fresh, KEYS)
    assert not ok
    assert reason is not None
    assert "signature" in reason


async def test_a_truncated_tail_is_caught_by_the_checkpoint(
    owner_engine: AsyncEngine,
) -> None:
    """The chain alone cannot see this; the signed head can."""
    tenant_id = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant_id, 5)
    await _seal(tenant_id)

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(text("DELETE FROM audit_events WHERE id = ANY(:ids)"), {"ids": ids[3:]})
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )
        # The attacker also repairs the head row so a na*ve check sees nothing.
        await conn.execute(
            text(
                "UPDATE audit_chain_heads SET next_seq = 4, "
                "last_hash = (SELECT hash FROM audit_events WHERE id = :id) "
                "WHERE tenant_id = :t"
            ),
            {"id": ids[2], "t": tenant_id},
        )

    async with system_session(reason="test verification") as db:
        await set_tenant(db, tenant_id)
        checkpoint = await checkpoints.latest(db, tenant_id)
        assert checkpoint is not None
        ok, reason = await checkpoints.verify_checkpoint(db, checkpoint, KEYS)
    assert not ok
    assert reason is not None
    assert "chain_seq 5" in reason


async def test_a_rewritten_signed_row_is_caught(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant_id, 3)
    await _seal(tenant_id)

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text("UPDATE audit_events SET hash = decode(repeat('00', 32), 'hex') WHERE id = :id"),
            {"id": ids[2]},
        )
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )

    async with system_session(reason="test verification") as db:
        await set_tenant(db, tenant_id)
        checkpoint = await checkpoints.latest(db, tenant_id)
        assert checkpoint is not None
        ok, reason = await checkpoints.verify_checkpoint(db, checkpoint, KEYS)
    assert not ok
    assert reason is not None
    assert "no longer matches" in reason


def test_the_signed_message_binds_scope_sequence_hash_and_time() -> None:
    moment = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    digest = bytes(range(32))
    tenant = uuid.UUID("11111111-1111-1111-1111-111111111111")

    body = checkpoints.message(tenant, 7, digest, moment).decode()
    assert body.startswith("civicpulse.audit.checkpoint.v1|")
    assert "|scope:11111111-1111-1111-1111-111111111111|" in body
    assert "|seq:7|" in body
    assert f"|hash:{digest.hex()}|" in body

    assert "|scope:platform|" in checkpoints.message(None, 7, digest, moment).decode()
    # A different instant is a different message, so a signature cannot be moved.
    assert checkpoints.message(tenant, 7, digest, moment + timedelta(microseconds=1)) != (
        checkpoints.message(tenant, 7, digest, moment)
    )
    assert checkpoints.sign(KEY.secret, b"body") == hmac.new(KEY.secret, b"body", "sha256").digest()


async def test_sealing_covers_every_chain_including_the_platform_one(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (tenant_id, action, entity_type) "
                "VALUES (NULL, 'platform.test', 'tenant')"
            )
        )
    monkeypatch.setattr(checkpoints, "current_key", lambda *_: KEY)

    result = await checkpoints.seal_all_chains()
    assert result["not_configured"] == 0
    assert result["sealed"] >= 2, result

    async with system_session(reason="test platform checkpoint") as db:
        platform = await checkpoints.checkpoints_for(db, None, limit=1)
    assert platform
    assert checkpoints.signature_valid(platform[0], KEYS)


async def test_sealing_is_skipped_without_a_key(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checkpoints, "current_key", lambda *_: None)
    result = await checkpoints.seal_all_chains()
    assert result == {"sealed": 0, "skipped": 0, "refused": 0, "not_configured": 1}


async def test_a_run_is_executed_and_recorded(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 5)
    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        run = await runs.start(db, tenant_id=tenant_id, requested_by=None)

    result = await runs.execute(run.id)
    assert result == {"passed": 1, "failed": 0}

    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        stored = await runs.get(db, run.id)
    assert stored.status == "passed"
    assert stored.checked_count == 5
    assert stored.finished_at is not None


async def test_a_failed_run_records_the_first_bad_row(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant_id, 4)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text("UPDATE audit_events SET action = 'x' WHERE id = :id"), {"id": ids[1]}
        )
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )
    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        run = await runs.start(db, tenant_id=tenant_id, requested_by=None, mode="independent")

    assert await runs.execute(run.id) == {"passed": 0, "failed": 1}
    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        stored = await runs.get(db, run.id)
    assert stored.status == "failed"
    assert stored.first_bad_seq == 2
    assert stored.failure_reason is not None


async def test_the_range_is_validated_against_the_chain(owner_engine: AsyncEngine) -> None:
    from app.core.errors import ValidationFailed

    tenant_id = await _tenant(owner_engine)
    empty = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 3)

    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        with pytest.raises(ValidationFailed, match="before from_seq"):
            await runs.start(db, tenant_id=tenant_id, requested_by=None, from_seq=3, to_seq=2)
        with pytest.raises(ValidationFailed, match="past the head"):
            await runs.start(db, tenant_id=tenant_id, requested_by=None, to_seq=99)
        with pytest.raises(ValidationFailed, match="mode"):
            await runs.start(db, tenant_id=tenant_id, requested_by=None, mode="sql")  # type: ignore[arg-type]
    async with system_session(reason="test run") as db:
        await set_tenant(db, empty)
        with pytest.raises(ValidationFailed, match="no audit events"):
            await runs.start(db, tenant_id=empty, requested_by=None)


async def test_only_one_run_in_flight_per_tenant(owner_engine: AsyncEngine) -> None:
    from sqlalchemy.exc import IntegrityError

    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 3)

    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        await runs.start(db, tenant_id=tenant_id, requested_by=None)
        with pytest.raises(IntegrityError):
            await runs.start(db, tenant_id=tenant_id, requested_by=None)
        await db.rollback()


async def test_a_run_can_be_abandoned(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 3)
    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        run = await runs.start(db, tenant_id=tenant_id, requested_by=None)
        await runs.abandon(db, run)

    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        remaining = (
            await db.execute(
                text("SELECT count(*) FROM audit_chain_verifications WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert remaining == 0


async def test_runs_are_retained_for_a_window(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 2)
    async with system_session(reason="test run") as db:
        await set_tenant(db, tenant_id)
        old = AuditChainVerification(
            tenant_id=tenant_id,
            from_seq=1,
            to_seq=2,
            mode="db",
            status="passed",
            started_at=datetime.now(UTC) - timedelta(days=400),
            finished_at=datetime.now(UTC) - timedelta(days=400),
        )
        fresh = AuditChainVerification(
            tenant_id=tenant_id, from_seq=1, to_seq=2, mode="db", status="passed"
        )
        db.add_all([old, fresh])
        await db.flush()
        old_id, fresh_id = old.id, fresh.id

    assert await runs.purge(older_than_days=90) >= 1

    async with system_session(reason="test retention") as db:
        await set_tenant(db, tenant_id)
        left = {
            row[0]
            for row in (
                await db.execute(
                    text("SELECT id FROM audit_chain_verifications WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            )
        }
    assert old_id not in left
    assert fresh_id in left


async def test_the_sweep_skips_a_chain_with_a_run_in_flight(
    owner_engine: AsyncEngine,
) -> None:
    """A stuck pending run must not break the sweep for every other tenant."""
    blocked = await _tenant(owner_engine)
    other = await _tenant(owner_engine)
    await _events(owner_engine, blocked, 2)
    await _events(owner_engine, other, 2)
    async with system_session(reason="test run") as db:
        await set_tenant(db, blocked)
        await runs.start(db, tenant_id=blocked, requested_by=None)

    result = await runs.sweep()
    assert result["skipped"] >= 1
    assert result["platform_passed"] == 1

    async with system_session(reason="test sweep") as db:
        statuses = (
            (
                await db.execute(
                    text(
                        "SELECT status FROM audit_chain_verifications "
                        "WHERE tenant_id = :t ORDER BY started_at"
                    ),
                    {"t": other},
                )
            )
            .scalars()
            .all()
        )
    assert list(statuses) == ["passed"]


async def test_the_sweep_verifies_each_tenant_and_the_platform_chain(
    owner_engine: AsyncEngine,
) -> None:
    first = await _tenant(owner_engine)
    second = await _tenant(owner_engine)
    await _events(owner_engine, first, 3)
    await _events(owner_engine, second, 2)

    result = await runs.sweep()
    # `sweep` covers every tenant in the database, including chains other tests
    # deliberately broke, so only this test's own tenants are asserted on.
    assert result["passed"] >= 2
    assert result["platform_passed"] == 1

    async with system_session(reason="test sweep") as db:
        statuses = (
            await db.execute(
                text(
                    "SELECT status, count(*) FROM audit_chain_verifications "
                    "WHERE tenant_id = ANY(:ids) GROUP BY status ORDER BY status"
                ),
                {"ids": [first, second]},
            )
        ).all()
    assert statuses == [("passed", 2)], statuses


async def test_a_sweep_that_finds_a_break_marks_the_run_failed(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant_id, 4)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text("UPDATE audit_events SET after = '{\"x\": 1}' WHERE id = :id"), {"id": ids[1]}
        )
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )

    result = await runs.sweep(mode="independent")
    assert result["failed"] >= 1

    async with system_session(reason="test sweep") as db:
        stored = (
            await db.execute(
                text(
                    "SELECT first_bad_seq FROM audit_chain_verifications "
                    "WHERE tenant_id = :t AND status = 'failed'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert stored == 2


async def test_the_sweep_is_incremental_after_a_pass(owner_engine: AsyncEngine) -> None:
    from app.core.config import get_settings

    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 3)
    await runs.sweep()

    await runs.sweep()
    async with system_session(reason="test sweep") as db:
        from_seq = (
            await db.execute(
                text(
                    "SELECT from_seq FROM audit_chain_verifications WHERE tenant_id = :t "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    if datetime.now(UTC).weekday() == 0:
        assert from_seq == 1, "Monday verifies from the first event"
    else:
        assert from_seq == 4, "otherwise it resumes after the last passing run"
    assert get_settings().audit_verify_batch_size > 0


async def test_verification_still_passes_with_the_batch_setting_small(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    await _events(owner_engine, tenant_id, 5)
    async with system_session(reason="test verification") as db:
        await set_tenant(db, tenant_id)
        report = await verification.verify_chain(db, tenant_id=tenant_id, batch_size=1)
    assert report.passed
    assert report.checked == 5
