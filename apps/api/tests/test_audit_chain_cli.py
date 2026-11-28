"""The operator CLI: what it prints, and the exit code a cron line depends on.

The exit code is the contract (`0` passed, `1` broken, `2` usage), so these tests
assert on it rather than on internals. The output matters too, in one direction
only: a failure has to name the sequence an operator will go and look at, and it
must never carry the row's payload.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.tenancy import set_tenant, system_session
from app.domains.audit import checkpoints
from app.domains.audit.checkpoints import AnchorKey
from scripts.verify_audit_chain import EXIT_BROKEN, EXIT_OK, EXIT_USAGE, build_parser, run
from tests.factories import TenantRow, create_tenant

KEY = AnchorKey(key_id="k1", secret=b"a-test-anchor-key-that-is-long-enough")


async def _tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


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


async def _cli(*argv: str) -> int:
    return await run(build_parser().parse_args([*argv]))


async def _tamper(owner_engine: AsyncEngine, statement: str, params: dict[str, Any]) -> None:
    """A write the append-only trigger would refuse, as a DB-level attacker makes."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(text(statement), params)
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )


async def test_a_clean_chain_passes_with_exit_zero(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await _tenant(owner_engine)
    await _events(owner_engine, tenant.id, 3)

    assert await _cli("--tenant", tenant.slug) == EXIT_OK

    out = capsys.readouterr().out
    assert "PASS" in out
    assert tenant.slug in out
    assert "1 chains, 3 events" in out


async def test_a_rewritten_payload_fails_at_its_own_sequence(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant.id, 3)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET before = CAST(:before AS jsonb) WHERE id = :id",
        {"before": json.dumps({"n": 999}), "id": ids[1]},
    )

    assert await _cli("--tenant", tenant.slug) == EXIT_BROKEN

    out = capsys.readouterr().out
    assert "FAIL at chain_seq 2" in out
    assert "reason: hash" in out
    assert "docs/runbooks/audit-chain-recovery.md" in out


async def test_a_deleted_row_is_reported_as_a_gap(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant.id, 4)
    await _tamper(owner_engine, "DELETE FROM audit_events WHERE id = :id", {"id": ids[1]})

    assert await _cli("--tenant", tenant.slug) == EXIT_BROKEN
    assert "reason: gap" in capsys.readouterr().out


async def test_the_payload_of_a_broken_row_is_never_printed(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """PRD §12.2: a failure names the row, not what the row contains."""
    tenant = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant.id, 2)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET before = CAST(:before AS jsonb) WHERE id = :id",
        {"before": json.dumps({"applicant": "PAN-1234-LEAKED"}), "id": ids[0]},
    )

    assert await _cli("--tenant", tenant.slug) == EXIT_BROKEN

    captured = capsys.readouterr()
    assert "PAN-1234-LEAKED" not in captured.out
    assert "PAN-1234-LEAKED" not in captured.err


async def test_both_modes_agree_on_a_broken_chain(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant.id, 3)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET before = CAST(:before AS jsonb) WHERE id = :id",
        {"before": json.dumps({"n": 1}), "id": ids[1]},
    )

    assert await _cli("--tenant", tenant.slug, "--mode", "db") == EXIT_BROKEN
    assert await _cli("--tenant", tenant.slug, "--mode", "independent") == EXIT_BROKEN


async def test_an_unknown_slug_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await _cli("--tenant", "no-such-city") == EXIT_USAGE
    assert "no tenant with slug" in capsys.readouterr().err


async def test_a_bad_range_is_a_usage_error() -> None:
    assert await _cli("--tenant", "irrelevant", "--from-seq", "0") == EXIT_USAGE
    assert await _cli("--tenant", "irrelevant", "--from-seq", "9", "--to-seq", "4") == EXIT_USAGE


async def test_the_json_output_is_one_object_per_chain_then_a_summary(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await _tenant(owner_engine)
    await _events(owner_engine, tenant.id, 2)

    assert await _cli("--tenant", tenant.slug, "--json") == EXIT_OK

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    *records, summary = lines
    assert summary["summary"]["chains"] == 1
    assert summary["summary"]["passed"] == 1
    assert summary["summary"]["ok"] is True

    [record] = records
    assert record["label"] == tenant.slug
    assert record["scope"] == "tenant"
    assert record["ok"] is True
    assert record["checked"] == 2
    assert record["mode"] == "independent"


async def test_the_platform_chain_is_verifiable(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the CLI can do this: it needs the RLS bypass."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (tenant_id, action, entity_type) "
                "VALUES (NULL, 'test.platform', 'test')"
            )
        )

    assert await _cli("--platform") == EXIT_OK

    out = capsys.readouterr().out
    assert "platform" in out
    assert "PASS" in out


async def test_a_deleted_tail_is_caught_against_the_checkpoint(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rows left behind still verify; the signature is what sees the loss."""
    settings = get_settings()
    monkeypatch.setattr(settings, "audit_anchor_key", SecretStr(KEY.secret.decode()))
    monkeypatch.setattr(settings, "audit_anchor_key_id", KEY.key_id)

    tenant = await _tenant(owner_engine)
    ids = await _events(owner_engine, tenant.id, 4)
    async with system_session(reason="test sealing") as db:
        await set_tenant(db, tenant.id)
        assert await checkpoints.seal(db, tenant_id=tenant.id, key=KEY) is not None

    # Drop the tail below the sealed sequence.
    await _tamper(owner_engine, "DELETE FROM audit_events WHERE id = :id", {"id": ids[3]})

    # Without --checkpoints the remaining prefix is internally consistent.
    assert await _cli("--tenant", tenant.slug, "--to-seq", "3") == EXIT_OK

    assert await _cli("--tenant", tenant.slug, "--checkpoints") == EXIT_BROKEN
    out = capsys.readouterr().out
    assert "FAIL at checkpoint" in out
    assert "is gone, but a checkpoint signed it" in out


async def test_a_failed_chain_stops_the_walk_by_default(
    owner_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """--fail-fast is the default so a broken chain is not buried in the output."""
    broken = await _tenant(owner_engine)
    ids = await _events(owner_engine, broken.id, 2)
    await _tamper(
        owner_engine,
        "UPDATE audit_events SET before = CAST(:before AS jsonb) WHERE id = :id",
        {"before": json.dumps({"n": 1}), "id": ids[0]},
    )
    healthy = await _tenant(owner_engine)
    await _events(owner_engine, healthy.id, 1)

    await _cli("--all-tenants")
    out = capsys.readouterr().out
    # The platform row is always last, so it is missing when the walk stopped.
    assert "platform" not in out

    await _cli("--all-tenants", "--no-fail-fast")
    assert "platform" in capsys.readouterr().out
