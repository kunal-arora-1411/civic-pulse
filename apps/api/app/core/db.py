"""Database engine, ORM base and the per-request unit of work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import Connection, DateTime, MetaData, event, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, SessionTransaction, mapped_column

from app.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"server_settings": {"application_name": settings.service_name}},
    )


TENANT_INFO_KEY = "civicpulse.tenant_id"
BYPASS_INFO_KEY = "civicpulse.bypass_rls"

SET_RLS_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    "       set_config('app.bypass_rls', :bypass, true)"
)


def rls_params(info: dict[str, Any]) -> dict[str, str]:
    return {
        "tenant_id": info.get(TENANT_INFO_KEY) or "",
        "bypass": "on" if info.get(BYPASS_INFO_KEY) else "off",
    }


class AppSession(Session):
    """Session that carries the RLS context (see app/core/tenancy.py)."""


@event.listens_for(AppSession, "after_begin")
def _apply_rls_context(session: Session, _: SessionTransaction, connection: Connection) -> None:
    # Transaction-local settings vanish at commit; re-apply them whenever this
    # session starts a new transaction so the context can't silently drop.
    if session.info.get(TENANT_INFO_KEY) or session.info.get(BYPASS_INFO_KEY):
        connection.execute(SET_RLS_CONTEXT, rls_params(session.info))


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: responses are built from objects after the
    # unit of work has committed, and we never want an implicit reload then.
    return async_sessionmaker(
        get_engine(), expire_on_commit=False, autoflush=False, sync_session_class=AppSession
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request.

    Commits when the endpoint returns and rolls back if it raises. Declared
    with scope="function" below, so the commit happens before the response is
    sent: a client never sees a 2xx for a write that then fails to commit.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
