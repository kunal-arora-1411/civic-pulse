"""Cryptographic primitives: token hashing, JWTs and secret encryption."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings
from app.core.errors import TokenExpired, Unauthenticated

TokenType = Literal["access", "mfa"]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_opaque_token() -> str:
    """A 256-bit random token, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a high-entropy token. Salting isn't needed at 256 bits of entropy."""
    return hashlib.sha256(token.encode()).hexdigest()


def hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- JWTs ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    session_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MfaClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    challenge_id: uuid.UUID


def _audience(settings: Settings, typ: TokenType) -> str:
    # Distinct audiences mean an MFA token can never be replayed as an access
    # token, even if a check on `typ` were forgotten somewhere.
    return settings.jwt_audience if typ == "access" else f"{settings.jwt_audience}:mfa"


def _encode(typ: TokenType, subject: uuid.UUID, ttl: int, claims: dict[str, Any]) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "iss": settings.jwt_issuer,
        "aud": _audience(settings, typ),
        "sub": str(subject),
        "typ": typ,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def _decode(token: str, typ: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=_audience(settings, typ),
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "typ", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("The token is invalid.") from exc
    if payload.get("typ") != typ:
        raise Unauthenticated("The token is invalid.")
    return payload


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def encode_access_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID | None, session_id: uuid.UUID
) -> str:
    return _encode(
        "access",
        user_id,
        get_settings().access_token_ttl_seconds,
        {"tid": str(tenant_id) if tenant_id else None, "sid": str(session_id)},
    )


def decode_access_token(token: str) -> AccessClaims:
    payload = _decode(token, "access")
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=_uuid_or_none(payload.get("tid")),
            session_id=uuid.UUID(payload["sid"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise Unauthenticated("The token is invalid.") from exc


def encode_mfa_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID | None, challenge_id: uuid.UUID
) -> str:
    return _encode(
        "mfa",
        user_id,
        get_settings().mfa_token_ttl_seconds,
        {"tid": str(tenant_id) if tenant_id else None, "cid": str(challenge_id)},
    )


def decode_mfa_token(token: str) -> MfaClaims:
    payload = _decode(token, "mfa")
    try:
        return MfaClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=_uuid_or_none(payload.get("tid")),
            challenge_id=uuid.UUID(payload["cid"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise Unauthenticated("The token is invalid.") from exc


# --- secrets at rest -------------------------------------------------------------


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().totp_encryption_key.get_secret_value().encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:  # wrong key, or tampered ciphertext
        raise RuntimeError("Could not decrypt a stored secret") from exc
