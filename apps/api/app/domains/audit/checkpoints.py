"""Signed seals of a chain's head.

A chain on its own cannot detect truncation: delete the last fifty rows and the
remaining prefix still verifies perfectly. A checkpoint records that the head was
`H` at sequence `N`, signed with a key that is not in the database, so removing
rows below `N` becomes visible.

Sealing only ever happens after the range since the previous checkpoint verified.
A broken chain therefore stops being sealed, which freezes the evidence at the
last good state rather than signing over damage.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.tenancy import rls_bypass, set_tenant, system_session
from app.domains.audit import verification
from app.domains.audit.chain import micros
from app.domains.audit.models import AuditCheckpoint

logger = logging.getLogger(__name__)

DOMAIN_TAG = "civicpulse.audit.checkpoint.v1"
#: How the platform chain is named in a signed message (it has no tenant id).
PLATFORM = "platform"

Scope = uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AnchorKey:
    key_id: str
    secret: bytes


@dataclass(frozen=True, slots=True)
class SealResult:
    tenant_id: Scope
    up_to_seq: int
    created: bool
    refused: bool = False

    @property
    def sealed(self) -> bool:
        return self.created


class AnchorKeyMissing(RuntimeError):
    """Sealing was asked for without a key. Never seal unsigned."""


def current_key(settings: Settings | None = None) -> AnchorKey | None:
    settings = settings or get_settings()
    if settings.audit_anchor_key is None:
        return None
    return AnchorKey(
        key_id=settings.audit_anchor_key_id,
        secret=settings.audit_anchor_key.get_secret_value().encode(),
    )


def known_keys(settings: Settings | None = None) -> dict[str, bytes]:
    """Every key a signature may have been made with, including rotated-out ones.

    Without the previous keys a rotation would turn every older checkpoint into a
    false alarm.
    """
    settings = settings or get_settings()
    keys = {
        key_id: secret.get_secret_value().encode()
        for key_id, secret in settings.audit_anchor_previous_keys.items()
    }
    current = current_key(settings)
    if current is not None:
        keys[current.key_id] = current.secret
    return keys


def message(tenant_id: Scope, up_to_seq: int, head_hash: bytes, created: datetime) -> bytes:
    """The exact bytes that are signed.

    `created_at` is part of the message, so a signature cannot be moved onto a
    different checkpoint that happens to share a sequence and hash.
    """
    scope = str(tenant_id) if tenant_id is not None else PLATFORM
    return (
        f"{DOMAIN_TAG}|scope:{scope}|seq:{up_to_seq}|hash:{head_hash.hex()}"
        f"|created_us:{micros(created)}"
    ).encode()


def sign(secret: bytes, body: bytes) -> bytes:
    return hmac.new(secret, body, hashlib.sha256).digest()


def signature_of(checkpoint: AuditCheckpoint, secret: bytes) -> bytes:
    return sign(
        secret,
        message(
            checkpoint.tenant_id,
            checkpoint.up_to_seq,
            bytes(checkpoint.head_hash),
            checkpoint.created_at,
        ),
    )


def signature_valid(checkpoint: AuditCheckpoint, keys: dict[str, bytes] | None = None) -> bool:
    """Whether the signature verifies (and whether its key is still known)."""
    keys = known_keys() if keys is None else keys
    secret = keys.get(checkpoint.key_id)
    if secret is None:
        return False
    try:
        expected = signature_of(checkpoint, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, bytes(checkpoint.signature))


async def latest(db: AsyncSession, tenant_id: Scope) -> AuditCheckpoint | None:
    return (
        await db.execute(
            select(AuditCheckpoint)
            .where(AuditCheckpoint.tenant_id.is_not_distinct_from(tenant_id))
            .order_by(AuditCheckpoint.up_to_seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def row_at(db: AsyncSession, tenant_id: Scope, seq: int) -> bytes | None:
    value = (
        await db.execute(
            text(
                "SELECT hash FROM audit_events "
                "WHERE tenant_id IS NOT DISTINCT FROM :tenant AND chain_seq = :seq"
            ),
            {"tenant": tenant_id, "seq": seq},
        )
    ).scalar()
    return None if value is None else bytes(value)


async def verify_checkpoint(
    db: AsyncSession, checkpoint: AuditCheckpoint, keys: dict[str, bytes] | None = None
) -> tuple[bool, str | None]:
    """`(ok, reason)` for one checkpoint: signature, then the row it names."""
    if not signature_valid(checkpoint, keys):
        return False, "checkpoint signature does not verify"
    present = await row_at(db, checkpoint.tenant_id, checkpoint.up_to_seq)
    if present is None:
        return False, (
            f"the event at chain_seq {checkpoint.up_to_seq} is gone, but a checkpoint signed it"
        )
    if present != bytes(checkpoint.head_hash):
        return False, (
            f"the event at chain_seq {checkpoint.up_to_seq} no longer matches the hash "
            "that was signed"
        )
    return True, None


async def seal(
    db: AsyncSession,
    *,
    tenant_id: Scope,
    now: datetime | None = None,
    verify: bool = True,
    key: AnchorKey | None = None,
) -> SealResult | None:
    """Seal the current head of one chain, or decide there is nothing to seal.

    Returns `None` when the head has not moved since the previous checkpoint, and
    a `SealResult` with `refused` set when the range since then does not verify.
    Raises `AnchorKeyMissing` when there is no key: an unsigned seal would look
    like evidence without being any.
    """
    anchor = key if key is not None else current_key()
    if anchor is None:
        raise AnchorKeyMissing("no AUDIT_ANCHOR_KEY configured; refusing to seal")

    head_seq, head_hash = await verification.chain_head(db, tenant_id)
    if head_seq == 0:
        return None

    previous = await latest(db, tenant_id)
    if previous is not None and previous.up_to_seq >= head_seq:
        return None

    if verify:
        since = previous.up_to_seq + 1 if previous is not None else 1
        report = await verification.verify_range(
            db, tenant_id=tenant_id, from_seq=since, to_seq=head_seq, mode="db"
        )
        if not report.passed:
            logger.error(
                "audit.chain.sealing_skipped",
                extra={
                    "audit": {
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "chain_seq": report.divergence.chain_seq if report.divergence else None,
                        "reason": report.divergence.reason if report.divergence else None,
                    }
                },
            )
            return SealResult(tenant_id=tenant_id, up_to_seq=head_seq, created=False, refused=True)

    created = (now or datetime.now(UTC)).astimezone(UTC)
    signature = sign(anchor.secret, message(tenant_id, head_seq, head_hash, created))
    statement = (
        pg_insert(AuditCheckpoint)
        .values(
            tenant_id=tenant_id,
            up_to_seq=head_seq,
            head_hash=head_hash,
            key_id=anchor.key_id,
            signature=signature,
            created_at=created,
        )
        .on_conflict_do_nothing(constraint="uq_audit_checkpoints_scope_seq")
        .returning(AuditCheckpoint.id)
    )
    inserted = (await db.execute(statement)).scalar_one_or_none()
    await db.flush()
    if inserted is None:
        return SealResult(tenant_id=tenant_id, up_to_seq=head_seq, created=False)
    logger.info(
        "audit.chain.checkpointed",
        extra={
            "audit": {
                "tenant_id": str(tenant_id) if tenant_id else None,
                "up_to_seq": head_seq,
                "key_id": anchor.key_id,
            }
        },
    )
    return SealResult(tenant_id=tenant_id, up_to_seq=head_seq, created=True)


async def seal_all_chains(now: datetime | None = None) -> dict[str, int]:
    """Seal every chain whose head has moved. One short transaction per chain."""
    if current_key() is None:
        logger.warning("audit.chain.checkpoint_skipped: AUDIT_ANCHOR_KEY is not configured")
        return {"sealed": 0, "skipped": 0, "refused": 0, "not_configured": 1}

    async with system_session(reason="audit checkpoint: list tenants") as db:
        tenant_ids: list[uuid.UUID | None] = [
            row[0] for row in (await db.execute(text("SELECT id FROM tenants ORDER BY id")))
        ]
    tenant_ids.append(None)  # the platform chain

    sealed = skipped = refused = 0
    for tenant_id in tenant_ids:
        async with system_session(reason="audit checkpoint") as db:
            if tenant_id is None:
                async with rls_bypass(db, reason="platform audit chain checkpoint"):
                    result = await seal(db, tenant_id=None, now=now)
            else:
                await set_tenant(db, tenant_id)
                result = await seal(db, tenant_id=tenant_id, now=now)
            if result is None:
                skipped += 1
            elif result.refused:
                refused += 1
            else:
                sealed += 1
    return {"sealed": sealed, "skipped": skipped, "refused": refused, "not_configured": 0}


async def checkpoints_for(
    db: AsyncSession, tenant_id: Scope, *, limit: int | None = None
) -> list[AuditCheckpoint]:
    statement = (
        select(AuditCheckpoint)
        .where(AuditCheckpoint.tenant_id.is_not_distinct_from(tenant_id))
        .order_by(AuditCheckpoint.up_to_seq.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list((await db.execute(statement)).scalars())
