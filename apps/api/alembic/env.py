"""Alembic environment (async).

Migrations run as the schema owner (MIGRATION_DATABASE_URL), never as the app
role: the app role must not be able to alter tables or policies.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Tables that belong to PostGIS and its companion extensions, not to us.
_FOREIGN_SCHEMAS = {"tiger", "tiger_data", "topology"}
_FOREIGN_TABLES = {"spatial_ref_sys"}


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    if type_ != "table":
        return True
    return name not in _FOREIGN_TABLES and getattr(obj, "schema", None) not in _FOREIGN_SCHEMAS


def _url() -> str:
    settings = get_settings()
    return config.get_main_option("sqlalchemy.url") or (
        settings.migration_database_url or settings.database_url
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
