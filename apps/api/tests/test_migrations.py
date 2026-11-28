"""Phase 1 data survives the Phase 2 migrations.

Runs the migrations on a database of its own: up to 0002, some Phase 1
rows written the way Phase 1 wrote them, then up to head.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import MAINTENANCE_URL, OWNER_URL, TEST_DB_NAME, _dsn

MIGRATION_DB = f"{TEST_DB_NAME}_migrations"
URL = OWNER_URL.set(database=MIGRATION_DB)


def _alembic(revision: str, *, down: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", URL.render_as_string(hide_password=False))
    cfg.attributes["configure_logger"] = False
    if down:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


async def _recreate() -> None:
    conn = await asyncpg.connect(_dsn(MAINTENANCE_URL))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{MIGRATION_DB}" OWNER "{OWNER_URL.username}"')
    finally:
        await conn.close()


async def _run(sql: str, *args: Any) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_dsn(URL))
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


PHASE1_ROWS = """
WITH t AS (INSERT INTO tenants (slug, name) VALUES ('mig-city', 'Migration City') RETURNING id),
u AS (INSERT INTO users (tenant_id, phone) SELECT id, '+918000000001' FROM t
      RETURNING id, tenant_id),
c AS (INSERT INTO categories (tenant_id, code, name_i18n, icon)
      SELECT id, 'pothole', '{"en": "Pothole"}', 'construction' FROM t RETURNING id, tenant_id),
i AS (INSERT INTO civic_issues (id, tenant_id, reference, category_id, status, location,
                                report_count, unique_reporter_count, severity, priority)
      SELECT v.id, c.tenant_id, v.ref, c.id, 'reported',
             ST_SetSRID(ST_MakePoint(77.6, 12.98), 4326),
             1, 1, v.severity, v.priority
      FROM c, (VALUES ($1::uuid, 'CP-26-000001', ' High ', 'urgent'),
                      ($2::uuid, 'CP-26-000002', NULL, 'LOW'),
                      ($3::uuid, 'CP-26-000003', 'bad', NULL)) AS v(id, ref, severity, priority)
      RETURNING id, tenant_id, category_id, reference)
INSERT INTO reports (tenant_id, reference, reporter_id, category_id, issue_id, status,
                     location, location_source)
SELECT i.tenant_id, replace(i.reference, 'CP', 'R'), u.id, i.category_id, i.id, 'accepted',
       ST_SetSRID(ST_MakePoint(77.6, 12.98), 4326), 'gps'
FROM i, u
"""


@pytest.fixture(scope="module")
def migrated() -> dict[str, uuid.UUID]:
    ids = {
        "severity_override": uuid.uuid4(),
        "priority_override": uuid.uuid4(),
        "plain": uuid.uuid4(),
    }
    asyncio.run(_recreate())
    _alembic("0002")
    asyncio.run(_run(PHASE1_ROWS, *ids.values()))
    _alembic("head")
    return ids


def test_phase1_reports_become_new_issue_with_citizen_categories(
    migrated: dict[str, uuid.UUID],
) -> None:
    rows = asyncio.run(
        _run("SELECT matching_status, category_source, issue_id IS NOT NULL AS linked FROM reports")
    )
    assert len(rows) == 3
    assert {(r["matching_status"], r["category_source"], r["linked"]) for r in rows} == {
        ("new_issue", "citizen", True)
    }


def test_phase1_severity_and_priority_strings_carry_over_as_overrides(
    migrated: dict[str, uuid.UUID],
) -> None:
    rows = {
        r["id"]: r
        for r in asyncio.run(
            _run(
                "SELECT id, severity, severity_source, severity_reason, priority_override_band, "
                "priority_override_reason, priority_score, priority_computed_at FROM civic_issues"
            )
        )
    }
    kept = rows[migrated["severity_override"]]
    assert (kept["severity"], kept["severity_source"]) == ("high", "override")
    assert kept["severity_reason"].startswith("Set before")
    assert kept["priority_override_band"] is None  # "urgent" isn't a band

    band = rows[migrated["priority_override"]]
    assert (band["severity"], band["severity_source"]) == ("medium", "rule")
    assert band["priority_override_band"] == "low"
    assert band["priority_override_reason"].startswith("Set before")

    plain = rows[migrated["plain"]]
    assert (plain["severity"], plain["severity_source"], plain["severity_reason"]) == (
        "medium",
        "rule",
        None,
    )
    # Computed by the application after the migration, never in SQL.
    assert all(
        r["priority_score"] is None and r["priority_computed_at"] is None for r in rows.values()
    )


def test_phase2_migrations_downgrade_and_upgrade_again(migrated: dict[str, uuid.UUID]) -> None:
    _alembic("0002", down=True)
    rows = asyncio.run(_run("SELECT severity, priority FROM civic_issues ORDER BY reference"))
    assert [(r["severity"], r["priority"]) for r in rows] == [
        ("high", None),
        ("medium", "low"),
        ("medium", None),
    ]
    _alembic("head")
    count = asyncio.run(
        _run("SELECT count(*) AS n FROM reports WHERE matching_status = 'new_issue'")
    )
    assert count[0]["n"] == 3


def test_the_old_visual_floor_default_follows_the_model_again(
    migrated: dict[str, uuid.UUID],
) -> None:
    """0006: a stored 0.80 was the old default written out, so it becomes
    null (the model's floor); a value someone chose is kept."""
    _alembic("0005", down=True)
    asyncio.run(
        _run(
            """
            WITH t AS (INSERT INTO tenants (slug, name) VALUES ('mig-city-2', 'Second City')
                       RETURNING id)
            INSERT INTO tenant_configs (tenant_id, key, value)
            SELECT id, 'matching', $1::jsonb FROM tenants WHERE slug = 'mig-city'
            UNION ALL
            SELECT id, 'matching', $2::jsonb FROM t
            """,
            '{"thresholds": {"auto": 0.85, "review": 0.6, "visual_min": 0.8}}',
            '{"thresholds": {"auto": 0.85, "review": 0.6, "visual_min": 0.88}}',
        )
    )
    _alembic("head")
    rows = asyncio.run(
        _run(
            "SELECT t.slug, c.value #> '{thresholds,visual_min}' AS floor "
            "FROM tenant_configs c JOIN tenants t ON t.id = c.tenant_id ORDER BY t.slug"
        )
    )
    assert [(r["slug"], r["floor"]) for r in rows] == [("mig-city", "null"), ("mig-city-2", "0.88")]

    _alembic("0005", down=True)
    rows = asyncio.run(
        _run("SELECT value #> '{thresholds,visual_min}' AS floor FROM tenant_configs")
    )
    assert sorted(r["floor"] for r in rows) == ["0.8", "0.88"]
    _alembic("head")


# --- 0017 / 0018: the audit hash chain --------------------------------------

# The question the verifier asks in `db` mode, asked once over every row.
HASH_VIOLATIONS = """
SELECT count(*) AS n
  FROM audit_events e
 WHERE e.hash <> audit_hash_v1(e.prev_hash, e.tenant_id, e.chain_seq, e.occurred_at,
                               e.actor_id, e.action, e.entity_type, e.entity_id,
                               e.before, e.after, e.request_id, e.ip, e.user_agent)
"""

LINK_VIOLATIONS = """
SELECT count(*) AS n
  FROM (SELECT prev_hash,
               lag(hash) OVER (PARTITION BY tenant_id ORDER BY chain_seq) AS prior
          FROM audit_events) linked
 WHERE prior IS NOT NULL AND prev_hash <> prior
"""


def _unbackfilled_rows() -> dict[str, Any]:
    """Rows the way a pre-0017 deployment wrote them: no chain columns at all."""
    tenants = asyncio.run(
        _run(
            "INSERT INTO tenants (slug, name) VALUES "
            "('chain-a', 'Chain A'), ('chain-b', 'Chain B') RETURNING id, slug"
        )
    )
    ids = {row["slug"]: row["id"] for row in tenants}
    # Two chains, interleaved, with the optional columns sometimes NULL -- the
    # cases the framing has to tell apart.
    plan: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = [
        ("chain-a", "issue.status_changed", {"n": 1}, None),
        ("chain-b", "auth.login", None, {"ok": True}),
        ("chain-a", "issue.assigned", None, None),
        ("chain-a", "report.filed", {"text": "pothole"}, {"n": 2}),
    ]
    audit_ids: list[int] = []
    for slug, action, before, after in plan:
        inserted = asyncio.run(
            _run(
                "INSERT INTO audit_events (tenant_id, action, entity_type, entity_id, before, "
                "after, request_id, ip, user_agent) "
                "VALUES ($1, $2, 'test', 'ent-1', $3::jsonb, $4::jsonb, 'req-1', '10.0.0.1', $5) "
                "RETURNING id",
                ids[slug],
                action,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
                "a-user-agent-string",
            )
        )
        audit_ids.append(inserted[0]["id"])
    return {"tenants": ids, "events": audit_ids}


@pytest.fixture(scope="module")
def chained() -> dict[str, Any]:
    """A database stopped at 0016 with unbackfilled rows, then brought to head."""
    asyncio.run(_recreate())
    _alembic("0016")
    seeded = _unbackfilled_rows()
    _alembic("head")
    return seeded


def test_the_backfill_chains_every_row_written_before_0017(chained: dict[str, Any]) -> None:
    rows = asyncio.run(
        _run(
            "SELECT tenant_id, chain_seq, prev_hash, hash FROM audit_events "
            "ORDER BY tenant_id, chain_seq"
        )
    )
    assert len(rows) == len(chained["events"])
    assert all(len(bytes(row["prev_hash"])) == 32 for row in rows)
    assert all(len(bytes(row["hash"])) == 32 for row in rows)

    # One chain per tenant, contiguous from 1, and each starts at genesis.
    by_tenant: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        by_tenant.setdefault(row["tenant_id"], []).append(row)
    assert len(by_tenant) == 2
    for chain in by_tenant.values():
        assert [row["chain_seq"] for row in chain] == list(range(1, len(chain) + 1))
        assert bytes(chain[0]["prev_hash"]) == bytes(32)


def test_the_backfill_leaves_a_chain_that_verifies(chained: dict[str, Any]) -> None:
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0
    assert asyncio.run(_run(LINK_VIOLATIONS))[0]["n"] == 0

    # And every head points exactly past the tail of its chain.
    heads = asyncio.run(
        _run(
            "SELECT h.tenant_id, h.next_seq, h.last_hash, "
            "       (SELECT max(chain_seq) FROM audit_events e "
            "         WHERE e.tenant_id = h.tenant_id) AS tail_seq, "
            "       (SELECT hash FROM audit_events e "
            "         WHERE e.tenant_id = h.tenant_id "
            "         ORDER BY chain_seq DESC LIMIT 1) AS tail_hash "
            "  FROM audit_chain_heads h WHERE h.tenant_id IS NOT NULL"
        )
    )
    assert len(heads) == 2
    assert all(row["next_seq"] == row["tail_seq"] + 1 for row in heads)
    assert all(bytes(row["last_hash"]) == bytes(row["tail_hash"]) for row in heads)
    # chain-a took three of the four rows, chain-b one.
    assert sorted(row["next_seq"] for row in heads) == [2, 4]


def test_the_backfill_preserves_the_rows_it_chains(chained: dict[str, Any]) -> None:
    rows = asyncio.run(
        _run(
            "SELECT id, action, entity_type, entity_id, before::text AS before, "
            "       after::text AS after, request_id, ip, user_agent "
            "  FROM audit_events ORDER BY id"
        )
    )
    assert [row["id"] for row in rows] == chained["events"]
    assert rows[0]["before"] == '{"n": 1}'
    assert rows[0]["after"] is None
    assert rows[1]["before"] is None
    assert rows[1]["after"] == '{"ok": true}'
    assert all(row["request_id"] == "req-1" and row["ip"] == "10.0.0.1" for row in rows)


def test_the_chain_columns_are_not_null_after_the_migration(chained: dict[str, Any]) -> None:
    rows = asyncio.run(
        _run(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            " WHERE table_name = 'audit_events' "
            "   AND column_name IN ('chain_seq', 'prev_hash', 'hash')"
        )
    )
    assert {row["column_name"]: row["is_nullable"] for row in rows} == {
        "chain_seq": "NO",
        "prev_hash": "NO",
        "hash": "NO",
    }


def test_0018_downgrades_and_upgrades_again_without_touching_the_chain(
    chained: dict[str, Any],
) -> None:
    """Its downgrade drops only the NOT NULLs: the chain is evidence once written."""
    _alembic("0017", down=True)
    nullable = asyncio.run(
        _run(
            "SELECT is_nullable FROM information_schema.columns "
            " WHERE table_name = 'audit_events' AND column_name = 'hash'"
        )
    )
    assert nullable[0]["is_nullable"] == "YES"
    assert asyncio.run(_run("SELECT count(*) AS n FROM audit_events"))[0]["n"] == 4
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0

    _alembic("head")
    back = asyncio.run(
        _run(
            "SELECT is_nullable FROM information_schema.columns "
            " WHERE table_name = 'audit_events' AND column_name = 'hash'"
        )
    )
    assert back[0]["is_nullable"] == "NO"
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0


def test_dropping_0017_and_rebuilding_it_chains_the_rows_again(
    chained: dict[str, Any],
) -> None:
    """The full round trip: columns and tables go, and 0018 backfills on the way back."""
    _alembic("0016", down=True)
    gone = asyncio.run(
        _run(
            "SELECT count(*) AS n FROM information_schema.columns "
            " WHERE table_name = 'audit_events' "
            "   AND column_name IN ('chain_seq', 'prev_hash', 'hash')"
        )
    )
    assert gone[0]["n"] == 0
    assert asyncio.run(_run("SELECT count(*) AS n FROM audit_events"))[0]["n"] == 4

    _alembic("head")
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0
    assert asyncio.run(_run(LINK_VIOLATIONS))[0]["n"] == 0
    rows = asyncio.run(
        _run("SELECT tenant_id, chain_seq FROM audit_events ORDER BY tenant_id, chain_seq")
    )
    assert all(row["chain_seq"] >= 1 for row in rows)


def test_the_backfill_refuses_a_chain_larger_than_its_limit(
    chained: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is the difference between a slow deploy and an outage."""
    _alembic("0017", down=True)
    monkeypatch.setenv("AUDIT_BACKFILL_MAX_ROWS", "2")
    with pytest.raises(Exception, match="refuses more than 2"):
        _alembic("head")

    # The failed migration rolled back, so the rows are still there.
    assert asyncio.run(_run("SELECT count(*) AS n FROM audit_events"))[0]["n"] == 4

    monkeypatch.delenv("AUDIT_BACKFILL_MAX_ROWS")
    _alembic("head")
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0


def test_a_backfilled_chain_keeps_appending_from_its_own_head(
    chained: dict[str, Any],
) -> None:
    """Without a head row, the next audited write collides on chain_seq 1.

    This is the failure the head upsert in 0018 prevents, so it is worth an
    explicit test rather than trusting the backfill's own self-check.
    """
    tenant = chained["tenants"]["chain-a"]
    rows = asyncio.run(
        _run(
            "SELECT chain_seq FROM audit_events WHERE tenant_id = $1 ORDER BY chain_seq",
            tenant,
        )
    )
    tail = len(rows)
    assert [row["chain_seq"] for row in rows] == list(range(1, tail + 1))

    asyncio.run(
        _run(
            "INSERT INTO audit_events (tenant_id, action, entity_type) "
            "VALUES ($1, 'post.backfill', 'test')",
            tenant,
        )
    )

    after = asyncio.run(
        _run(
            "SELECT chain_seq FROM audit_events WHERE tenant_id = $1 ORDER BY chain_seq",
            tenant,
        )
    )
    assert [row["chain_seq"] for row in after] == list(range(1, tail + 2))
    assert asyncio.run(_run(HASH_VIOLATIONS))[0]["n"] == 0
    assert asyncio.run(_run(LINK_VIOLATIONS))[0]["n"] == 0
