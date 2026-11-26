"""Notifications beyond the inbox: email, SMS and Web Push (P4-03/P4-04).

Each in-app notification becomes a `notification.created` outbox event in
the same transaction; the channels then honour the recipient's preferences,
de-duplicate, cap texts per day and log why anything did not go out.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.core.db import get_session_factory
from app.core.tenancy import set_tenant, system_session
from app.domains.outbox.email import EmailChannel
from app.domains.outbox.push import PushChannel, PushResult, Target
from app.domains.outbox.service import dispatch_event
from app.domains.outbox.sms import OTP_EVENT, SmsChannel, otp_event
from tests.factories import create_tenant, create_user
from tests.helpers import RecordingSms, Session, login, request_otp
from tests.phase1 import City, make_city
from tests.test_outbox_email import RecordingMailer

PREFERENCES = "/api/v1/notifications/preferences"
SUBSCRIPTIONS = "/api/v1/notifications/push-subscriptions"
DEAD_LETTERS = "/api/v1/admin/outbox/dead-letters"
ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


@pytest.fixture
def push_on(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(settings, "vapid_private_key", SecretStr("private-key-for-tests"))


async def _person(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *roles: str,
    email: str | None = None,
    locale: str = "en",
) -> uuid.UUID:
    row = await create_user(conn, tenant_id, *roles)
    await conn.execute(
        text("UPDATE users SET email = :e, locale = :l WHERE id = :u"),
        {"e": email, "l": locale, "u": row.id},
    )
    return row.id


async def _notify(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    kind: str = "issue_status",
    params: dict[str, Any] | None = None,
    link: str = "/reports/r1",
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO notifications (tenant_id, user_id, kind, title_key, body_key, "
                "params, link) VALUES (:t, :u, :k, :title, :body, "
                "CAST(:p AS jsonb), :l) RETURNING id"
            ),
            {
                "t": tenant_id,
                "u": user_id,
                "k": kind,
                "title": f"{kind}.title",
                "body": f"{kind}.body",
                "p": json.dumps(params or {"issue": "CP-1", "status": "in_progress"}),
                "l": link,
            },
        )
    ).scalar_one()


async def _event_of(conn: AsyncConnection, notification_id: uuid.UUID) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "SELECT id FROM outbox_events WHERE event_type = 'notification.created' "
                "AND aggregate_id = :n"
            ),
            {"n": notification_id},
        )
    ).scalar_one()


async def _deliveries(engine: AsyncEngine, event_id: uuid.UUID) -> list[tuple[str, str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT channel, outcome, detail FROM outbox_deliveries "
                "WHERE event_id = :e ORDER BY created_at"
            ),
            {"e": event_id},
        )
        return [(r[0], r[1], r[2]) for r in rows]


async def _queued(
    owner_engine: AsyncEngine, *roles: str, **notification: Any
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """A tenant, a person with a phone, and one notification for them."""
    email = notification.pop("email", None)
    locale = notification.pop("locale", "en")
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user_id = await _person(
            conn, tenant.id, *(roles or ("citizen",)), email=email, locale=locale
        )
        phone = (
            await conn.execute(text("SELECT phone FROM users WHERE id = :u"), {"u": user_id})
        ).scalar_one()
        notification_id = await _notify(conn, tenant.id, user_id, **notification)
        event_id = await _event_of(conn, notification_id)
    return tenant.id, user_id, event_id, phone


# --- the outbox event ------------------------------------------------------------------


async def test_every_notification_is_offered_to_the_external_channels(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user_id = await _person(conn, tenant.id, "citizen")
        notification_id = await _notify(conn, tenant.id, user_id)
        row = (
            await conn.execute(
                text(
                    "SELECT tenant_id, aggregate_type, payload FROM outbox_events "
                    "WHERE event_type = 'notification.created' AND aggregate_id = :n"
                ),
                {"n": notification_id},
            )
        ).one()
    assert row[0] == tenant.id
    assert row[1] == "notification"
    assert row[2] == {
        "notification_id": str(notification_id),
        "user_id": str(user_id),
        "kind": "issue_status",
        "issue_id": None,
    }


# --- SMS -------------------------------------------------------------------------------


async def test_a_status_change_is_texted_without_sensitive_detail(
    owner_engine: AsyncEngine,
) -> None:
    _, _, event_id, phone = await _queued(owner_engine)
    sms = RecordingSms()

    await dispatch_event(event_id, channels=(SmsChannel(sms),))

    # A reference and a status: nothing a lock screen should not show.
    assert sms.texts == [
        (phone, "CivicPulse: Issue CP-1: In progress. http://localhost:3000/reports/r1")
    ]
    assert await _deliveries(owner_engine, event_id) == [("sms", "delivered", "id test-1")]


async def test_texts_follow_the_recipients_language(owner_engine: AsyncEngine) -> None:
    _, _, event_id, _ = await _queued(owner_engine, locale="hi")
    sms = RecordingSms()

    await dispatch_event(event_id, channels=(SmsChannel(sms),))

    assert "समस्या CP-1: काम जारी" in sms.texts[0][1]


async def test_a_kind_switched_off_is_not_texted(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user_id = await _person(conn, tenant.id, "citizen")
        await conn.execute(
            text(
                "INSERT INTO notification_preferences (tenant_id, user_id, kind, channel, enabled) "
                "VALUES (:t, :u, 'issue_status', 'sms', false)"
            ),
            {"t": tenant.id, "u": user_id},
        )
        event_id = await _event_of(conn, await _notify(conn, tenant.id, user_id))
    sms = RecordingSms()

    await dispatch_event(event_id, channels=(SmsChannel(sms),))

    assert sms.texts == []
    assert await _deliveries(owner_engine, event_id) == [
        ("sms", "skipped", "the recipient turned issue_status off on sms")
    ]


async def test_an_identical_notification_is_not_texted_twice(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user_id = await _person(conn, tenant.id, "citizen")
        first = await _event_of(conn, await _notify(conn, tenant.id, user_id))
        second = await _event_of(conn, await _notify(conn, tenant.id, user_id))
        different = await _event_of(
            conn,
            await _notify(conn, tenant.id, user_id, params={"issue": "CP-1", "status": "resolved"}),
        )
    sms = RecordingSms()

    for event_id in (first, second, different):
        await dispatch_event(event_id, channels=(SmsChannel(sms),))

    assert len(sms.texts) == 2
    assert (await _deliveries(owner_engine, second))[0][1:] == (
        "skipped",
        "the same notification went out on this channel moments ago",
    )


async def test_texts_are_capped_per_person_per_day(
    owner_engine: AsyncEngine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "notification_sms_per_day", 1)
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user_id = await _person(conn, tenant.id, "citizen")
        first = await _event_of(conn, await _notify(conn, tenant.id, user_id))
        second = await _event_of(
            conn,
            await _notify(conn, tenant.id, user_id, params={"issue": "CP-2", "status": "closed"}),
        )
    sms = RecordingSms()

    await dispatch_event(first, channels=(SmsChannel(sms),))
    await dispatch_event(second, channels=(SmsChannel(sms),))

    assert len(sms.texts) == 1
    assert (await _deliveries(owner_engine, second))[0][2] == "the recipient reached 1 texts today"


async def test_a_deactivated_account_gets_nothing(owner_engine: AsyncEngine) -> None:
    _, user_id, event_id, _ = await _queued(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false WHERE id = :u"), {"u": user_id})
    sms = RecordingSms()

    await dispatch_event(event_id, channels=(SmsChannel(sms),))

    assert sms.texts == []
    assert await _deliveries(owner_engine, event_id) == [
        ("sms", "skipped", "the recipient's account is deactivated")
    ]


# --- email -----------------------------------------------------------------------------


async def test_a_notification_is_emailed_with_a_way_to_stop_it(owner_engine: AsyncEngine) -> None:
    _, _, event_id, _ = await _queued(owner_engine, email="asha@example.com")
    mailer = RecordingMailer()

    await dispatch_event(event_id, channels=(EmailChannel(mailer),))

    (email,) = mailer.sent
    assert email.to == "asha@example.com"
    assert email.subject == "Issue CP-1: In progress"
    assert "http://localhost:3000/reports/r1" in email.text
    assert "http://localhost:3000/profile" in email.text


async def test_assignment_notifications_are_left_to_the_assignment_email(
    owner_engine: AsyncEngine,
) -> None:
    _, _, event_id, _ = await _queued(
        owner_engine,
        "field_worker",
        email="ravi@example.com",
        kind="assignment",
        params={"issue": "CP-9"},
    )
    mailer = RecordingMailer()

    await dispatch_event(event_id, channels=(EmailChannel(mailer),))

    assert mailer.sent == []
    assert await _deliveries(owner_engine, event_id) == [
        ("email", "skipped", "assignments are emailed with issue.assigned")
    ]


# --- Web Push --------------------------------------------------------------------------


class FakePushService:
    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.sent: list[tuple[Target, str]] = []

    async def send(self, target: Target, payload: str) -> PushResult:
        self.sent.append((target, payload))
        return PushResult(status=self.status, message_id="msg-1", error=None)


async def _subscribe(conn: AsyncConnection, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth) "
            "VALUES (:t, :u, :e, 'key', 'secret')"
        ),
        {"t": tenant_id, "u": user_id, "e": f"{ENDPOINT}-{uuid.uuid4()}"},
    )


async def test_a_notification_is_pushed_to_every_subscribed_browser(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id, user_id, event_id, _ = await _queued(owner_engine)
    async with owner_engine.begin() as conn:
        await _subscribe(conn, tenant_id, user_id)
        await _subscribe(conn, tenant_id, user_id)
    service = FakePushService()

    await dispatch_event(event_id, channels=(PushChannel(service),))

    assert len(service.sent) == 2
    payload = json.loads(service.sent[0][1])
    assert payload["title"] == "Issue CP-1: In progress"
    assert payload["url"] == "http://localhost:3000/reports/r1"
    assert (await _deliveries(owner_engine, event_id))[0][:2] == ("push", "delivered")


async def test_a_subscription_the_push_service_forgot_is_removed(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id, user_id, event_id, _ = await _queued(owner_engine)
    async with owner_engine.begin() as conn:
        await _subscribe(conn, tenant_id, user_id)

    await dispatch_event(event_id, channels=(PushChannel(FakePushService(status=410)),))

    async with owner_engine.connect() as conn:
        left = (
            await conn.execute(
                text("SELECT count(*) FROM push_subscriptions WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar_one()
    assert left == 0
    assert await _deliveries(owner_engine, event_id) == [
        ("push", "skipped", "every subscription had expired")
    ]


async def test_a_push_service_error_is_retried(owner_engine: AsyncEngine) -> None:
    tenant_id, user_id, event_id, _ = await _queued(owner_engine)
    async with owner_engine.begin() as conn:
        await _subscribe(conn, tenant_id, user_id)

    await dispatch_event(event_id, channels=(PushChannel(FakePushService(status=503)),))

    assert (await _deliveries(owner_engine, event_id))[0][:2] == ("push", "failed")
    async with owner_engine.connect() as conn:
        next_at = (
            await conn.execute(
                text("SELECT next_attempt_at FROM outbox_events WHERE id = :e"), {"e": event_id}
            )
        ).scalar_one()
    assert next_at is not None


# --- preferences API -------------------------------------------------------------------


def _choices(body: dict[str, Any]) -> dict[tuple[str, str], bool]:
    return {
        (item["kind"], c["channel"]): c["enabled"]
        for item in body["items"]
        for c in item["channels"]
    }


async def test_a_citizen_sees_and_changes_their_own_choices(
    client: httpx.AsyncClient, city: City
) -> None:
    response = await client.get(PREFERENCES, headers=city.citizen.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["kind"] for i in body["items"]] == [
        "report_new_issue",
        "report_linked",
        "issue_status",
    ]
    assert _choices(body)[("issue_status", "sms")] is True
    assert body["available"]["sms"] is True
    assert body["push_public_key"] is None

    changed = await client.put(
        PREFERENCES,
        headers=city.citizen.headers,
        json={"items": [{"kind": "issue_status", "channel": "sms", "enabled": False}]},
    )
    assert changed.status_code == 200, changed.text
    assert _choices(changed.json())[("issue_status", "sms")] is False
    # Untouched choices keep their defaults.
    assert _choices(changed.json())[("issue_status", "email")] is True

    again = await client.get(PREFERENCES, headers=city.citizen.headers)
    assert _choices(again.json())[("issue_status", "sms")] is False


async def test_staff_are_offered_the_staff_kinds(client: httpx.AsyncClient, city: City) -> None:
    response = await client.get(PREFERENCES, headers=city.operator.headers)
    assert response.status_code == 200, response.text
    kinds = [i["kind"] for i in response.json()["items"]]
    assert {"review_task", "assignment", "sla_breach"} <= set(kinds)
    # Review-task email would mail every operator for every report.
    assert _choices(response.json())[("review_task", "email")] is False


@pytest.mark.parametrize(
    ("kind", "channel"),
    [("review_task", "push"), ("report_new_issue", "push"), ("issue_status", "fax")],
)
async def test_a_choice_that_cannot_apply_is_refused(
    client: httpx.AsyncClient, city: City, kind: str, channel: str
) -> None:
    response = await client.put(
        PREFERENCES,
        headers=city.citizen.headers,
        json={"items": [{"kind": kind, "channel": channel, "enabled": True}]},
    )
    assert response.status_code == 422


async def test_preferences_need_a_sign_in(client: httpx.AsyncClient) -> None:
    assert (await client.get(PREFERENCES)).status_code == 401
    assert (await client.put(PREFERENCES, json={"items": []})).status_code == 401


# --- push subscriptions API ------------------------------------------------------------


def _subscription(endpoint: str = ENDPOINT) -> dict[str, Any]:
    return {"endpoint": endpoint, "keys": {"p256dh": "BKey", "auth": "secret"}}


async def test_subscribing_needs_push_to_be_configured(
    client: httpx.AsyncClient, city: City
) -> None:
    response = await client.post(SUBSCRIPTIONS, headers=city.citizen.headers, json=_subscription())
    assert response.status_code == 503


async def test_a_browser_subscribes_once_and_unsubscribes(
    client: httpx.AsyncClient, city: City, owner_engine: AsyncEngine, push_on: None
) -> None:
    endpoint = f"{ENDPOINT}-{uuid.uuid4()}"
    for _ in range(2):
        response = await client.post(
            SUBSCRIPTIONS, headers=city.citizen.headers, json=_subscription(endpoint)
        )
        assert response.status_code == 201, response.text

    preferences = await client.get(PREFERENCES, headers=city.citizen.headers)
    assert preferences.json()["push_public_key"] == "BPublicKeyForTests"
    assert preferences.json()["available"]["push"] is True

    async def count() -> int:
        async with owner_engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM push_subscriptions WHERE endpoint = :e"),
                    {"e": endpoint},
                )
            ).scalar_one()

    assert await count() == 1

    # Someone else cannot remove it.
    other = await client.delete(
        SUBSCRIPTIONS, headers=city.operator.headers, params={"endpoint": endpoint}
    )
    assert other.status_code == 204
    assert await count() == 1

    gone = await client.delete(
        SUBSCRIPTIONS, headers=city.citizen.headers, params={"endpoint": endpoint}
    )
    assert gone.status_code == 204
    assert await count() == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",
        "https://169.254.169.254/latest/meta-data",
        "https://internal.civicpulse.local/hook",
        "https://evilfcm.googleapis.com.example.com/x",
    ],
)
async def test_only_real_push_services_can_be_endpoints(
    client: httpx.AsyncClient, city: City, push_on: None, endpoint: str
) -> None:
    response = await client.post(
        SUBSCRIPTIONS, headers=city.citizen.headers, json=_subscription(endpoint)
    )
    assert response.status_code == 422


# --- tenant isolation ------------------------------------------------------------------


async def test_other_tenants_never_see_delivery_settings(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        one = await create_tenant(conn)
        two = await create_tenant(conn)
        user_id = await _person(conn, one.id, "citizen")
        await conn.execute(
            text(
                "INSERT INTO notification_preferences (tenant_id, user_id, kind, channel, enabled) "
                "VALUES (:t, :u, 'issue_status', 'sms', false)"
            ),
            {"t": one.id, "u": user_id},
        )
        await _subscribe(conn, one.id, user_id)

    async with get_session_factory()() as session:
        await set_tenant(session, two.id)
        for table in ("notification_preferences", "push_subscriptions"):
            rows = await session.execute(
                text(f"SELECT 1 FROM {table} WHERE user_id = :u"),  # noqa: S608
                {"u": user_id},
            )
            assert rows.all() == [], table

    async with get_session_factory()() as session:
        await set_tenant(session, two.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO notification_preferences "
                    "(tenant_id, user_id, kind, channel, enabled) "
                    "VALUES (:t, :u, 'issue_status', 'email', false)"
                ),
                {"t": one.id, "u": user_id},
            )


# --- dead letters ----------------------------------------------------------------------


async def _dead_letter(conn: AsyncConnection, tenant_id: uuid.UUID) -> uuid.UUID:
    event_id = (
        await conn.execute(
            text(
                "INSERT INTO outbox_events (tenant_id, event_type, aggregate_type, aggregate_id, "
                "payload, attempts, dead_lettered_at, last_error) "
                "VALUES (:t, 'issue.assigned', 'issue', gen_random_uuid(), "
                "'{\"phone\": \"+919999999999\"}', 5, now(), 'relay refused') RETURNING id"
            ),
            {"t": tenant_id},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO outbox_deliveries (tenant_id, event_id, channel, outcome, detail) "
            "VALUES (:t, :e, 'email', 'failed', 'relay refused')"
        ),
        {"t": tenant_id, "e": event_id},
    )
    return event_id


async def test_an_administrator_lists_and_retries_dead_letters(
    client: httpx.AsyncClient, city: City, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        event_id = await _dead_letter(conn, city.tenant.id)

    listed = await client.get(DEAD_LETTERS, headers=city.admin.headers)
    assert listed.status_code == 200, listed.text
    (item,) = [i for i in listed.json()["items"] if i["id"] == str(event_id)]
    assert item["last_error"] == "relay refused"
    assert item["deliveries"][0]["outcome"] == "failed"
    # Contact details in the payload never leave through this endpoint.
    assert "payload" not in item
    assert "+919999999999" not in listed.text

    retried = await client.post(f"{DEAD_LETTERS}/{event_id}/retry", headers=city.admin.headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["dead_lettered_at"] is None

    async with owner_engine.connect() as conn:
        state = (
            await conn.execute(
                text("SELECT attempts, dead_lettered_at FROM outbox_events WHERE id = :e"),
                {"e": event_id},
            )
        ).one()
        audited = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action = 'outbox.dead_letter_retried' AND entity_id = :e"
                ),
                {"e": str(event_id)},
            )
        ).scalar_one()
    assert state == (0, None)
    assert audited == 1

    # Once back in the queue it is no longer a dead letter.
    again = await client.post(f"{DEAD_LETTERS}/{event_id}/retry", headers=city.admin.headers)
    assert again.status_code == 404


async def test_dead_letters_are_for_administrators_only(
    client: httpx.AsyncClient, city: City
) -> None:
    for who in (city.operator, city.citizen):
        assert (await client.get(DEAD_LETTERS, headers=who.headers)).status_code == 403
        retry = await client.post(f"{DEAD_LETTERS}/{uuid.uuid4()}/retry", headers=who.headers)
        assert retry.status_code == 403


async def test_another_tenants_dead_letters_are_invisible(
    client: httpx.AsyncClient, city: City, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        elsewhere = await create_tenant(conn)
        event_id = await _dead_letter(conn, elsewhere.id)

    listed = await client.get(DEAD_LETTERS, headers=city.admin.headers)
    assert str(event_id) not in [i["id"] for i in listed.json()["items"]]
    retry = await client.post(f"{DEAD_LETTERS}/{event_id}/retry", headers=city.admin.headers)
    assert retry.status_code == 404


# --- one-time passwords ----------------------------------------------------------------


async def test_a_sign_in_code_is_sent_from_the_outbox_encrypted_at_rest(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user = await create_user(conn, tenant.id, "citizen")

    response = await request_otp(client, user.phone, tenant.slug)
    assert response.status_code == 200, response.text
    challenge_id = response.json()["challenge_id"]
    code = sms.codes[user.phone]

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, payload, dispatched_at FROM outbox_events "
                    "WHERE event_type = :t AND aggregate_id = :c"
                ),
                {"t": OTP_EVENT, "c": challenge_id},
            )
        ).one()
    # Sent straight after the request, and never stored in clear.
    assert row[2] is not None
    assert code not in str(row[1])
    assert (await _deliveries(owner_engine, row[0]))[0][:2] == ("sms", "delivered")


async def test_a_code_that_expired_in_the_queue_is_not_sent(owner_engine: AsyncEngine) -> None:
    event = otp_event(
        tenant_id=None,
        challenge_id=uuid.uuid4(),
        phone="+919812345678",
        code="123456",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with system_session(reason="test: a stale sign-in code") as db:
        db.add(event)
    sms = RecordingSms()

    await dispatch_event(event.id, channels=(SmsChannel(sms),))

    assert sms.sent == []
    assert await _deliveries(owner_engine, event.id) == [
        ("sms", "skipped", "the code expired before it could be sent")
    ]


async def test_signing_in_still_works_end_to_end(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user = await create_user(conn, tenant.id, "citizen")
    session: Session = await login(client, sms, user.phone, tenant.slug)
    assert session.access_token
