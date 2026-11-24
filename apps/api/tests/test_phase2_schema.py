"""The Phase 2 tables at the database level: tenant isolation, privileges,
and the constraints that keep matching state consistent."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.db import get_session_factory
from app.core.tenancy import set_tenant
from tests.factories import (
    IssueRow,
    TenantRow,
    create_category,
    create_issue,
    create_tenant,
    create_user,
)

TENANT_TABLES = (
    "media_embeddings",
    "classifications",
    "match_decisions",
    "review_tasks",
    "issue_relations",
    "tenant_configs",
    "places_of_interest",
)


@dataclass
class Seeded:
    tenant: TenantRow
    user_id: uuid.UUID
    first: IssueRow
    second: IssueRow


async def _seed(conn: AsyncConnection) -> Seeded:
    tenant = await create_tenant(conn)
    citizen = await create_user(conn, tenant.id, "citizen")
    category = await create_category(conn, tenant.id)
    first = await create_issue(conn, tenant.id, category_id=category, reporter_id=citizen.id)
    second = await create_issue(conn, tenant.id, category_id=category, reporter_id=citizen.id)
    params = {"t": tenant.id, "u": citizen.id}
    await conn.execute(
        text(
            "INSERT INTO model_registry (id, task, name, version) "
            "VALUES ('schema-test@1', 'embedding', 'Schema test', '1') ON CONFLICT DO NOTHING"
        )
    )
    media_id = (
        await conn.execute(
            text(
                "INSERT INTO media_assets (tenant_id, owner_id, purpose, status, content_type, "
                "declared_size_bytes, checksum_sha256, storage_key, upload_expires_at) VALUES "
                "(:t, :u, 'report_evidence', 'processing', 'image/jpeg', 10, :sum, :key, now()) "
                "RETURNING id"
            ),
            {**params, "sum": "0" * 64, "key": f"test/{uuid.uuid4()}"},
        )
    ).scalar_one()
    vector = json.dumps([1.0] + [0.0] * 511)
    await conn.execute(
        text(
            "INSERT INTO media_embeddings (tenant_id, media_id, model_id, embedding, phash) "
            "VALUES (:t, :m, 'schema-test@1', CAST(:v AS vector), -5)"
        ),
        {**params, "m": media_id, "v": vector},
    )
    await conn.execute(
        text(
            "INSERT INTO classifications (tenant_id, requested_by, media_ids, status) "
            "VALUES (:t, :u, ARRAY[CAST(:m AS uuid)], 'pending')"
        ),
        {**params, "m": media_id},
    )
    await conn.execute(
        text(
            "INSERT INTO match_decisions (tenant_id, report_id, candidate_issue_id, rank, score, "
            "signals, decision) VALUES (:t, :r, :i, 1, 0.5, '{}'::jsonb, 'rejected_candidate')"
        ),
        {**params, "r": second.report_id, "i": first.id},
    )
    await conn.execute(
        text(
            "INSERT INTO review_tasks (tenant_id, report_id, status, resolution, resolved_at) "
            "VALUES (:t, :r, 'resolved', 'new_issue', now())"
        ),
        {**params, "r": second.report_id},
    )
    low, high = sorted([first.id, second.id])
    await conn.execute(
        text(
            "INSERT INTO issue_relations (tenant_id, issue_id, related_issue_id) "
            "VALUES (:t, :a, :b)"
        ),
        {**params, "a": low, "b": high},
    )
    await conn.execute(
        text("INSERT INTO tenant_configs (tenant_id, key, value) VALUES (:t, 'matching', '{}')"),
        params,
    )
    await conn.execute(
        text(
            "INSERT INTO places_of_interest (tenant_id, kind, name, geom) "
            "VALUES (:t, 'school', 'Test School', ST_SetSRID(ST_MakePoint(77.6, 12.98), 4326))"
        ),
        params,
    )
    return Seeded(tenant, citizen.id, first, second)


@pytest.fixture
async def pair(owner_engine: AsyncEngine) -> tuple[Seeded, Seeded]:
    async with owner_engine.begin() as conn:
        return await _seed(conn), await _seed(conn)


async def test_each_tenant_sees_only_its_own_phase2_rows(pair: tuple[Seeded, Seeded]) -> None:
    a, _ = pair
    async with get_session_factory()() as session:
        for table in TENANT_TABLES:
            rows = await session.execute(text(f"SELECT DISTINCT tenant_id FROM {table}"))  # noqa: S608
            assert rows.all() == [], table
    async with get_session_factory()() as session:
        await set_tenant(session, a.tenant.id)
        for table in TENANT_TABLES:
            rows = await session.execute(text(f"SELECT DISTINCT tenant_id FROM {table}"))  # noqa: S608
            assert {row[0] for row in rows} == {a.tenant.id}, table


async def test_phase2_writes_into_another_tenant_are_rejected(
    pair: tuple[Seeded, Seeded],
) -> None:
    a, b = pair
    async with get_session_factory()() as session:
        await set_tenant(session, a.tenant.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (tenant_id, key, value) "
                    "VALUES (:t, 'priority', '{}')"
                ),
                {"t": b.tenant.id},
            )


async def test_the_model_registry_is_shared_by_every_tenant(pair: tuple[Seeded, Seeded]) -> None:
    a, b = pair
    for tenant in (a.tenant, b.tenant):
        async with get_session_factory()() as session:
            await set_tenant(session, tenant.id)
            found = await session.scalar(
                text("SELECT count(*) FROM model_registry WHERE id = 'schema-test@1'")
            )
            assert found == 1


async def test_app_role_privileges_on_phase2_tables(owner_engine: AsyncEngine) -> None:
    checks = {
        ("match_decisions", "UPDATE"): True,
        ("match_decisions", "DELETE"): False,
        ("review_tasks", "DELETE"): False,
        ("issue_relations", "DELETE"): True,
        ("issue_relations", "UPDATE"): False,
        ("media_embeddings", "UPDATE"): False,
        ("classifications", "DELETE"): False,
        ("model_registry", "DELETE"): False,
        ("tenant_configs", "DELETE"): False,
    }
    async with owner_engine.connect() as conn:
        for (table, privilege), expected in checks.items():
            granted = await conn.scalar(
                text("SELECT has_table_privilege('civicpulse_app', :t, :p)"),
                {"t": table, "p": privilege},
            )
            assert granted is expected, (table, privilege)


async def test_a_report_has_an_issue_exactly_when_matching_placed_it(
    owner_engine: AsyncEngine, pair: tuple[Seeded, Seeded]
) -> None:
    a, _ = pair
    for status, issue in (("pending", a.first.id), ("review", a.first.id), ("linked", None)):
        async with owner_engine.connect() as conn:
            with pytest.raises(IntegrityError, match="ck_reports_issue_matches_status"):
                await conn.execute(
                    text("UPDATE reports SET matching_status = :s, issue_id = :i WHERE id = :r"),
                    {"s": status, "i": issue, "r": a.second.report_id},
                )


async def test_one_open_review_task_per_report(
    owner_engine: AsyncEngine, pair: tuple[Seeded, Seeded]
) -> None:
    a, _ = pair
    insert = text("INSERT INTO review_tasks (tenant_id, report_id, status) VALUES (:t, :r, 'open')")
    async with owner_engine.begin() as conn:
        await conn.execute(insert, {"t": a.tenant.id, "r": a.first.report_id})
    async with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError, match="uq_review_tasks_open_report"):
            await conn.execute(insert, {"t": a.tenant.id, "r": a.first.report_id})


async def test_relations_are_stored_once_per_pair(
    owner_engine: AsyncEngine, pair: tuple[Seeded, Seeded]
) -> None:
    a, _ = pair
    low, high = sorted([a.first.id, a.second.id])
    async with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError, match="ck_issue_relations_ordered_pair"):
            await conn.execute(
                text(
                    "INSERT INTO issue_relations (tenant_id, issue_id, related_issue_id) "
                    "VALUES (:t, :a, :b)"
                ),
                {"t": a.tenant.id, "a": high, "b": low},
            )


async def test_an_issue_cannot_be_merged_into_itself(
    owner_engine: AsyncEngine, pair: tuple[Seeded, Seeded]
) -> None:
    a, b = pair
    async with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError, match="ck_civic_issues_not_merged_into_self"):
            await conn.execute(
                text("UPDATE civic_issues SET merged_into_id = id WHERE id = :i"), {"i": a.first.id}
            )
    async with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError, match="fk_civic_issues_tenant_merged_into"):
            await conn.execute(
                text("UPDATE civic_issues SET merged_into_id = :o WHERE id = :i"),
                {"i": a.first.id, "o": b.first.id},
            )


async def test_embeddings_have_a_cosine_hnsw_index(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        definition = await conn.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_media_embeddings_embedding_hnsw'"
            )
        )
    assert definition is not None
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
