"""Phone OTP login, refresh-token rotation, logout and session revocation."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Environment, Settings
from tests.factories import TenantRow, create_tenant, create_user, unique_phone
from tests.helpers import RecordingSms, bearer, login, request_otp, verify_otp


@pytest.fixture
async def tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


async def _scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


# --- OTP login -----------------------------------------------------------------------


async def test_otp_login_auto_creates_a_citizen(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    phone = unique_phone()
    requested = await request_otp(client, phone, tenant.slug)
    assert requested.status_code == 200
    body = requested.json()
    assert set(body) == {"challenge_id", "expires_in", "resend_after"}
    assert body["expires_in"] == 300
    assert body["resend_after"] == 30

    verified = await verify_otp(client, body["challenge_id"], sms.codes[phone], tenant.slug)
    assert verified.status_code == 200, verified.text
    tokens = verified.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 900
    assert tokens["refresh_token"]
    user = tokens["user"]
    assert user["phone"] == phone
    assert user["tenant_id"] == str(tenant.id)
    assert user["is_staff"] is False
    assert user["roles"] == [{"role": "citizen", "department_id": None, "jurisdiction_id": None}]
    assert "report:create" in user["permissions"]
    assert "user:manage" not in user["permissions"]

    cookie = verified.headers["set-cookie"]
    assert cookie.startswith(f"cp_refresh={tokens['refresh_token']};")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Secure" not in cookie  # not production
    assert verified.headers["cache-control"] == "no-store"

    me = await client.get("/api/v1/users/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json() == user

    role = await _scalar(
        owner_engine,
        "SELECT r.role::text FROM user_roles r JOIN users u ON u.id = r.user_id "
        "WHERE u.phone = :phone AND u.tenant_id = :tenant",
        phone=phone,
        tenant=tenant.id,
    )
    assert role == "citizen"
    # Only an HMAC of the code is stored.
    stored = await _scalar(
        owner_engine, "SELECT code_hash FROM otp_challenges WHERE id = :id", id=body["challenge_id"]
    )
    assert stored != sms.codes[phone]
    assert len(str(stored)) == 64


async def test_second_login_reuses_the_account(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, redis: object
) -> None:
    phone = unique_phone()
    first = await login(client, sms, phone, tenant.slug)
    await redis.delete(f"otp:cooldown:{phone}")  # type: ignore[attr-defined]
    second = await login(client, sms, phone, tenant.slug)
    assert first.user["id"] == second.user["id"]


async def test_indian_numbers_are_normalised(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    phone = unique_phone()
    local = phone.removeprefix("+91")
    response = await request_otp(client, local, tenant.slug)
    assert response.status_code == 200
    assert phone in sms.codes


async def test_invalid_phone_is_rejected(client: httpx.AsyncClient, tenant: TenantRow) -> None:
    response = await request_otp(client, "12345", tenant.slug)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_tenant_is_404(client: httpx.AsyncClient) -> None:
    response = await request_otp(client, unique_phone(), "no-such-city")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_wrong_code_is_counted_even_though_the_request_fails(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    wrong = "111111" if sms.codes[phone] != "111111" else "222222"

    response = await verify_otp(client, challenge_id, wrong, tenant.slug)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"
    assert response.json()["error"]["details"] == {"attempts_remaining": 4}
    attempts = await _scalar(
        owner_engine, "SELECT attempts FROM otp_challenges WHERE id = :id", id=challenge_id
    )
    assert attempts == 1


async def test_attempt_limit_locks_the_challenge(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    correct = sms.codes[phone]
    wrong = "111111" if correct != "111111" else "222222"

    codes = [(await verify_otp(client, challenge_id, wrong)).status_code for _ in range(5)]
    assert codes == [400, 400, 400, 400, 429]
    # Even the right code is refused now.
    locked = await verify_otp(client, challenge_id, correct)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_attempts"


async def test_expired_challenge_is_rejected(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE otp_challenges SET expires_at = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": challenge_id},
        )
    response = await verify_otp(client, challenge_id, sms.codes[phone])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "code_expired"


async def test_a_code_works_only_once(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    assert (await verify_otp(client, challenge_id, sms.codes[phone])).status_code == 200
    again = await verify_otp(client, challenge_id, sms.codes[phone])
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "code_expired"


async def test_challenge_cannot_be_redeemed_under_another_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        other = await create_tenant(conn)
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    response = await verify_otp(client, challenge_id, sms.codes[phone], other.slug)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "code_expired"


async def test_otp_requests_are_rate_limited_per_phone(
    client: httpx.AsyncClient, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    phone = unique_phone()
    assert (await request_otp(client, phone, tenant.slug)).status_code == 200
    # Same phone through a different tenant shares the limit.
    async with owner_engine.begin() as conn:
        other = await create_tenant(conn)
    again = await request_otp(client, phone, other.slug)
    assert again.status_code == 429
    error = again.json()["error"]
    assert error["code"] == "rate_limited"
    assert 0 < error["details"]["retry_after"] <= 30
    assert again.headers["retry-after"] == str(error["details"]["retry_after"])


async def test_hourly_otp_limit(
    client: httpx.AsyncClient, tenant: TenantRow, redis: object, settings: Settings
) -> None:
    phone = unique_phone()
    statuses = []
    for _ in range(settings.otp_max_per_hour + 1):
        await redis.delete(f"otp:cooldown:{phone}")  # type: ignore[attr-defined]
        statuses.append((await request_otp(client, phone, tenant.slug)).status_code)
    assert statuses == [200] * settings.otp_max_per_hour + [429]


async def test_fixed_dev_code_works_outside_production_only(
    client: httpx.AsyncClient,
    tenant: TenantRow,
    redis: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "dev_fixed_otp", True)
    phone = unique_phone()
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    assert (await verify_otp(client, challenge_id, "000000")).status_code == 200

    monkeypatch.setattr(settings, "env", Environment.PRODUCTION)
    await redis.delete(f"otp:cooldown:{phone}")  # type: ignore[attr-defined]
    challenge_id = (await request_otp(client, phone, tenant.slug)).json()["challenge_id"]
    refused = await verify_otp(client, challenge_id, "000000")
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_code"


async def test_deactivated_account_cannot_log_in(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, tenant.id, "operator", is_active=False)
    challenge_id = (await request_otp(client, user.phone, tenant.slug)).json()["challenge_id"]
    response = await verify_otp(client, challenge_id, sms.codes[user.phone])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


# --- platform administrators -------------------------------------------------------------


async def test_platform_admin_logs_in_without_a_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        admin = await create_user(conn, None, "platform_admin")
    session = await login(client, sms, admin.phone, None)
    assert session.user["tenant_id"] is None
    assert session.user["permissions"] == ["tenant:manage"]
    me = await client.get("/api/v1/users/me", headers=session.headers)
    assert me.status_code == 200
    assert me.json()["id"] == str(admin.id)


async def test_no_tenant_login_for_a_non_admin_sends_nothing_and_fails(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "dev_fixed_otp", True)
    phone = unique_phone()
    response = await request_otp(client, phone, None)
    # Same response shape as a real admin gets, so the number isn't revealed...
    assert response.status_code == 200
    # ...but no SMS goes out, and even the dev code can't complete the login.
    assert phone not in sms.codes
    verified = await verify_otp(client, response.json()["challenge_id"], "000000")
    assert verified.status_code == 400
    assert verified.json()["error"]["code"] == "invalid_code"


# --- refresh rotation ----------------------------------------------------------------------


async def _refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def test_refresh_rotates_the_token(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    rotated = await _refresh(client, session.refresh_token)
    assert rotated.status_code == 200
    body = rotated.json()
    assert body["refresh_token"] != session.refresh_token
    assert body["user"]["id"] == session.user["id"]
    assert (
        await client.get("/api/v1/users/me", headers=bearer(body["access_token"]))
    ).status_code == 200
    # The original access token stays valid until it expires; rotation is not revocation.
    assert (await client.get("/api/v1/users/me", headers=session.headers)).status_code == 200


async def test_refresh_token_reuse_revokes_the_whole_family(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    first = (await _refresh(client, session.refresh_token)).json()
    second = (await _refresh(client, first["refresh_token"])).json()

    # Replaying the original (already rotated) token is treated as theft.
    replay = await _refresh(client, session.refresh_token)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "unauthenticated"
    assert "cp_refresh=" in replay.headers["set-cookie"]  # cookie cleared

    # Every token and session in the family is now dead, including the newest.
    assert (await _refresh(client, second["refresh_token"])).status_code == 401
    for access in (session.access_token, first["access_token"], second["access_token"]):
        assert (await client.get("/api/v1/users/me", headers=bearer(access))).status_code == 401

    reasons = await _scalar(
        owner_engine,
        "SELECT array_agg(DISTINCT revoked_reason) FROM auth_sessions s "
        "JOIN users u ON u.id = s.user_id WHERE u.id = :id",
        id=session.user["id"],
    )
    assert reasons == ["reuse_detected"]


async def test_refresh_within_grace_window_is_not_treated_as_theft(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    tenant: TenantRow,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 30)
    session = await login(client, sms, unique_phone(), tenant.slug)
    # Two tabs refreshing with the same token at the same moment.
    a, b = await asyncio.gather(
        _refresh(client, session.refresh_token), _refresh(client, session.refresh_token)
    )
    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json()["refresh_token"] != b.json()["refresh_token"]
    for response in (a, b):
        follow_up = await _refresh(client, response.json()["refresh_token"])
        assert follow_up.status_code == 200


async def test_concurrent_reuse_outside_grace_revokes_family(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    a, b = await asyncio.gather(
        _refresh(client, session.refresh_token), _refresh(client, session.refresh_token)
    )
    # Row locking serialises them: exactly one rotation wins, the other is reuse.
    assert sorted([a.status_code, b.status_code]) == [200, 401]
    winner = a if a.status_code == 200 else b
    assert (await _refresh(client, winner.json()["refresh_token"])).status_code == 401


async def test_refresh_with_the_cookie(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    # The login response set cp_refresh in the client's cookie jar.
    assert client.cookies.get("cp_refresh") == session.refresh_token
    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    assert client.cookies.get("cp_refresh") == rotated.json()["refresh_token"]


async def test_refresh_without_any_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_refresh_with_garbage_token(client: httpx.AsyncClient) -> None:
    response = await _refresh(client, "not-a-real-token")
    assert response.status_code == 401


# --- logout and revocation ------------------------------------------------------------


async def test_logout_takes_effect_immediately(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    response = await client.post("/api/v1/auth/logout", headers=session.headers)
    assert response.status_code == 204
    assert 'cp_refresh=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]

    # The access token is still unexpired, but its session is gone.
    me = await client.get("/api/v1/users/me", headers=session.headers)
    assert me.status_code == 401
    assert (await _refresh(client, session.refresh_token)).status_code == 401


async def test_logout_only_ends_the_current_session(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, redis: object
) -> None:
    phone = unique_phone()
    laptop = await login(client, sms, phone, tenant.slug)
    await redis.delete(f"otp:cooldown:{phone}")  # type: ignore[attr-defined]
    phone_app = await login(client, sms, phone, tenant.slug)
    await client.post("/api/v1/auth/logout", headers=laptop.headers)
    assert (await client.get("/api/v1/users/me", headers=phone_app.headers)).status_code == 200


async def test_revoke_all_ends_every_session(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, redis: object
) -> None:
    phone = unique_phone()
    laptop = await login(client, sms, phone, tenant.slug)
    await redis.delete(f"otp:cooldown:{phone}")  # type: ignore[attr-defined]
    phone_app = await login(client, sms, phone, tenant.slug)
    response = await client.post("/api/v1/auth/sessions/revoke-all", headers=laptop.headers)
    assert response.status_code == 204
    for session in (laptop, phone_app):
        assert (await client.get("/api/v1/users/me", headers=session.headers)).status_code == 401
        assert (await _refresh(client, session.refresh_token)).status_code == 401


async def test_deactivating_a_user_ends_their_sessions_at_once(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, owner_engine: AsyncEngine
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": session.user["id"]}
        )
    assert (await client.get("/api/v1/users/me", headers=session.headers)).status_code == 401
    assert (await _refresh(client, session.refresh_token)).status_code == 401


# --- access tokens -------------------------------------------------------------------------


async def test_missing_and_malformed_tokens(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/users/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthenticated"
    assert missing.headers["www-authenticate"] == "Bearer"

    garbage = await client.get("/api/v1/users/me", headers=bearer("not.a.jwt"))
    assert garbage.status_code == 401
    assert garbage.json()["error"]["code"] == "unauthenticated"


async def test_expired_access_token(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    tenant: TenantRow,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "access_token_ttl_seconds", -1)
    session = await login(client, sms, unique_phone(), tenant.slug)
    response = await client.get("/api/v1/users/me", headers=session.headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


async def test_token_signed_with_another_key_is_rejected(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    import jwt

    session = await login(client, sms, unique_phone(), tenant.slug)
    claims = jwt.decode(session.access_token, options={"verify_signature": False})
    forged = jwt.encode(claims, "attacker-secret-attacker-secret-0000", algorithm="HS256")
    assert (await client.get("/api/v1/users/me", headers=bearer(forged))).status_code == 401


async def test_mfa_token_cannot_be_used_as_access_token(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    from app.core.security import encode_mfa_token

    session = await login(client, sms, unique_phone(), tenant.slug)
    import uuid

    token = encode_mfa_token(uuid.UUID(session.user["id"]), tenant.id, uuid.uuid4())
    assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 401


# --- profile ---------------------------------------------------------------------------------


async def test_update_own_profile(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    response = await client.patch(
        "/api/v1/users/me",
        headers=session.headers,
        json={
            "display_name": "Asha",
            "email": "asha@example.com",
            "locale": "hi",
            "preferences": {"notifications": {"sms": False}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Asha"
    assert body["email"] == "asha@example.com"
    assert body["locale"] == "hi"
    assert body["preferences"] == {"notifications": {"sms": False}}


async def test_profile_rejects_unsupported_locale_and_unknown_fields(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    session = await login(client, sms, unique_phone(), tenant.slug)
    bad_locale = await client.patch(
        "/api/v1/users/me", headers=session.headers, json={"locale": "fr"}
    )
    assert bad_locale.status_code == 422
    assert bad_locale.json()["error"]["details"]["supported_locales"] == ["en", "hi"]

    # Users can't grant themselves anything through the profile endpoint.
    escalate = await client.patch(
        "/api/v1/users/me", headers=session.headers, json={"is_active": True, "roles": []}
    )
    assert escalate.status_code == 422


async def test_email_must_be_unique_within_a_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    first = await login(client, sms, unique_phone(), tenant.slug)
    second = await login(client, sms, unique_phone(), tenant.slug)
    await client.patch("/api/v1/users/me", headers=first.headers, json={"email": "dup@example.com"})
    clash = await client.patch(
        "/api/v1/users/me", headers=second.headers, json={"email": "DUP@example.com"}
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "conflict"


async def test_tenants_current(client: httpx.AsyncClient, tenant: TenantRow) -> None:
    response = await client.get("/api/v1/tenants/current", headers={"X-Tenant": tenant.slug})
    assert response.status_code == 200
    assert response.json() == {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": "Test City",
        "default_locale": "en",
        "supported_locales": ["en", "hi"],
        "map": None,  # no jurisdictions, so no map view (see test_geo.py)
    }
    missing = await client.get("/api/v1/tenants/current")
    assert missing.status_code == 422
    unknown = await client.get("/api/v1/tenants/current", headers={"X-Tenant": "nowhere"})
    assert unknown.status_code == 404
