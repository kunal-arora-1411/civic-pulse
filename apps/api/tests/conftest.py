"""Test harness: a fresh `civicpulse_test` database on a real Postgres.

The database is recreated once per session through the owner connection and
migrated to head. The app under test connects as the non-superuser
`civicpulse_app` role, exactly as in production, so row-level security is
exercised for real. The owner engine is available to tests for setup and for
checking what actually landed in the database.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from sqlalchemy.engine import URL, make_url

TEST_DB_NAME = "civicpulse_test"

_owner_url = make_url(
    os.environ.get(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://civicpulse:civicpulse@localhost:5432/civicpulse",
    )
)
_app_url = make_url(
    os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://civicpulse_app:civicpulse_app@localhost:5432/civicpulse",
    )
)
OWNER_URL = _owner_url.set(database=TEST_DB_NAME)
APP_URL = _app_url.set(database=TEST_DB_NAME)
MAINTENANCE_URL = _owner_url.set(database="postgres")

# Settings are read once, on first use, so the environment must be complete
# before anything from `app` is imported.
os.environ.update(
    {
        "ENV": "test",
        "LOG_LEVEL": os.environ.get("TEST_LOG_LEVEL", "WARNING"),
        "DATABASE_URL": APP_URL.render_as_string(hide_password=False),
        "MIGRATION_DATABASE_URL": OWNER_URL.render_as_string(hide_password=False),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
        "JWT_SECRET": "test-jwt-secret-that-is-long-enough-0123456789",
        "OTP_HMAC_SECRET": "test-otp-hmac-secret-long-enough-0123456789",
        # A fixed, valid Fernet key used only by the test suite.
        "TOTP_ENCRYPTION_KEY": "dGVzdC10b3RwLWtleS0wMDAwMDAwMDAwMDAwMDAwMDA=",
        "DEV_FIXED_OTP": "false",
        "REQUIRE_STAFF_MFA": "false",
        "REFRESH_REUSE_GRACE_SECONDS": "0",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.redis import get_redis  # noqa: E402


def _dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _recreate_database() -> None:
    conn = await asyncpg.connect(_dsn(MAINTENANCE_URL))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}" OWNER "{OWNER_URL.username}"')
        # The role normally comes from infra/db/init. Create it here if this
        # Postgres was not started from our image (e.g. a bare CI service).
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_URL.username)
        if not exists:
            await conn.execute(
                f'CREATE ROLE "{APP_URL.username}" LOGIN NOSUPERUSER NOBYPASSRLS '
                f"NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{APP_URL.password}'"
            )
        await conn.execute(f'GRANT CONNECT ON DATABASE "{TEST_DB_NAME}" TO "{APP_URL.username}"')
    finally:
        await conn.close()

    conn = await asyncpg.connect(_dsn(OWNER_URL))
    try:
        await conn.execute(f'GRANT USAGE ON SCHEMA public TO "{APP_URL.username}"')
    finally:
        await conn.close()


def _run_migrations() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    if not (root / "alembic").exists():
        return
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_recreate_database())
    _run_migrations()


@pytest.fixture(scope="session")
async def owner_engine(database: None) -> AsyncIterator[AsyncEngine]:
    """Superuser connection to the test database, for setup and assertions."""
    engine = create_async_engine(OWNER_URL)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app(database: None) -> AsyncIterator[FastAPI]:
    from app.core.db import get_engine
    from app.main import create_app

    redis = get_redis()
    await redis.flushdb()
    application = create_app()
    yield application
    await get_engine().dispose()
    await redis.aclose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def settings():
    return get_settings()
