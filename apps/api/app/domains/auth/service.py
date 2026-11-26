"""Authentication flows: phone OTP, sessions and refresh-token rotation.

Transaction notes. Everything here runs inside the request's single
transaction, with two deliberate exceptions where an error response must
still persist a write: a failed OTP attempt (otherwise the attempt limit could
be brute-forced by simply failing) and revoking a session family on refresh
reuse. Those paths commit explicitly before raising.

Lookups by an unguessable identifier (an OTP challenge id, a refresh token
hash) happen before the tenant is known, so they run under an explicit RLS
bypass. The tenant is then taken from the row that was found.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_client
from app.core.errors import Unauthenticated
from app.core.logging import log_fields
from app.core.phone import mask_phone
from app.core.ratelimit import enforce_cooldown, enforce_window
from app.core.security import (
    AccessClaims,
    constant_time_equals,
    encode_access_token,
    encode_mfa_token,
    hash_token,
    hmac_hex,
    new_opaque_token,
    utcnow,
)
from app.core.tenancy import acting_as, rls_bypass
from app.domains.audit import service as audit
from app.domains.auth.cookies import clear_refresh_cookie_headers
from app.domains.auth.errors import (
    AccountDisabled,
    CodeExpired,
    InvalidCode,
    PlatformAccount,
    TooManyAttempts,
)
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.outbox.sms import otp_event
from app.domains.rbac.models import UserRole
from app.domains.rbac.principal import Principal, RoleGrant
from app.domains.rbac.roles import Role
from app.domains.tenants.models import Tenant
from app.domains.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


@dataclass(frozen=True, slots=True)
class MfaPending:
    mfa_token: str


@dataclass(frozen=True, slots=True)
class OtpIssued:
    challenge_id: uuid.UUID
    expires_in: int
    resend_after: int
    # The outbox event that will text the code; None when nothing is sent.
    delivery_event_id: uuid.UUID | None = None


def _truncate(value: str | None, length: int) -> str | None:
    return value[:length] if value else value


def _session_ended() -> Unauthenticated:
    return Unauthenticated(
        "Your session has ended. Sign in again.", headers=clear_refresh_cookie_headers()
    )


# --- OTP ------------------------------------------------------------------------


def _generate_code(length: int) -> str:
    return f"{secrets.randbelow(10**length):0{length}d}"


def _hash_code(challenge_id: uuid.UUID, code: str) -> str:
    # Binding the challenge id into the HMAC means a leaked hash is useless
    # for any other challenge, and identical codes never hash alike.
    secret = get_settings().otp_hmac_secret.get_secret_value()
    return hmac_hex(secret, f"{challenge_id}:{code}")


def _code_matches(challenge: OtpChallenge, code: str) -> bool:
    settings = get_settings()
    if constant_time_equals(challenge.code_hash, _hash_code(challenge.id, code)):
        return True
    # fixed_otp_enabled is always False in production, whatever DEV_FIXED_OTP says.
    return settings.fixed_otp_enabled and constant_time_equals(code, settings.dev_fixed_otp_code)


async def _find_user(db: AsyncSession, tenant_id: uuid.UUID | None, phone: str) -> User | None:
    tenant_clause = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
    user = await db.scalar(select(User).where(tenant_clause, User.phone == phone))
    # Tenant-less users must be platform administrators; anything else is not
    # a valid platform login.
    is_platform_admin = user is not None and any(r.role is Role.PLATFORM_ADMIN for r in user.roles)
    if tenant_id is None and not is_platform_admin:
        return None
    return user


async def request_otp(
    db: AsyncSession, redis: Redis, *, tenant: Tenant | None, phone: str
) -> OtpIssued:
    """Create a challenge and queue its code for SMS in the same transaction.

    The text itself is sent from the outbox after the request commits (the
    caller queues `deliver_event`), so a slow or failing SMS provider never
    holds up the response; the dispatcher retries what failed.
    """
    settings = get_settings()
    client = get_client()

    # Rate limits come first, before any write or SMS. Keys are per phone
    # (across tenants) and per client IP, to blunt SMS pumping.
    await enforce_cooldown(redis, f"otp:cooldown:{phone}", settings.otp_resend_seconds)
    await enforce_window(redis, f"otp:hourly:{phone}", settings.otp_max_per_hour, 3600)
    if client.ip:
        await enforce_window(redis, f"otp:ip:{client.ip}", settings.otp_max_per_ip_per_hour, 3600)

    code = _generate_code(settings.otp_length)
    challenge = OtpChallenge(
        id=uuid.uuid4(),
        tenant_id=tenant.id if tenant else None,
        phone=phone,
        expires_at=utcnow() + timedelta(seconds=settings.otp_ttl_seconds),
        ip=client.ip,
        user_agent=_truncate(client.user_agent, 400),
    )
    challenge.code_hash = _hash_code(challenge.id, code)

    deliver = True
    event_id: uuid.UUID | None = None
    async with acting_as(db, challenge.tenant_id, reason="platform admin OTP request"):
        if tenant is None:
            # Without X-Tenant only platform administrators can sign in. Create
            # the challenge either way so the response doesn't reveal whether
            # the number has an account, but only text real administrators.
            deliver = await _find_user(db, None, phone) is not None
        db.add(challenge)
        await db.flush()
        if deliver:
            event = otp_event(
                tenant_id=challenge.tenant_id,
                challenge_id=challenge.id,
                phone=phone,
                code=code,
                expires_at=challenge.expires_at,
            )
            db.add(event)
            await db.flush()
            event_id = event.id

    if not deliver:
        logger.info(
            "OTP requested without tenant for a non-admin number",
            extra=log_fields(phone=mask_phone(phone)),
        )
    return OtpIssued(
        challenge_id=challenge.id,
        expires_in=settings.otp_ttl_seconds,
        resend_after=settings.otp_resend_seconds,
        delivery_event_id=event_id,
    )


async def _register_citizen(db: AsyncSession, tenant_id: uuid.UUID, phone: str) -> User:
    """Create a citizen account for a first-time phone number.

    ON CONFLICT DO NOTHING makes two simultaneous first logins for the same
    number converge on one account instead of one of them failing.
    """
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    new_id = await db.scalar(
        pg_insert(User)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, phone=phone, locale=tenant.default_locale)
        .on_conflict_do_nothing(constraint="uq_users_tenant_id_phone")
        .returning(User.id)
    )
    if new_id is not None:
        db.add(UserRole(tenant_id=tenant_id, user_id=new_id, role=Role.CITIZEN))
        await db.flush()
        await audit.record(
            db,
            action="user.registered",
            entity_type="user",
            entity_id=new_id,
            actor_id=new_id,
            tenant_id=tenant_id,
            after={"roles": [Role.CITIZEN.value], "via": "otp"},
        )
    user = await db.scalar(
        select(User)
        .where(User.tenant_id == tenant_id, User.phone == phone)
        .execution_options(populate_existing=True)
    )
    assert user is not None
    return user


async def verify_otp(
    db: AsyncSession, *, challenge_id: uuid.UUID, code: str, header_tenant: Tenant | None
) -> IssuedTokens | MfaPending:
    settings = get_settings()

    async with rls_bypass(db, reason="OTP challenge lookup by id"):
        challenge = await db.scalar(
            select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update()
        )
    if challenge is None or (header_tenant is not None and challenge.tenant_id != header_tenant.id):
        raise CodeExpired()

    async with acting_as(db, challenge.tenant_id, reason="platform admin OTP verify"):
        now = utcnow()
        if challenge.consumed_at is not None or challenge.expires_at <= now:
            raise CodeExpired()
        if challenge.attempts >= settings.otp_max_attempts:
            raise TooManyAttempts()

        user = await _find_user(db, challenge.tenant_id, challenge.phone)
        no_platform_account = challenge.tenant_id is None and user is None
        if no_platform_account or not _code_matches(challenge, code):
            challenge.attempts += 1
            remaining = settings.otp_max_attempts - challenge.attempts
            await db.flush()
            await db.commit()  # the failed attempt must survive the error response
            if remaining <= 0:
                raise TooManyAttempts()
            raise InvalidCode(details={"attempts_remaining": remaining})

        challenge.consumed_at = now
        if user is None:
            assert challenge.tenant_id is not None
            # A platform administrator's number is never auto-registered as a
            # citizen: the web app always sends X-Tenant, and silently minting
            # a tenant account for the platform admin would be surprising and
            # hard to undo. Checked only after the code is proven, so it
            # reveals nothing to someone who doesn't hold the phone.
            async with rls_bypass(db, reason="platform admin phone check"):
                is_platform_admin = await _find_user(db, None, challenge.phone) is not None
            if is_platform_admin:
                raise PlatformAccount()
            user = await _register_citizen(db, challenge.tenant_id, challenge.phone)
        if not user.is_active:
            raise AccountDisabled()

        if user.mfa_enabled:
            challenge.user_id = user.id
            await db.flush()
            return MfaPending(encode_mfa_token(user.id, user.tenant_id, challenge.id))

        return await issue_session(db, user, mfa_verified=False)


# --- sessions ------------------------------------------------------------------------


async def issue_session(db: AsyncSession, user: User, *, mfa_verified: bool) -> IssuedTokens:
    """Start a new session family. Call inside the user's tenant context."""
    settings = get_settings()
    client = get_client()
    now = utcnow()
    refresh_token = new_opaque_token()
    row = AuthSession(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        family_id=uuid.uuid4(),
        refresh_token_hash=hash_token(refresh_token),
        mfa_verified=mfa_verified,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
        ip=client.ip,
        user_agent=_truncate(client.user_agent, 400),
    )
    db.add(row)
    user.last_login_at = now
    await db.flush()
    await audit.record(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        tenant_id=user.tenant_id,
        after={"session_family": str(row.family_id), "mfa_verified": mfa_verified},
    )
    return IssuedTokens(
        access_token=encode_access_token(user.id, user.tenant_id, row.id),
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_seconds,
        user=user,
    )


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID, reason: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
        .execution_options(synchronize_session=False)
    )


async def refresh(db: AsyncSession, token: str) -> IssuedTokens:
    settings = get_settings()
    client = get_client()

    # FOR UPDATE serialises concurrent refreshes of the same token: the
    # second waits, then sees the first one's rotation.
    async with rls_bypass(db, reason="refresh token lookup by hash"):
        current = await db.scalar(
            select(AuthSession)
            .where(AuthSession.refresh_token_hash == hash_token(token))
            .with_for_update()
        )
    if current is None:
        raise _session_ended()

    async with acting_as(db, current.tenant_id, reason="platform admin session refresh"):
        now = utcnow()
        if current.revoked_at is not None or current.expires_at <= now:
            raise _session_ended()

        if current.rotated_at is not None:
            grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
            if now - current.rotated_at > grace:
                # A rotated token came back: either it was stolen or the
                # legitimate client is replaying it. Either way, end the
                # whole family so the thief's copy dies too.
                await _revoke_family(db, current.family_id, "reuse_detected")
                await audit.record(
                    db,
                    action="auth.refresh_reuse_detected",
                    entity_type="user",
                    entity_id=current.user_id,
                    tenant_id=current.tenant_id,
                    after={"session_family": str(current.family_id)},
                )
                await db.commit()
                logger.warning(
                    "refresh token reuse detected; session family revoked",
                    extra=log_fields(family_id=str(current.family_id)),
                )
                raise _session_ended()
            # Within the grace window this is two tabs refreshing at once;
            # give the late one a sibling token rather than logging out both.

        user = await db.get(User, current.user_id)
        if user is None or not user.is_active:
            await _revoke_family(db, current.family_id, "user_inactive")
            await db.commit()
            raise _session_ended()

        if current.rotated_at is None:
            current.rotated_at = now
        new_token = new_opaque_token()
        child = AuthSession(
            id=uuid.uuid4(),
            tenant_id=current.tenant_id,
            user_id=current.user_id,
            family_id=current.family_id,
            parent_id=current.id,
            refresh_token_hash=hash_token(new_token),
            mfa_verified=current.mfa_verified,
            expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            ip=client.ip,
            user_agent=_truncate(client.user_agent, 400),
        )
        db.add(child)
        await db.flush()

    return IssuedTokens(
        access_token=encode_access_token(user.id, user.tenant_id, child.id),
        refresh_token=new_token,
        expires_in=settings.access_token_ttl_seconds,
        user=user,
    )


async def logout(db: AsyncSession, principal: Principal) -> None:
    async with acting_as(db, principal.tenant_id, reason="platform admin logout"):
        family_id = await db.scalar(
            select(AuthSession.family_id).where(AuthSession.id == principal.session_id)
        )
        if family_id is not None:
            await _revoke_family(db, family_id, "logout")
        await audit.record(
            db,
            action="auth.logout",
            entity_type="user",
            entity_id=principal.user_id,
            actor=principal,
        )


async def revoke_all_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    *,
    reason: str,
    actor: Principal,
) -> None:
    """End every session of a user (self-service, or an admin deactivating them)."""
    async with acting_as(db, tenant_id, reason="platform admin revoking sessions"):
        await db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason=reason)
            .execution_options(synchronize_session=False)
        )
        await audit.record(
            db,
            action="auth.sessions_revoked",
            entity_type="user",
            entity_id=user_id,
            actor=actor,
            tenant_id=tenant_id,
            after={"reason": reason},
        )


async def load_principal(db: AsyncSession, claims: AccessClaims) -> Principal:
    """Resolve an access token to a principal, checking the session every time.

    Checking the session row on each request is what makes logout, revoke-all
    and deactivation take effect immediately rather than when the access token
    expires. Roles are read fresh too, so role changes apply at once.
    """
    async with acting_as(db, claims.tenant_id, reason="platform admin session check"):
        row = await db.get(AuthSession, claims.session_id)
        user = await db.get(User, claims.user_id) if row is not None else None

    ended = Unauthenticated("Your session has ended. Sign in again.")
    if row is None or user is None or row.user_id != user.id:
        raise ended
    if row.revoked_at is not None or row.expires_at <= utcnow():
        raise ended
    if not user.is_active or user.tenant_id != claims.tenant_id:
        raise ended

    grants = tuple(RoleGrant(r.role, r.department_id, r.jurisdiction_id) for r in user.roles)
    if claims.tenant_id is None and not any(g.role is Role.PLATFORM_ADMIN for g in grants):
        raise ended
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        session_id=row.id,
        grants=grants,
        mfa_verified=row.mfa_verified,
    )
