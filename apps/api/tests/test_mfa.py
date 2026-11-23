"""Staff TOTP: setup, enable, MFA login, and the REQUIRE_STAFF_MFA gate."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI
from pyotp.totp import TOTP
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.domains.auth.sms import get_sms_provider
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.main import create_app
from tests.factories import TenantRow, UserRow, create_tenant, create_user
from tests.helpers import RecordingSms, Session, bearer, login, start_login


def current_step() -> int:
    return int(time.time()) // 30


def code_at(secret: str, step: int) -> str:
    return TOTP(secret).at(step * 30)


def totp_code(secret: str) -> str:
    return code_at(secret, current_step())


@dataclass
class Enrolment:
    secret: str
    step: int  # the time step consumed by /mfa/enable

    def next_code(self) -> str:
        """A code that is fresh (not replayed) and within the drift window."""
        return code_at(self.secret, self.step + 1)


@pytest.fixture
async def tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


@pytest.fixture
async def operator(owner_engine: AsyncEngine, tenant: TenantRow) -> UserRow:
    async with owner_engine.begin() as conn:
        return await create_user(conn, tenant.id, "operator")


async def enrol(client: httpx.AsyncClient, session: Session) -> Enrolment:
    setup = await client.post("/api/v1/auth/mfa/setup", headers=session.headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    step = current_step()
    enabled = await client.post(
        "/api/v1/auth/mfa/enable", headers=session.headers, json={"code": code_at(secret, step)}
    )
    assert enabled.status_code == 204, enabled.text
    return Enrolment(secret, step)


async def test_citizens_cannot_set_up_mfa(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    async with owner_engine.begin() as conn:
        citizen = await create_user(conn, tenant.id, "citizen")
    session = await login(client, sms, citizen.phone, tenant.slug)
    response = await client.post("/api/v1/auth/mfa/setup", headers=session.headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_setup_and_enable(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    operator: UserRow,
    tenant: TenantRow,
    owner_engine: AsyncEngine,
) -> None:
    session = await login(client, sms, operator.phone, tenant.slug)
    setup = await client.post("/api/v1/auth/mfa/setup", headers=session.headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/CivicPulse:")

    # The secret is encrypted at rest.
    async with owner_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT mfa_secret_encrypted FROM users WHERE id = :id"), {"id": operator.id}
            )
        ).scalar_one()
    assert secret not in stored

    wrong = await client.post(
        "/api/v1/auth/mfa/enable", headers=session.headers, json={"code": "000000"}
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_code"

    ok = await client.post(
        "/api/v1/auth/mfa/enable", headers=session.headers, json={"code": totp_code(secret)}
    )
    assert ok.status_code == 204
    me = await client.get("/api/v1/users/me", headers=session.headers)
    assert me.json()["mfa_enabled"] is True

    again = await client.post("/api/v1/auth/mfa/setup", headers=session.headers)
    assert again.status_code == 409


async def test_enable_without_setup_is_a_conflict(
    client: httpx.AsyncClient, sms: RecordingSms, operator: UserRow, tenant: TenantRow
) -> None:
    session = await login(client, sms, operator.phone, tenant.slug)
    response = await client.post(
        "/api/v1/auth/mfa/enable", headers=session.headers, json={"code": "123456"}
    )
    assert response.status_code == 409


async def test_login_with_mfa_enabled_requires_totp(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    operator: UserRow,
    tenant: TenantRow,
    redis: object,
) -> None:
    enrolment = await enrol(client, await login(client, sms, operator.phone, tenant.slug))
    await redis.delete(f"otp:cooldown:{operator.phone}")  # type: ignore[attr-defined]

    client.cookies.clear()
    pending = await start_login(client, sms, operator.phone, tenant.slug)
    assert pending["mfa_required"] is True
    assert set(pending) == {"mfa_required", "mfa_token"}
    assert "cp_refresh" not in client.cookies  # no session yet

    # The mfa_token is not an access token.
    assert (
        await client.get("/api/v1/users/me", headers=bearer(pending["mfa_token"]))
    ).status_code == 401

    wrong = await client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_token": pending["mfa_token"], "code": "000000"}
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["details"]["attempts_remaining"] == 4

    # The code used to enable MFA moments ago can't be replayed...
    replay = await client.post(
        "/api/v1/auth/mfa/verify",
        json={
            "mfa_token": pending["mfa_token"],
            "code": code_at(enrolment.secret, enrolment.step),
        },
    )
    assert replay.status_code == 400
    # ...but the next one (within the drift window) works.
    verified = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": pending["mfa_token"], "code": enrolment.next_code()},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["user"]["mfa_enabled"] is True
    assert client.cookies.get("cp_refresh") == verified.json()["refresh_token"]

    # The mfa_token is single-use.
    reused = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": pending["mfa_token"], "code": enrolment.next_code()},
    )
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "challenge_expired"


async def test_mfa_attempts_are_limited(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    operator: UserRow,
    tenant: TenantRow,
    redis: object,
) -> None:
    enrolment = await enrol(client, await login(client, sms, operator.phone, tenant.slug))
    await redis.delete(f"otp:cooldown:{operator.phone}")  # type: ignore[attr-defined]
    pending = await start_login(client, sms, operator.phone, tenant.slug)
    statuses = []
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/mfa/verify", json={"mfa_token": pending["mfa_token"], "code": "000000"}
        )
        statuses.append(response.status_code)
    assert statuses == [400, 400, 400, 400, 429]
    locked = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": pending["mfa_token"], "code": enrolment.next_code()},
    )
    assert locked.status_code == 429


async def test_expired_mfa_token(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    operator: UserRow,
    tenant: TenantRow,
    redis: object,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrolment = await enrol(client, await login(client, sms, operator.phone, tenant.slug))
    await redis.delete(f"otp:cooldown:{operator.phone}")  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "mfa_token_ttl_seconds", -1)
    pending = await start_login(client, sms, operator.phone, tenant.slug)
    response = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": pending["mfa_token"], "code": enrolment.next_code()},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


# --- REQUIRE_STAFF_MFA ---------------------------------------------------------------


@pytest.fixture
async def probe_client(sms: RecordingSms) -> AsyncIterator[httpx.AsyncClient]:
    """An app with one route that needs a staff permission."""
    application: FastAPI = create_app()
    application.dependency_overrides[get_sms_provider] = lambda: sms

    @application.get("/probe")
    async def probe(
        principal: Annotated[Principal, require(Permission.CONFIG_READ)],
    ) -> dict[str, str]:
        return {"user_id": str(principal.user_id)}

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_staff_permissions_need_mfa_when_required(
    probe_client: httpx.AsyncClient,
    sms: RecordingSms,
    operator: UserRow,
    tenant: TenantRow,
    owner_engine: AsyncEngine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    redis: object,
) -> None:
    client = probe_client
    session = await login(client, sms, operator.phone, tenant.slug)
    async with owner_engine.begin() as conn:
        citizen = await create_user(conn, tenant.id, "citizen")
    citizen_session = await login(client, sms, citizen.phone, tenant.slug)

    # Off (the development default): no MFA needed.
    assert (await client.get("/probe", headers=session.headers)).status_code == 200

    monkeypatch.setattr(settings, "require_staff_mfa", True)
    blocked = await client.get("/probe", headers=session.headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "mfa_required"
    # A citizen gets plain "forbidden": they lack the permission altogether.
    denied = await client.get("/probe", headers=citizen_session.headers)
    assert denied.json()["error"]["code"] == "forbidden"

    # Enrolling MFA verifies the current session on the spot.
    enrolment = await enrol(client, session)
    assert (await client.get("/probe", headers=session.headers)).status_code == 200

    # A fresh login goes through the TOTP step and is verified too, and the
    # verification survives refresh-token rotation.
    await redis.delete(f"otp:cooldown:{operator.phone}")  # type: ignore[attr-defined]
    pending = await start_login(client, sms, operator.phone, tenant.slug)
    verified = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": pending["mfa_token"], "code": enrolment.next_code()},
    )
    assert verified.status_code == 200
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": verified.json()["refresh_token"]}
    )
    assert refreshed.status_code == 200
    probe = await client.get("/probe", headers=bearer(refreshed.json()["access_token"]))
    assert probe.status_code == 200
