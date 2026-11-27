"""The audit-chain endpoints: who may read them, and what they answer.

Signing in is itself audited, so a tenant's chain is never empty by the time a
test can call these endpoints. Expectations are therefore derived from the head the
status endpoint reports, not from the number of rows a test wrote.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import set_tenant, system_session
from app.domains.audit import checkpoints
from app.domains.audit.checkpoints import AnchorKey
from tests.factories import TenantRow, create_tenant, create_user, unique_phone
from tests.helpers import InlineJobs, RecordingSms, Session, login

CHAIN = "/api/v1/admin/audit-chain"
VERIFICATIONS = f"{CHAIN}/verifications"
CHECKPOINTS = f"{CHAIN}/checkpoints"
EVENTS = "/api/v1/admin/audit-events"
KEY = AnchorKey(key_id="k1", secret=b"an-api-test-anchor-key-long-enough")


@pytest.fixture
async def tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


@pytest.fixture
async def admin(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, tenant.id, "municipal_admin", display_name="Admin Asha")
    return await login(client, sms, user.phone, tenant.slug)


@pytest.fixture
async def operator(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, tenant.id, "operator")
    return await login(client, sms, user.phone, tenant.slug)


async def _events(owner_engine: AsyncEngine, tenant_id: uuid.UUID, count: int) -> None:
    async with owner_engine.begin() as conn:
        for index in range(count):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (tenant_id, action, entity_type) "
                    "VALUES (:tenant, :action, 'test')"
                ),
                {"tenant": tenant_id, "action": f"api.test.{index}"},
            )


async def _seal(owner_engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
    async with system_session(reason="api test sealing") as db:
        await set_tenant(db, tenant_id)
        await checkpoints.seal(db, tenant_id=tenant_id, key=KEY)


async def _head(client: httpx.AsyncClient, session: Session) -> dict[str, Any]:
    response = await client.get(CHAIN, headers=session.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_the_status_reports_the_head_and_health(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    before = await _head(client, admin)
    await _events(owner_engine, tenant.id, 4)
    after = await _head(client, admin)

    assert after["scope"] == "tenant"
    assert after["events"] == before["events"] + 4
    assert after["head"]["seq"] == after["events"]
    assert len(after["head"]["hash"]) == 64
    assert after["head"]["occurred_at"]
    assert after["last_checkpoint"] is None
    assert after["unsealed_events"] == after["events"]
    assert after["last_verification"] is None
    assert after["healthy"] is True


async def test_the_status_reports_a_signed_checkpoint(
    client: httpx.AsyncClient,
    admin: Session,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _events(owner_engine, tenant.id, 3)
    head = await _head(client, admin)
    await _seal(owner_engine, tenant.id)
    monkeypatch.setattr(checkpoints, "known_keys", lambda *_: {KEY.key_id: KEY.secret})

    body = await _head(client, admin)
    checkpoint = body["last_checkpoint"]
    assert checkpoint["up_to_seq"] == head["events"]
    assert checkpoint["key_id"] == "k1"
    assert checkpoint["signature_valid"] is True
    assert body["unsealed_events"] == 0
    assert body["healthy"] is True


async def test_a_checkpoint_signed_with_an_unknown_key_is_not_healthy(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    """The test settings have no AUDIT_ANCHOR_KEY, so the seal's key is unknown."""
    await _events(owner_engine, tenant.id, 2)
    await _seal(owner_engine, tenant.id)

    body = await _head(client, admin)
    assert body["last_checkpoint"]["signature_valid"] is False
    assert body["healthy"] is False


async def test_starting_a_verification_runs_it_and_records_the_result(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 5)
    head = await _head(client, admin)

    response = await client.post(VERIFICATIONS, headers=admin.headers, json={"mode": "independent"})
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "pending"
    assert (queued["from_seq"], queued["to_seq"]) == (1, head["events"])
    assert queued["mode"] == "independent"

    finished = await client.get(f"{VERIFICATIONS}/{queued['id']}", headers=admin.headers)
    assert finished.status_code == 200
    body = finished.json()
    assert body["status"] == "passed"
    assert body["checked_count"] == head["events"]
    assert body["first_bad_seq"] is None
    assert body["finished_at"] is not None


async def test_a_verification_is_itself_audited(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 2)
    queued = (await client.post(VERIFICATIONS, headers=admin.headers, json={})).json()

    response = await client.get(
        EVENTS,
        headers=admin.headers,
        params={"action": "audit.chain.verification_requested"},
    )
    items = response.json()["items"]
    assert [item["entity_id"] for item in items] == [queued["id"]]
    assert items[0]["after"] == {
        "from_seq": queued["from_seq"],
        "to_seq": queued["to_seq"],
        "mode": queued["mode"],
    }


async def test_a_failed_verification_names_the_row(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 4)
    head = await _head(client, admin)
    target = head["events"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text(
                "UPDATE audit_events SET action = 'tampered' "
                "WHERE tenant_id = :t AND chain_seq = :seq"
            ),
            {"t": tenant.id, "seq": target},
        )
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )

    run_id = (await client.post(VERIFICATIONS, headers=admin.headers, json={})).json()["id"]
    body = (await client.get(f"{VERIFICATIONS}/{run_id}", headers=admin.headers)).json()
    assert body["status"] == "failed"
    assert body["first_bad_seq"] == target
    assert body["failure_reason"]


async def test_the_range_is_validated(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 3)
    head = await _head(client, admin)

    for payload in (
        {"from_seq": 0},
        {"from_seq": 3, "to_seq": 2},
        {"to_seq": head["events"] + 10},
        {"mode": "sql"},
    ):
        response = await client.post(VERIFICATIONS, headers=admin.headers, json=payload)
        assert response.status_code == 422, (payload, response.text)
        assert response.json()["error"]["code"] == "validation_error"


async def test_a_second_window_can_be_asked_for_after_the_first_finishes(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 3)
    head = await _head(client, admin)
    first = await client.post(VERIFICATIONS, headers=admin.headers, json={})
    assert first.status_code == 202

    second = await client.post(
        VERIFICATIONS,
        headers=admin.headers,
        json={"from_seq": 2, "to_seq": head["events"] + 1},
    )
    assert second.status_code == 202
    assert second.json()["from_seq"] == 2


async def test_verifications_are_listed_newest_first(
    client: httpx.AsyncClient, admin: Session, owner_engine: AsyncEngine, tenant: TenantRow
) -> None:
    await _events(owner_engine, tenant.id, 3)
    await client.post(VERIFICATIONS, headers=admin.headers, json={})
    await client.post(VERIFICATIONS, headers=admin.headers, json={"from_seq": 2})

    response = await client.get(VERIFICATIONS, headers=admin.headers)
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert [item["status"] for item in page["items"]] == ["passed", "passed"]

    filtered = await client.get(VERIFICATIONS, headers=admin.headers, params={"status": "failed"})
    assert filtered.json()["total"] == 0

    bad = await client.get(VERIFICATIONS, headers=admin.headers, params={"status": "nope"})
    assert bad.status_code == 422


async def test_checkpoints_are_listed_with_their_signature_state(
    client: httpx.AsyncClient,
    admin: Session,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _events(owner_engine, tenant.id, 2)
    head = await _head(client, admin)
    await _seal(owner_engine, tenant.id)
    monkeypatch.setattr(checkpoints, "known_keys", lambda *_: {KEY.key_id: KEY.secret})

    response = await client.get(CHECKPOINTS, headers=admin.headers)
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["up_to_seq"] == head["events"]
    assert page["items"][0]["signature_valid"] is True


async def test_citizens_and_operators_cannot_read_the_chain(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, operator: Session
) -> None:
    citizen = await login(client, sms, unique_phone(), tenant.slug)
    for session in (citizen, operator):
        for url in (CHAIN, VERIFICATIONS, CHECKPOINTS):
            response = await client.get(url, headers=session.headers)
            assert response.status_code == 403, (url, response.text)
            assert set(response.json()) == {"error"}
        posted = await client.post(VERIFICATIONS, headers=session.headers, json={})
        assert posted.status_code == 403

    assert (await client.get(CHAIN)).status_code == 401
    assert (await client.post(VERIFICATIONS, json={})).status_code == 401


async def test_another_tenants_run_is_a_404(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    admin: Session,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
) -> None:
    await _events(owner_engine, tenant.id, 2)
    run_id = (await client.post(VERIFICATIONS, headers=admin.headers, json={})).json()["id"]

    async with owner_engine.begin() as conn:
        other = await create_tenant(conn)
        outsider = await create_user(conn, other.id, "municipal_admin")
    other_admin = await login(client, sms, outsider.phone, other.slug)

    response = await client.get(f"{VERIFICATIONS}/{run_id}", headers=other_admin.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    listed = await client.get(VERIFICATIONS, headers=other_admin.headers)
    assert listed.json()["total"] == 0


async def test_an_unknown_verification_id_is_a_404(
    client: httpx.AsyncClient, admin: Session
) -> None:
    response = await client.get(f"{VERIFICATIONS}/{uuid.uuid4()}", headers=admin.headers)
    assert response.status_code == 404


async def test_an_empty_chain_cannot_be_verified(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    """A run over nothing would pass while checking nothing, so it is refused."""
    async with owner_engine.begin() as conn:
        empty = await create_tenant(conn)
        user = await create_user(conn, empty.id, "municipal_admin")
    session = await login(client, sms, user.phone, empty.slug)

    async with owner_engine.begin() as conn:
        # The append-only trigger blocks DELETE for every role, including the owner.
        await conn.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :t"), {"t": empty.id})
        await conn.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")
        )
        await conn.execute(
            text(
                "UPDATE audit_chain_heads SET next_seq = 1, "
                "last_hash = decode(repeat('00', 32), 'hex') WHERE tenant_id = :t"
            ),
            {"t": empty.id},
        )

    response = await client.post(VERIFICATIONS, headers=session.headers, json={})
    assert response.status_code == 422
    assert "no audit events" in response.json()["error"]["message"]


async def test_the_range_limit_is_enforced(
    client: httpx.AsyncClient,
    admin: Session,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _events(owner_engine, tenant.id, 4)

    class Tiny:
        audit_verify_max_events = 2

    monkeypatch.setattr("app.domains.audit.runs.get_settings", lambda: Tiny())
    response = await client.post(VERIFICATIONS, headers=admin.headers, json={})
    assert response.status_code == 422
    assert "limited to 2 events" in response.json()["error"]["message"]


async def test_a_pending_run_blocks_a_second_one(
    client: httpx.AsyncClient,
    admin: Session,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    jobs: InlineJobs,
) -> None:
    """The database's in-flight index is what turns this into a 409."""
    await _events(owner_engine, tenant.id, 2)
    jobs.inline = False  # leave the run `pending`, as a slow worker would
    first = await client.post(VERIFICATIONS, headers=admin.headers, json={})
    assert first.status_code == 202

    conflict = await client.post(VERIFICATIONS, headers=admin.headers, json={})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"
