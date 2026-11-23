"""Idempotency keys for retry-prone create operations (PRD §11.1).

The key is claimed with INSERT ... ON CONFLICT DO NOTHING inside the request
transaction, and the stored response is written in that same transaction.
That gives the semantics we want without an "in progress" state:

* A retry after success finds the committed row and replays the response.
* A concurrent duplicate blocks on the unique index until the first
  transaction finishes. If it committed, the duplicate replays; if it rolled
  back, the duplicate proceeds as the first attempt. Two creates can't both
  happen.
* Failed requests leave nothing behind (their transaction rolled back), so
  they can be retried with the same key.

Keys are scoped to (tenant, actor, operation): two administrators can't
collide, and one key can't be replayed against a different endpoint.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.db import Base
from app.core.errors import Conflict, IdempotencyKeyReused

REPLAY_HEADER = "Idempotent-Replayed"

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[\x21-\x7e]+$",
        description="Unique per logical operation. Retrying with the same key and body "
        "replays the original response; a different body returns 422.",
    ),
]


class IdempotencyKey(Base):
    """A stored response for a retried create request."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "actor_id", "scope", "key", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def request_fingerprint(body: BaseModel) -> str:
    """Hash of the parsed body, so formatting and key order don't matter."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def begin(
    db: AsyncSession,
    *,
    key: str | None,
    scope: str,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    body: BaseModel,
) -> IdempotencyKey | JSONResponse | None:
    """Claim `key`, or return the response to replay.

    Returns None when no key was sent, the claimed row when this request
    should do the work (pass it to `complete`), or a ready response to send
    when this is a replay.
    """
    if key is None:
        return None
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=get_settings().idempotency_ttl_seconds)
    fingerprint = request_fingerprint(body)
    identity = {"tenant_id": tenant_id, "actor_id": actor_id, "scope": scope, "key": key}

    claimed = await db.scalar(
        pg_insert(IdempotencyKey)
        .values(id=uuid.uuid4(), request_hash=fingerprint, expires_at=expires_at, **identity)
        .on_conflict_do_nothing(constraint="uq_idempotency_keys_tenant_id_actor_id_scope_key")
        .returning(IdempotencyKey.id)
    )
    if claimed is not None:
        record = await db.get(IdempotencyKey, claimed)
        assert record is not None
        return record

    # Someone already holds this key (and has committed: the INSERT above
    # waited for them). Lock it so an expired-key takeover can't race.
    tenant_clause = (
        IdempotencyKey.tenant_id.is_(None)
        if tenant_id is None
        else IdempotencyKey.tenant_id == tenant_id
    )
    actor_clause = (
        IdempotencyKey.actor_id.is_(None)
        if actor_id is None
        else IdempotencyKey.actor_id == actor_id
    )
    existing = await db.scalar(
        select(IdempotencyKey)
        .where(
            tenant_clause, actor_clause, IdempotencyKey.scope == scope, IdempotencyKey.key == key
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert existing is not None

    if existing.expires_at <= now:
        existing.request_hash = fingerprint
        existing.response_status = None
        existing.response_body = None
        existing.expires_at = expires_at
        await db.flush()
        return existing
    if existing.request_hash != fingerprint:
        raise IdempotencyKeyReused()
    if existing.response_status is None:  # pragma: no cover - defensive
        raise Conflict("A request with this Idempotency-Key is still being processed.")
    return JSONResponse(
        existing.response_body,
        status_code=existing.response_status,
        headers={REPLAY_HEADER: "true"},
    )


async def complete(
    db: AsyncSession, record: IdempotencyKey | None, status_code: int, body: BaseModel
) -> None:
    """Store the response in the same transaction as the work itself."""
    if record is None:
        return
    record.response_status = status_code
    record.response_body = body.model_dump(mode="json")
    await db.flush()
