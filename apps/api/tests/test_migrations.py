"""Phase 1 data survives the Phase 2 migrations.

Runs the migrations on a database of its own: up to 0002, some Phase 1
rows written the way Phase 1 wrote them, then up to head.
"""

from __future__ import annotations

import asyncio
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
