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
        # Every test request comes from 127.0.0.1.
        "OTP_MAX_PER_IP_PER_HOUR": "100000",
        # Real MinIO from compose, in a bucket of its own (emptied per run).
        # The root credentials are fine here: the suite creates that bucket.
        "S3_ENDPOINT": os.environ.get("TEST_S3_ENDPOINT", "http://localhost:9000"),
        "S3_PUBLIC_ENDPOINT": os.environ.get("TEST_S3_ENDPOINT", "http://localhost:9000"),
        "S3_ACCESS_KEY": os.environ.get("TEST_S3_ACCESS_KEY", "civicpulse"),
        "S3_SECRET_KEY": os.environ.get("TEST_S3_SECRET_KEY", "civicpulse-minio"),
        "S3_BUCKET": os.environ.get("TEST_S3_BUCKET", "civicpulse-test"),
        # Never call a real geocoder from tests.
        "GEOCODER": "none",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from tests.helpers import RecordingSms  # noqa: E402


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


def _reset_bucket() -> None:
    import boto3
    from botocore.config import Config

    settings = get_settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = settings.s3_bucket
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)
        return
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})


@pytest.fixture(scope="session", autouse=True)
def bucket() -> str:
    """An empty test bucket on the compose MinIO."""
    _reset_bucket()
    return get_settings().s3_bucket


@pytest.fixture(scope="session")
async def owner_engine(database: None) -> AsyncIterator[AsyncEngine]:
    """Superuser connection to the test database, for setup and assertions."""
    engine = create_async_engine(OWNER_URL)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def sms() -> RecordingSms:
    return RecordingSms()


@pytest.fixture(scope="session")
async def app(database: None, sms: RecordingSms) -> AsyncIterator[FastAPI]:
    from app.core.db import get_engine
    from app.domains.auth.sms import get_sms_provider
    from app.main import create_app

    redis = get_redis()
    await redis.flushdb()
    application = create_app()
    application.dependency_overrides[get_sms_provider] = lambda: sms
    yield application
    await get_engine().dispose()
    await redis.aclose()


@pytest.fixture
def redis():
    return get_redis()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def settings():
    return get_settings()
