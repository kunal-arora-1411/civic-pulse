from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditEvent(Base):
    """Append-only record of a sensitive action, in a per-tenant hash chain.

    A trigger rejects UPDATE, DELETE and TRUNCATE, and the app role is only
    granted SELECT and INSERT. actor_id deliberately has no foreign key: the
    history must outlive the user it mentions.

    `chain_seq`, `prev_hash` and `hash` are assigned by the `audit_chain_assign`
    trigger (migration 0017), never by application code -- an INSERT that
    supplies them is refused. `hash` is the SHA-256 of the canonical framing of
    this row including `prev_hash`, so rewriting any column breaks the chain at
    this row and every link after it. See app/domains/audit/chain.py for the
    Python mirror of that framing.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_events_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_audit_events_tenant_actor", "tenant_id", "actor_id"),
        # Postgres treats NULLs as distinct in a plain unique index, so the
        # platform chain (tenant_id NULL) needs its own partial index. Both are
        # also the index the verifier walks in order.
        Index(
            "uq_audit_events_chain_seq",
            "tenant_id",
            "chain_seq",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        Index(
            "uq_audit_events_platform_chain_seq",
            "chain_seq",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        CheckConstraint("hash IS NULL OR octet_length(hash) = 32", name="ck_audit_events_hash_len"),
        CheckConstraint(
            "prev_hash IS NULL OR octet_length(prev_hash) = 32",
            name="ck_audit_events_prev_hash_len",
        ),
        CheckConstraint("chain_seq IS NULL OR chain_seq >= 1", name="ck_audit_events_chain_seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    chain_seq: Mapped[int] = mapped_column(BigInteger)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    hash: Mapped[bytes] = mapped_column(LargeBinary(32))


class AuditChainHead(Base):
    """Where one chain ends: the only mutable row in the hash chain.

    There is one row per tenant and one for the platform chain (tenant_id NULL,
    reachable only through the explicit RLS bypass). The `UPDATE` the append
    trigger runs against this row is also the lock that serialises appends to
    that chain, which is what keeps `chain_seq` contiguous.
    """

    __tablename__ = "audit_chain_heads"
    __table_args__ = (
        # NULLS NOT DISTINCT so the platform row is covered by the same natural
        # key, and `ON CONFLICT ON CONSTRAINT uq_audit_chain_heads_tenant` in the
        # trigger is unambiguous for it.
        UniqueConstraint(
            "tenant_id",
            name="uq_audit_chain_heads_tenant",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("next_seq >= 1", name="ck_audit_chain_heads_next_seq"),
        CheckConstraint("octet_length(last_hash) = 32", name="ck_audit_chain_heads_last_hash_len"),
    )

    # A synthetic key, because a primary key cannot hold the platform row's NULL
    # tenant_id.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "tenants.id",
            ondelete="RESTRICT",
            name="fk_audit_chain_heads_tenant_id_tenants",
        )
    )
    next_seq: Mapped[int] = mapped_column(BigInteger)
    last_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class AuditCheckpoint(Base):
    """A signed seal of a chain's head at a sequence (A6.3).

    The chain on its own cannot detect truncation: delete the last rows and the
    remaining prefix still verifies. A checkpoint records that the head was `H`
    at sequence `N`, signed with a key held outside the database, so removing
    rows below `N` becomes visible. Append-only by trigger, like the log.
    """

    __tablename__ = "audit_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "up_to_seq",
            name="uq_audit_checkpoints_scope_seq",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_audit_checkpoints_tenant_created", "tenant_id", "created_at"),
        CheckConstraint("up_to_seq >= 1", name="ck_audit_checkpoints_up_to_seq"),
        CheckConstraint("octet_length(head_hash) = 32", name="ck_audit_checkpoints_head_hash_len"),
        CheckConstraint("octet_length(signature) = 32", name="ck_audit_checkpoints_signature_len"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "tenants.id",
            ondelete="RESTRICT",
            name="fk_audit_checkpoints_tenant_id_tenants",
        )
    )
    up_to_seq: Mapped[int] = mapped_column(BigInteger)
    head_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    key_id: Mapped[str] = mapped_column(String(64))
    signature: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class AuditChainVerification(Base):
    """One run of the verifier over a range of one chain.

    A unique index in the database allows one `pending`/`running` run per
    tenant, so two simultaneous requests cannot both start one.
    """

    __tablename__ = "audit_chain_verifications"
    __table_args__ = (
        Index("ix_audit_chain_verifications_tenant_started", "tenant_id", "started_at"),
        Index(
            "uq_audit_chain_verifications_in_flight",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        CheckConstraint("mode IN ('db', 'independent')", name="ck_audit_chain_verifications_mode"),
        CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'error')",
            name="ck_audit_chain_verifications_status",
        ),
        CheckConstraint(
            "from_seq >= 1 AND to_seq >= from_seq", name="ck_audit_chain_verifications_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "tenants.id",
            ondelete="CASCADE",
            name="fk_audit_chain_verifications_tenant_id_tenants",
        )
    )
    from_seq: Mapped[int] = mapped_column(BigInteger)
    to_seq: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    checked_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    first_bad_seq: Mapped[int | None] = mapped_column(BigInteger)
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    # No foreign key: who asked outlives the user it mentions.
    requested_by: Mapped[uuid.UUID | None] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
