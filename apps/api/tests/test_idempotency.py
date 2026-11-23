"""Idempotency-Key on POST /admin/users."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import TenantRow, create_tenant, create_user, unique_phone
from tests.helpers import RecordingSms, Session, login

USERS = "/api/v1/admin/users"


@pytest.fixture
async def tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


async def _admin(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, tenant.id, "municipal_admin")
    return await login(client, sms, user.phone, tenant.slug)


@pytest.fixture
async def admin(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> Session:
    return await _admin(client, sms, owner_engine, tenant)


def _body(phone: str | None = None, name: str = "Idem Potent") -> dict:
    return {"phone": phone or unique_phone(), "display_name": name, "roles": [{"role": "operator"}]}


async def _post(
    client: httpx.AsyncClient, admin: Session, body: dict, key: str | None
) -> httpx.Response:
    headers = dict(admin.headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    return await client.post(USERS, headers=headers, json=body)


async def _users_with_phone(engine: AsyncEngine, phone: str) -> int:
    async with engine.connect() as conn:
        return (
            await conn.execute(text("SELECT count(*) FROM users WHERE phone = :p"), {"p": phone})
        ).scalar_one()


async def test_same_key_and_body_replays_the_response(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine
) -> None:
    key = uuid.uuid4().hex
    body = _body()
    first = await _post(client, admin, body, key)
    assert first.status_code == 201
    assert "idempotent-replayed" not in first.headers

    # Key order and whitespace in the JSON don't matter; the parsed body does.
    second = await client.post(
        USERS,
        headers={**admin.headers, "Idempotency-Key": key, "Content-Type": "application/json"},
        content='{"roles":[{"role":"operator"}], "display_name":"Idem Potent", '
        f'"phone":"{body["phone"]}"}}',
    )
    assert second.status_code == 201
    assert second.headers["idempotent-replayed"] == "true"
    assert second.json() == first.json()
    assert await _users_with_phone(owner_engine, body["phone"]) == 1


async def test_same_key_with_a_different_body_is_rejected(
    client: httpx.AsyncClient, admin: Session
) -> None:
    key = uuid.uuid4().hex
    assert (await _post(client, admin, _body(), key)).status_code == 201
    reused = await _post(client, admin, _body(), key)
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


async def test_concurrent_duplicates_create_one_user(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine
) -> None:
    key = uuid.uuid4().hex
    body = _body()
    responses = await asyncio.gather(*(_post(client, admin, body, key) for _ in range(5)))
    assert [r.status_code for r in responses] == [201] * 5
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(r.headers.get("idempotent-replayed") == "true" for r in responses) == 4
    assert await _users_with_phone(owner_engine, body["phone"]) == 1


async def test_concurrent_creates_with_different_keys_conflict_cleanly(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine
) -> None:
    body = _body()
    responses = await asyncio.gather(
        *(_post(client, admin, body, uuid.uuid4().hex) for _ in range(4))
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409, 409, 409]
    assert await _users_with_phone(owner_engine, body["phone"]) == 1


async def test_a_failed_request_can_be_retried_with_the_same_key(
    client: httpx.AsyncClient, admin: Session
) -> None:
    key = uuid.uuid4().hex
    bad = _body()
    bad["roles"] = [{"role": "operator", "department_id": str(uuid.uuid4())}]
    assert (await _post(client, admin, bad, key)).status_code == 422
    # Nothing was stored for the failed attempt, so the key is still free.
    assert (await _post(client, admin, _body(), key)).status_code == 201


async def test_keys_are_scoped_to_the_admin(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    admin: Session,
) -> None:
    other_admin = await _admin(client, sms, owner_engine, tenant)
    key = uuid.uuid4().hex
    assert (await _post(client, admin, _body(), key)).status_code == 201
    # The same key from another admin is a separate operation.
    assert (await _post(client, other_admin, _body(), key)).status_code == 201


async def test_requests_without_a_key_are_not_deduplicated(
    client: httpx.AsyncClient, admin: Session
) -> None:
    body = _body()
    assert (await _post(client, admin, body, None)).status_code == 201
    assert (await _post(client, admin, body, None)).status_code == 409


async def test_malformed_keys_are_rejected(client: httpx.AsyncClient, admin: Session) -> None:
    for key in ("x" * 256, "has space"):
        response = await _post(client, admin, _body(), key)
        assert response.status_code == 422, key
