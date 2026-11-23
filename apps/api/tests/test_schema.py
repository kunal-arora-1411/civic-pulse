"""The migrated schema: extensions, the app role, append-only audit, and no
drift between the ORM models and migration 0001."""

from __future__ import annotations

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Base


async def test_required_extensions_are_installed(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(text("SELECT extname FROM pg_extension"))
        installed = {row[0] for row in rows}
    assert {"postgis", "vector", "h3", "pgcrypto"} <= installed


async def test_app_role_cannot_bypass_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles "
                    "WHERE rolname = 'civicpulse_app'"
                )
            )
        ).one()
    assert row == (False, False, False)


async def test_audit_events_reject_update_and_delete(owner_engine: AsyncEngine) -> None:
    # Even the owner (a superuser) is stopped by the trigger.
    async with owner_engine.begin() as conn:
        event_id = (
            await conn.execute(
                text(
                    "INSERT INTO audit_events (action, entity_type) "
                    "VALUES ('test.event', 'test') RETURNING id"
                )
            )
        ).scalar_one()

    for statement in (
        "UPDATE audit_events SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
    ):
        async with owner_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text(statement), {"id": event_id})

    async with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text("TRUNCATE audit_events"))


async def test_app_role_privileges_on_audit_events(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        privileges = (
            await conn.execute(
                text(
                    "SELECT has_table_privilege('civicpulse_app', 'audit_events', 'INSERT'),"
                    "       has_table_privilege('civicpulse_app', 'audit_events', 'UPDATE'),"
                    "       has_table_privilege('civicpulse_app', 'audit_events', 'DELETE'),"
                    "       has_table_privilege('civicpulse_app', 'alembic_version', 'SELECT')"
                )
            )
        ).one()
    assert privileges == (True, False, False, False)


def _include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    if type_ != "table":
        return True
    foreign = name in {"spatial_ref_sys", "alembic_version"}
    return not foreign and getattr(obj, "schema", None) not in {"tiger", "topology"}


def _diff(connection: Any) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "include_object": _include_object}
    )
    return compare_metadata(context, Base.metadata)


async def test_models_match_migrations(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    assert diff == []
