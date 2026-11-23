"""AC-14 at the database level: the app role can only see the tenant set for
its transaction, whatever the query asks for."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.db import AppSession, get_session_factory
from app.core.tenancy import acting_as, rls_bypass, set_tenant
from app.domains.org.models import Department
from app.domains.users.models import User
from tests.factories import TenantRow, create_department, create_tenant, create_user


@pytest.fixture
async def two_tenants(owner_engine: AsyncEngine) -> tuple[TenantRow, TenantRow]:
    async with owner_engine.begin() as conn:
        a = await create_tenant(conn, name="Tenant A")
        b = await create_tenant(conn, name="Tenant B")
        for tenant in (a, b):
            await create_department(conn, tenant.id)
            await create_user(conn, tenant.id, "citizen")
            await create_user(conn, tenant.id, "municipal_admin")
    return a, b


def _session() -> AsyncSession:
    return get_session_factory()()


async def _count(session: AsyncSession, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model).filter_by(**filters)
    return (await session.execute(stmt)).scalar_one()


async def test_no_tenant_set_sees_nothing(two_tenants: tuple[TenantRow, TenantRow]) -> None:
    async with _session() as session:
        assert await _count(session, User) == 0
        assert await _count(session, Department) == 0


async def test_tenant_a_cannot_see_tenant_b_rows(two_tenants: tuple[TenantRow, TenantRow]) -> None:
    a, b = two_tenants
    async with _session() as session:
        await set_tenant(session, a.id)
        # Asking for tenant B explicitly still returns nothing.
        assert await _count(session, User, tenant_id=b.id) == 0
        assert await _count(session, Department, tenant_id=b.id) == 0
        # And unfiltered queries only see tenant A.
        tenants = (await session.execute(select(User.tenant_id).distinct())).scalars().all()
        assert tenants == [a.id]


async def test_tenant_a_cannot_write_tenant_b_rows(
    two_tenants: tuple[TenantRow, TenantRow],
) -> None:
    a, b = two_tenants
    async with _session() as session:
        await set_tenant(session, a.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("INSERT INTO departments (tenant_id, name, code) VALUES (:t, 'X', 'XX')"),
                {"t": b.id},
            )

    async with _session() as session:
        await set_tenant(session, a.id)
        result = await session.execute(
            text("UPDATE departments SET name = 'hijacked' WHERE tenant_id = :t"), {"t": b.id}
        )
        assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]
        result = await session.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": b.id})
        assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_moving_a_row_to_another_tenant_is_rejected(
    two_tenants: tuple[TenantRow, TenantRow],
) -> None:
    a, b = two_tenants
    async with _session() as session:
        await set_tenant(session, a.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("UPDATE departments SET tenant_id = :b WHERE tenant_id = :a"),
                {"a": a.id, "b": b.id},
            )


async def test_bypass_is_explicit_and_scoped(two_tenants: tuple[TenantRow, TenantRow]) -> None:
    a, b = two_tenants
    async with _session() as session:
        await set_tenant(session, a.id)
        async with rls_bypass(session, reason="test"):
            assert await _count(session, Department, tenant_id=b.id) == 1
        # Back to tenant A only once the block ends.
        assert await _count(session, Department, tenant_id=b.id) == 0
        assert await _count(session, Department, tenant_id=a.id) == 1


async def test_acting_as_platform_uses_bypass(two_tenants: tuple[TenantRow, TenantRow]) -> None:
    _, b = two_tenants
    async with _session() as session:
        async with acting_as(session, None, reason="test platform"):
            assert await _count(session, Department, tenant_id=b.id) == 1
        assert await _count(session, Department, tenant_id=b.id) == 0


async def test_context_survives_commit_and_never_leaks_to_next_session(
    two_tenants: tuple[TenantRow, TenantRow],
) -> None:
    a, _ = two_tenants
    # A pool of exactly one connection, so the second session must reuse the
    # first session's connection.
    engine = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0)
    single = async_sessionmaker(engine, expire_on_commit=False, sync_session_class=AppSession)
    pid_sql = text("SELECT pg_backend_pid()")
    setting_sql = text("SELECT current_setting('app.tenant_id', true)")
    try:
        async with single() as session:
            await set_tenant(session, a.id)
            assert await _count(session, Department) == 1
            first_pid = (await session.execute(pid_sql)).scalar_one()
            await session.commit()
            # New transaction in the same session: the listener re-applies tenant A.
            assert await _count(session, Department) == 1
            assert (await session.execute(setting_sql)).scalar_one() == str(a.id)
            await session.commit()

        async with single() as session:
            assert (await session.execute(pid_sql)).scalar_one() == first_pid
            assert (await session.execute(setting_sql)).scalar_one() in ("", None)
            assert await _count(session, Department) == 0
    finally:
        await engine.dispose()


async def test_tenants_table_is_readable_without_tenant(
    two_tenants: tuple[TenantRow, TenantRow],
) -> None:
    # The registry itself is not tenant-scoped: X-Tenant lookups happen before
    # any tenant is known.
    a, _ = two_tenants
    async with _session() as session:
        slug = (
            await session.execute(text("SELECT slug FROM tenants WHERE id = :id"), {"id": a.id})
        ).scalar_one()
        assert slug == a.slug
