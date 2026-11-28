"""The hash chain over `audit_events`: how it is built, and that it cannot be
skipped.

The framing itself (the bytes that are hashed) and its Python mirror are
covered by test_audit_chain_framing.py; tamper detection by
test_audit_chain_tampering.py. This file is about construction: sequence,
linkage, atomicity and concurrency.
"""

from __future__ import annotations

import asyncio
import itertools
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_session_factory
from app.core.tenancy import set_tenant
from tests.factories import create_tenant


async def _tenant(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        return (await create_tenant(conn)).id


async def _append(owner_engine: AsyncEngine, tenant_id: uuid.UUID, action: str) -> int:
    """Write one audit row the way `record()` does, minus the ORM."""
    async with owner_engine.begin() as conn:
        return (
            await conn.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type) "
                    "VALUES (:tenant, :action, 'test') RETURNING id"
                ),
                {"tenant": tenant_id, "action": action},
            )
        ).scalar_one()


async def _chain(owner_engine: AsyncEngine, tenant_id: uuid.UUID | None) -> list[tuple]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT chain_seq, prev_hash, hash FROM audit_events "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant ORDER BY chain_seq"
            ),
            {"tenant": tenant_id},
        )
        return list(rows)


async def test_the_first_event_starts_the_chain(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    await _append(owner_engine, tenant_id, "auth.login")

    chain = await _chain(owner_engine, tenant_id)
    assert [(seq, prev) for seq, prev, _ in chain] == [(1, bytes(32))]
    assert len(chain[0][2]) == 32


async def test_each_event_links_to_the_one_before_it(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    for action in ("auth.login", "user.registered", "issue.status_changed"):
        await _append(owner_engine, tenant_id, action)

    chain = await _chain(owner_engine, tenant_id)
    assert [seq for seq, _, _ in chain] == [1, 2, 3]
    assert chain[1][1] == chain[0][2]
    assert chain[2][1] == chain[1][2]


async def test_tenants_have_separate_chains(owner_engine: AsyncEngine) -> None:
    first = await _tenant(owner_engine)
    await _append(owner_engine, first, "auth.login")
    second = await _tenant(owner_engine)
    await _append(owner_engine, second, "auth.login")
    await _append(owner_engine, first, "auth.login")

    assert [seq for seq, _, _ in await _chain(owner_engine, first)] == [1, 2]
    assert [seq for seq, _, _ in await _chain(owner_engine, second)] == [1]


async def test_platform_events_have_their_own_chain(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        before = (
            await conn.execute(
                text("SELECT coalesce(max(chain_seq), 0) FROM audit_events WHERE tenant_id IS NULL")
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO audit_events (tenant_id, action, entity_type) "
                "VALUES (NULL, 'platform.tenant_created', 'tenant')"
            )
        )

    chain = await _chain(owner_engine, None)
    assert chain, "the platform chain holds the row just written"
    assert [seq for seq, _, _ in chain] == list(range(1, before + 2))
    last = chain[-1]
    if len(chain) > 1:
        assert last[1] == chain[-2][2]


async def test_a_raw_insert_is_chained_too(owner_engine: AsyncEngine) -> None:
    """Feature code that bypasses audit.service.record() cannot skip the chain."""
    tenant_id = await _tenant(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (tenant_id, action, entity_type) "
                "VALUES (:tenant, 'raw.sql', 'test')"
            ),
            {"tenant": tenant_id},
        )

    [(seq, prev, digest)] = await _chain(owner_engine, tenant_id)
    assert (seq, prev) == (1, bytes(32))
    assert len(digest) == 32


async def test_supplying_chain_columns_is_refused(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="chained by the database"):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type, chain_seq) "
                    "VALUES (:tenant, 'forged', 'test', 7)"
                ),
                {"tenant": tenant_id},
            )


async def test_a_failed_append_leaves_no_gap(owner_engine: AsyncEngine) -> None:
    """The sequence number and the row are released by the same rollback."""
    tenant_id = await _tenant(owner_engine)
    await _append(owner_engine, tenant_id, "auth.login")

    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="value too long"):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type) "
                    "VALUES (:tenant, :action, 'test')"
                ),
                {"tenant": tenant_id, "action": "x" * 200},
            )

    await _append(owner_engine, tenant_id, "auth.login")
    assert [seq for seq, _, _ in await _chain(owner_engine, tenant_id)] == [1, 2]


async def test_concurrent_appends_in_one_chain_stay_contiguous(
    owner_engine: AsyncEngine,
) -> None:
    """The head row is the lock: 16 writers, no gaps, no duplicates (AC-2)."""
    tenant_id = await _tenant(owner_engine)
    factory = get_session_factory()

    async def write(index: int) -> None:
        async with factory() as session:
            await set_tenant(session, tenant_id)
            await session.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type) "
                    "VALUES (:tenant, :action, 'test')"
                ),
                {"tenant": tenant_id, "action": f"concurrent.{index}"},
            )
            await session.commit()

    await asyncio.gather(*(write(i) for i in range(16)))

    chain = await _chain(owner_engine, tenant_id)
    assert [seq for seq, _, _ in chain] == list(range(1, 17))
    for previous, current in itertools.pairwise(chain):
        assert current[1] == previous[2]


async def test_the_head_tracks_the_last_event(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    async with owner_engine.begin() as conn:
        head = (
            await conn.execute(
                text("SELECT next_seq, last_hash FROM audit_chain_heads WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
        ).one()
    assert head == (1, bytes(32)), "a new tenant starts with an empty chain"

    await _append(owner_engine, tenant_id, "auth.login")
    await _append(owner_engine, tenant_id, "auth.logout")

    async with owner_engine.begin() as conn:
        head = (
            await conn.execute(
                text("SELECT next_seq, last_hash FROM audit_chain_heads WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
        ).one()
    last_seq, _, last_hash = (await _chain(owner_engine, tenant_id))[-1]
    assert head == (last_seq + 1, last_hash)


async def test_a_new_tenant_gets_a_head_row(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        head = (
            await conn.execute(
                text("SELECT next_seq, last_hash FROM audit_chain_heads WHERE tenant_id = :tenant"),
                {"tenant": tenant.id},
            )
        ).one()
    assert head == (1, bytes(32))


async def test_the_app_role_cannot_remove_a_head_or_a_checkpoint(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id = await _tenant(owner_engine)
    factory = get_session_factory()
    async with factory() as session:
        await set_tenant(session, tenant_id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("DELETE FROM audit_chain_heads WHERE tenant_id = :t"), {"t": tenant_id}
            )
    async with factory() as session:
        await set_tenant(session, tenant_id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text("DELETE FROM audit_checkpoints"))


async def test_checkpoints_are_append_only(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_checkpoints "
                "(tenant_id, up_to_seq, head_hash, key_id, signature) "
                "VALUES (:tenant, 1, decode(repeat('11', 32), 'hex'), 'k1', "
                "decode(repeat('22', 32), 'hex'))"
            ),
            {"tenant": tenant_id},
        )

    for statement in (
        "UPDATE audit_checkpoints SET key_id = 'k2' WHERE tenant_id = :tenant",
        "DELETE FROM audit_checkpoints WHERE tenant_id = :tenant",
        "TRUNCATE audit_checkpoints",
    ):
        async with owner_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text(statement), {"tenant": tenant_id})
