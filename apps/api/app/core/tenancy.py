"""Tenant context for row-level security.

Postgres policies read two transaction-local settings:

* `app.tenant_id`: the tenant whose rows are visible.
* `app.bypass_rls`: `on` lifts the policy. Only platform-admin paths and
  system jobs use it, always through `rls_bypass()` with a stated reason, so
  every use is visible in code review and in the logs.

Both are set with `set_config(..., is_local => true)`, so they end with the
transaction and can never leak to the next request that borrows the pooled
connection. The desired state lives in `session.info`; an `after_begin`
listener on AppSession (app/core/db.py) re-applies it whenever the session
opens a new transaction, for example after an explicit mid-request commit.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import tenant_id_var
from app.core.db import (
    BYPASS_INFO_KEY,
    SET_RLS_CONTEXT,
    TENANT_INFO_KEY,
    get_session_factory,
    rls_params,
)
from app.core.logging import log_fields

logger = logging.getLogger(__name__)


async def _sync(session: AsyncSession) -> None:
    # Outside a transaction there is nothing to update: after_begin applies
    # the state when the next one starts.
    if session.in_transaction():
        await session.execute(SET_RLS_CONTEXT, rls_params(session.info))


def current_tenant(session: AsyncSession) -> uuid.UUID | None:
    value = session.info.get(TENANT_INFO_KEY)
    return uuid.UUID(value) if value else None


def bypass_enabled(session: AsyncSession) -> bool:
    return bool(session.info.get(BYPASS_INFO_KEY))


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Scope the rest of this session to one tenant (or to none)."""
    session.info[TENANT_INFO_KEY] = str(tenant_id) if tenant_id else None
    tenant_id_var.set(str(tenant_id) if tenant_id else None)
    await _sync(session)


@asynccontextmanager
async def rls_bypass(session: AsyncSession, *, reason: str) -> AsyncIterator[None]:
    """Lift tenant isolation for the duration of the block.

    Use only for platform-admin paths and system jobs. `reason` is logged.
    """
    previous = bool(session.info.get(BYPASS_INFO_KEY))
    session.info[BYPASS_INFO_KEY] = True
    if not previous:
        logger.info("rls bypass enabled", extra=log_fields(rls_bypass_reason=reason))
    await _sync(session)
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        session.info[BYPASS_INFO_KEY] = previous
        try:
            await _sync(session)
        except SQLAlchemyError:
            # The transaction already failed and will be rolled back, which
            # discards the transaction-local setting anyway.
            if not failed:
                raise


@asynccontextmanager
async def acting_as(
    session: AsyncSession, tenant_id: uuid.UUID | None, *, reason: str
) -> AsyncIterator[None]:
    """Run as the given tenant, or as the platform (bypass) when it is None.

    Platform administrators and their sessions are the only rows with no
    tenant, so reaching them needs the bypass by construction.
    """
    if tenant_id is not None:
        await set_tenant(session, tenant_id)
        yield
    else:
        async with rls_bypass(session, reason=reason):
            yield


@asynccontextmanager
async def system_session(*, reason: str) -> AsyncIterator[AsyncSession]:
    """A session for system jobs (seed, Celery tasks) with RLS lifted.

    Commits on success and rolls back on error.
    """
    async with get_session_factory()() as session:
        try:
            async with rls_bypass(session, reason=reason):
                yield session
                # Flush while the bypass is still on: objects added with
                # session.add() would otherwise be written at commit, after
                # the bypass is lifted, and fail the policy.
                await session.flush()
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
