"""Staff TOTP multi-factor authentication.

Secrets are encrypted at rest with Fernet (TOTP_ENCRYPTION_KEY). Each accepted
code's time step is remembered, so a code can't be replayed within its
validity window, including by someone watching over a shoulder.
"""

from __future__ import annotations

import time

import pyotp
from pyotp.totp import TOTP
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, TokenExpired, Unauthenticated
from app.core.ratelimit import enforce_window
from app.core.security import (
    constant_time_equals,
    decode_mfa_token,
    decrypt_secret,
    encrypt_secret,
    utcnow,
)
from app.core.tenancy import acting_as
from app.domains.audit import service as audit
from app.domains.auth.errors import AccountDisabled, CodeExpired, InvalidCode, TooManyAttempts
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.auth.service import IssuedTokens, issue_session
from app.domains.rbac.principal import Principal
from app.domains.users.models import User

TOTP_DRIFT_STEPS = 1  # accept the previous and next 30s window for clock drift


def matching_step(secret: str, code: str, last_used_step: int | None) -> int | None:
    """The time step `code` is valid for, or None. Steps at or before
    `last_used_step` are refused, which is what blocks replay."""
    totp = TOTP(secret)
    current = int(time.time()) // totp.interval
    for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if constant_time_equals(totp.at(step * totp.interval), code):
            return step
    return None


async def setup(db: AsyncSession, principal: Principal) -> tuple[str, str]:
    """Generate (or regenerate) a pending secret. Returns (secret, otpauth URI)."""
    if not principal.is_staff:
        raise Forbidden("Multi-factor authentication is available to staff accounts.")
    settings = get_settings()
    async with acting_as(db, principal.tenant_id, reason="platform admin MFA setup"):
        user = await db.get(User, principal.user_id)
        assert user is not None
        if user.mfa_enabled:
            raise Conflict("Multi-factor authentication is already enabled.")
        secret = pyotp.random_base32()
        user.mfa_secret_encrypted = encrypt_secret(secret)
        await db.flush()
    label = user.email or user.phone
    uri = TOTP(secret).provisioning_uri(name=label, issuer_name=settings.totp_issuer)
    return secret, uri


async def enable(db: AsyncSession, redis: Redis, principal: Principal, code: str) -> None:
    settings = get_settings()
    # Attempts are metered in Redis so failures needn't be committed.
    await enforce_window(
        redis, f"mfa:enable:{principal.user_id}", settings.totp_max_attempts, 15 * 60
    )
    async with acting_as(db, principal.tenant_id, reason="platform admin MFA enable"):
        user = await db.get(User, principal.user_id)
        assert user is not None
        if user.mfa_enabled:
            raise Conflict("Multi-factor authentication is already enabled.")
        if not user.mfa_secret_encrypted:
            raise Conflict("Start multi-factor setup first.")
        step = matching_step(decrypt_secret(user.mfa_secret_encrypted), code, None)
        if step is None:
            raise InvalidCode()
        user.mfa_enabled = True
        user.mfa_last_used_step = step

        # Entering a valid code just proved possession of the device, so the
        # current session counts as MFA-verified from here on.
        family_id = await db.scalar(
            select(AuthSession.family_id).where(AuthSession.id == principal.session_id)
        )
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(mfa_verified=True)
            .execution_options(synchronize_session=False)
        )
        await db.flush()
        await audit.record(
            db, action="auth.mfa_enabled", entity_type="user", entity_id=user.id, actor=principal
        )


async def verify(db: AsyncSession, mfa_token: str, code: str) -> IssuedTokens:
    """Second step of login for users with TOTP enabled."""
    settings = get_settings()
    try:
        claims = decode_mfa_token(mfa_token)
    except TokenExpired as exc:
        # An expired mfa_token is the same situation as an expired OTP:
        # start the login again.
        raise CodeExpired("The sign-in took too long. Request a new code.") from exc

    async with acting_as(db, claims.tenant_id, reason="platform admin MFA login"):
        challenge = await db.scalar(
            select(OtpChallenge).where(OtpChallenge.id == claims.challenge_id).with_for_update()
        )
        if challenge is None or challenge.user_id != claims.user_id:
            raise Unauthenticated("The token is invalid.")
        if challenge.consumed_at is None or challenge.mfa_completed_at is not None:
            raise CodeExpired()
        if challenge.mfa_attempts >= settings.totp_max_attempts:
            raise TooManyAttempts()

        user = await db.get(User, claims.user_id)
        if user is None or not user.mfa_enabled or not user.mfa_secret_encrypted:
            raise Unauthenticated("The token is invalid.")
        if not user.is_active:
            raise AccountDisabled()

        step = matching_step(
            decrypt_secret(user.mfa_secret_encrypted), code, user.mfa_last_used_step
        )
        if step is None:
            challenge.mfa_attempts += 1
            remaining = settings.totp_max_attempts - challenge.mfa_attempts
            await db.flush()
            await db.commit()  # count the failure even though we return an error
            if remaining <= 0:
                raise TooManyAttempts()
            raise InvalidCode(details={"attempts_remaining": remaining})

        challenge.mfa_completed_at = utcnow()
        user.mfa_last_used_step = step
        return await issue_session(db, user, mfa_verified=True)
