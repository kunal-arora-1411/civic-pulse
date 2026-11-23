"""Migration 0002 at the database level: tenant isolation on every new
table, privileges for the app role, and the search-document triggers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.core.db import get_session_factory
from app.core.tenancy import set_tenant
from tests.factories import TenantRow, create_category, create_issue, create_tenant, create_user

NEW_TABLES = (
    "categories",
    "status_transitions",
    "reference_counters",
    "media_assets",
    "civic_issues",
    "reports",
    "issue_events",
)


@dataclass
class Seeded:
    tenant: TenantRow
    category_id: uuid.UUID
    issue_id: uuid.UUID


async def _media(conn: AsyncConnection, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "INSERT INTO media_assets (tenant_id, owner_id, purpose, status, content_type, "
            "declared_size_bytes, checksum_sha256, storage_key, upload_expires_at) VALUES "
            "(:t, :o, 'report_evidence', 'pending', 'image/jpeg', 10, :sum, :key, now())"
        ),
        {"t": tenant_id, "o": owner_id, "sum": "0" * 64, "key": f"test/{uuid.uuid4()}"},
    )


async def _seed_tenant(conn: AsyncConnection) -> Seeded:
    tenant = await create_tenant(conn)
    citizen = await create_user(conn, tenant.id, "citizen")
    category_id = await create_category(conn, tenant.id)
    issue = await create_issue(conn, tenant.id, category_id=category_id, reporter_id=citizen.id)
    await _media(conn, tenant.id, citizen.id)
    await conn.execute(
        text(
            "INSERT INTO status_transitions (tenant_id, from_status, to_status, allowed_roles) "
            "VALUES (:t, 'reported', 'under_review', ARRAY['operator']::varchar[])"
        ),
        {"t": tenant.id},
    )
    await conn.execute(
        text(
            "INSERT INTO reference_counters (tenant_id, kind, year, last_value) "
            "VALUES (:t, 'issue', 26, 1)"
        ),
        {"t": tenant.id},
    )
    return Seeded(tenant, category_id, issue.id)


@pytest.fixture
async def pair(owner_engine: AsyncEngine) -> tuple[Seeded, Seeded]:
    async with owner_engine.begin() as conn:
        return await _seed_tenant(conn), await _seed_tenant(conn)


def _session() -> AsyncSession:
    return get_session_factory()()


async def _tenants_visible(session: AsyncSession, table: str) -> set[uuid.UUID]:
    rows = await session.execute(text(f"SELECT DISTINCT tenant_id FROM {table}"))  # noqa: S608
    return {row[0] for row in rows}


async def test_no_tenant_sees_no_rows_in_new_tables(pair: tuple[Seeded, Seeded]) -> None:
    async with _session() as session:
        for table in NEW_TABLES:
            assert await _tenants_visible(session, table) == set(), table


async def test_each_tenant_sees_only_its_own_rows(pair: tuple[Seeded, Seeded]) -> None:
    a, b = pair
    async with _session() as session:
        await set_tenant(session, a.tenant.id)
        for table in NEW_TABLES:
            assert await _tenants_visible(session, table) == {a.tenant.id}, table
        # Asking for B's rows by id finds nothing.
        found = await session.scalar(
            text("SELECT count(*) FROM civic_issues WHERE id = :id"), {"id": b.issue_id}
        )
        assert found == 0


async def test_writes_into_another_tenant_are_rejected(pair: tuple[Seeded, Seeded]) -> None:
    a, b = pair
    async with _session() as session:
        await set_tenant(session, a.tenant.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO categories (tenant_id, code, name_i18n, icon) "
                    "VALUES (:t, 'sneaky', '{}'::jsonb, 'x')"
                ),
                {"t": b.tenant.id},
            )
    async with _session() as session:
        await set_tenant(session, a.tenant.id)
        result = await session.execute(
            text("UPDATE civic_issues SET status = 'rejected' WHERE id = :id"), {"id": b.issue_id}
        )
        assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_composite_keys_stop_cross_tenant_links(
    owner_engine: AsyncEngine, pair: tuple[Seeded, Seeded]
) -> None:
    # Even the owner, who bypasses RLS, can't point A's report at B's category.
    a, b = pair
    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="fk_reports_tenant_category"):
            await conn.execute(
                text("UPDATE reports SET category_id = :c WHERE issue_id = :i"),
                {"c": b.category_id, "i": a.issue_id},
            )


async def test_app_role_privileges_on_history_tables(owner_engine: AsyncEngine) -> None:
    checks = {
        ("issue_events", "INSERT"): True,
        ("issue_events", "UPDATE"): False,
        ("issue_events", "DELETE"): False,
        ("reports", "DELETE"): False,
        ("civic_issues", "DELETE"): False,
        ("categories", "DELETE"): False,
        ("media_assets", "DELETE"): True,
    }
    async with owner_engine.connect() as conn:
        for (table, privilege), expected in checks.items():
            granted = await conn.scalar(
                text("SELECT has_table_privilege('civicpulse_app', :t, :p)"),
                {"t": table, "p": privilege},
            )
            assert granted is expected, (table, privilege)


async def test_search_document_covers_references_address_and_hindi(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        citizen = await create_user(conn, tenant.id, "citizen")
        category_id = await create_category(conn, tenant.id)
        issue = await create_issue(
            conn,
            tenant.id,
            category_id=category_id,
            reporter_id=citizen.id,
            description="बस स्टॉप के पास बड़ा गड्ढा है",
            address_text="MG Road, Shivajinagar",
        )

    async def matches(query: str) -> bool:
        async with owner_engine.connect() as conn:
            return bool(
                await conn.scalar(
                    text(
                        "SELECT search_document @@ plainto_tsquery('simple', :q) "
                        "FROM civic_issues WHERE id = :id"
                    ),
                    {"q": query, "id": issue.id},
                )
            )

    assert await matches("गड्ढा")
    assert await matches("shivajinagar")
    assert await matches(issue.reference)
    assert await matches(issue.report_reference)
    assert not await matches("streetlight")

    # Editing the report's description re-indexes its issue.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE reports SET description = 'broken streetlight' WHERE id = :id"),
            {"id": issue.report_id},
        )
    assert await matches("streetlight")
    assert not await matches("गड्ढा")
