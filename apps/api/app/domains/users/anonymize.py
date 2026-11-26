"""Account anonymization at the owner's request (P6-12, PRD 12.2 and 16).

The user row is kept, because reports, issues, support and audit history
reference it and the issue must stay intact (PRD 16). What identifies the
person is wiped instead: phone, email, name, preferences, MFA secret, the
private EXIF copy of their photos (GPS and device), and the address and
browser of their sessions, which are all ended.

The phone column is NOT NULL, E.164-checked and unique per tenant, and the
login upsert relies on that constraint. Rather than loosen it, the number is
replaced by a random one under +999, a country code ITU-T reserves and never
assigns, so no SMS can reach it and no real number can collide with it.
Logging in again with the old number creates a fresh, empty account.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.core.logging import log_fields
from app.core.security import utcnow
from app.core.tenancy import set_tenant
from app.domains.audit import service as audit
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.media.models import MediaAsset
from app.domains.rbac.principal import Principal
from app.domains.users.models import User

logger = logging.getLogger(__name__)

PLACEHOLDER_PREFIX = "+999"


def placeholder_phone() -> str:
    # +999 and 11 random digits: 14 digits, inside E.164's 15.
    return PLACEHOLDER_PREFIX + "".join(secrets.choice("0123456789") for _ in range(11))


async def anonymize_self(db: AsyncSession, principal: Principal) -> None:
    """Wipe the caller's personal data and end all their sessions.

    Citizens only: staff accounts carry assignments and accountability, so
    an administrator deactivates them instead.
    """
    if principal.is_staff or principal.tenant_id is None:
        raise Forbidden("Staff accounts are deactivated by an administrator.")
    tenant_id = principal.tenant_id
    await set_tenant(db, tenant_id)
    user = await db.scalar(select(User).where(User.id == principal.user_id).with_for_update())
    if user is None:
        raise NotFound()
    if user.anonymized_at is not None:
        return

    old_phone = user.phone
    now = utcnow()
    user.phone = placeholder_phone()
    user.email = None
    user.display_name = None
    user.preferences = {}
    user.is_active = False
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_last_used_step = None
    user.anonymized_at = now

    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id)
        .values(ip=None, user_agent=None)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason="anonymized")
        .execution_options(synchronize_session=False)
    )
    await db.execute(delete(OtpChallenge).where(OtpChallenge.phone == old_phone))
    media = await db.execute(
        update(MediaAsset)
        .where(MediaAsset.owner_id == user.id, MediaAsset.exif.is_not(None))
        .values(exif=None)
        .execution_options(synchronize_session=False)
    )
    await audit.record(
        db,
        action="user.anonymized",
        entity_type="user",
        entity_id=user.id,
        actor=principal,
        tenant_id=tenant_id,
        after={"media_exif_cleared": int(media.rowcount or 0)},  # pyright: ignore[reportAttributeAccessIssue]
    )
    logger.info("user anonymized", extra=log_fields(user_id=str(user.id)))
