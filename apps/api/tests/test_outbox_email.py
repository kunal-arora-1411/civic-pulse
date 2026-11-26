"""The outbox's email channel: the first external channel (P4-04).

test_outbox.py proves the dispatcher with a stand-in channel. These tests pin
the real one: who it writes to, what it says, and — the part that matters for
a notification service — that every reason for not sending is recorded as a
skip with its reason, while a relay refusing is a failure that gets retried.

No SMTP server is needed. The channel takes a mailer, so a recording mailer
stands in for the relay; the socket-opening half is checked by building the
message it would hand over.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.mail import Email, build_message, mask_email
from app.domains.outbox.channels import NO_CHANNEL, channels_for, default_channels
from app.domains.outbox.email import (
    Assignee,
    EmailChannel,
    IssueFacts,
    compose,
    priority_label,
    render_assignment,
)
from app.domains.outbox.models import OutboxEvent
from app.domains.outbox.service import dispatch
from tests.factories import create_category, create_issue, create_tenant, create_user

NOW = datetime.now(UTC)


class RecordingMailer:
    """Stands in for the relay and remembers what it was asked to send."""

    name = "recording"

    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.sent: list[Email] = []
        self.raise_on_send = raise_on_send

    async def send(self, email: Email) -> None:
        self.sent.append(email)
        if self.raise_on_send:
            raise RuntimeError("relay refused the message")


def _person(**overrides: Any) -> Assignee:
    base = Assignee(
        id=uuid.uuid4(),
        email="ravi@city.example",
        locale="en",
        display_name="Ravi Kumar",
    )
    return replace(base, **overrides)


def _facts(**overrides: Any) -> IssueFacts:
    base = IssueFacts(
        reference="CP-26-000042",
        category_en="Pothole",
        category_local="गड्ढा",
        address="5th Main Road, Ward 2",
        priority="high",
    )
    return replace(base, **overrides)


async def _event(
    conn: AsyncConnection, tenant_id: uuid.UUID, payload: dict[str, Any]
) -> OutboxEvent:
    """A real outbox row, returned as the object the dispatcher would claim."""
    event_id = (
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(tenant_id, event_type, aggregate_type, aggregate_id, payload, created_at) "
                "VALUES (:t, 'issue.assigned', 'issue', gen_random_uuid(), "
                "CAST(:p AS jsonb), :c) RETURNING id"
            ),
            {"t": tenant_id, "p": json.dumps(payload), "c": NOW},
        )
    ).scalar_one()
    return OutboxEvent(
        id=event_id,
        tenant_id=tenant_id,
        event_type="issue.assigned",
        aggregate_type="issue",
        aggregate_id=uuid.uuid4(),
        payload=payload,
        created_at=NOW,
        attempts=0,
    )


async def _staff(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    email: str | None = "ravi@city.example",
    locale: str = "en",
    is_active: bool = True,
) -> uuid.UUID:
    """A staff user with an address and a language (create_user has neither)."""
    user = await create_user(conn, tenant_id, display_name="Ravi Kumar", is_active=is_active)
    await conn.execute(
        text("UPDATE users SET email = :e, locale = :l WHERE id = :u"),
        {"e": email, "l": locale, "u": user.id},
    )
    return user.id


async def _issue(
    conn: AsyncConnection, tenant_id: uuid.UUID, *, address: str | None = "5th Main Road"
) -> uuid.UUID:
    reporter = await create_user(conn, tenant_id)
    category = await create_category(conn, tenant_id, code="pothole")
    issue = await create_issue(
        conn, tenant_id, category_id=category, reporter_id=reporter.id, address_text=address
    )
    return issue.id


async def _deliveries(conn: AsyncConnection, event_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT channel, outcome, detail FROM outbox_deliveries "
                    "WHERE event_id = :e ORDER BY created_at, channel"
                ),
                {"e": event_id},
            )
        ).all()
    )


# --- rendering -------------------------------------------------------------


def test_an_english_assignment_says_what_it_is_and_where_to_go() -> None:
    email = render_assignment(_person(), _facts(), "http://localhost:3000")

    assert email.to == "ravi@city.example"
    assert email.subject == "[CP-26-000042] Assigned to you: Pothole"
    assert "Hello Ravi Kumar," in email.text
    assert "CP-26-000042 (Pothole) is now assigned to you." in email.text
    assert "Where: 5th Main Road, Ward 2" in email.text
    assert "Priority: High" in email.text
    assert "Open your work queue: http://localhost:3000/field" in email.text


def test_a_hindi_reader_gets_hindi_copy_and_the_local_category_name() -> None:
    email = render_assignment(_person(locale="hi"), _facts(), "http://web.example/")

    assert "गड्ढा" in email.subject
    assert "अब आपको सौंपी गई है" in email.text
    assert "प्राथमिकता: उच्च" in email.text
    # A trailing slash on WEB_URL must not double up in the link.
    assert "http://web.example/field" in email.text
    assert "http://web.example//field" not in email.text


def test_missing_name_and_address_still_read_sensibly() -> None:
    english = render_assignment(_person(display_name=None), _facts(address=None), "http://w")
    hindi = render_assignment(
        _person(display_name=None, locale="hi"), _facts(address=None), "http://w"
    )

    assert english.text.startswith("Hello there,")
    assert "Where:" not in english.text
    assert hindi.text.startswith("नमस्ते महोदय,")


@pytest.mark.parametrize(
    ("band", "expected"),
    [("critical", "Critical"), ("low", "Low"), ("unknown-band", "unknown-band"), (None, "—")],
)
def test_an_unrecognised_priority_band_is_shown_rather_than_guessed(
    band: str | None, expected: str
) -> None:
    assert priority_label(band, hindi=False) == expected


def test_the_recipient_address_is_masked_in_logs() -> None:
    assert mask_email("ravi.kumar@city.example") == "ra***@city.example"
    assert mask_email("not-an-address") == "***"


def test_the_message_it_hands_the_relay_is_well_formed() -> None:
    email = render_assignment(_person(), _facts(), "http://localhost:3000")
    message = build_message(email, "CivicPulse <no-reply@civicpulse.local>")

    assert message["To"] == "ravi@city.example"
    assert message["Subject"] == email.subject
    # An out-of-office reply to this must not bounce back into the system.
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content_type() == "text/plain"


# --- composing against real rows ------------------------------------------


async def test_an_assignment_is_composed_from_the_database(owner_engine: AsyncEngine) -> None:
    mailer = RecordingMailer()
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id, locale="en")
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    delivery = await EmailChannel(mailer).deliver(event)

    assert delivery.outcome == "delivered"
    assert len(mailer.sent) == 1
    sent = mailer.sent[0]
    assert sent.to == "ravi@city.example"
    assert "is now assigned to you" in sent.text
    # The reference and address are the issue's own, not invented.
    assert "CP-99-" in sent.subject
    assert "5th Main Road" in sent.text


async def test_the_reader_locale_decides_the_language(owner_engine: AsyncEngine) -> None:
    mailer = RecordingMailer()
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id, locale="hi")
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    await EmailChannel(mailer).deliver(event)

    assert "अब आपको सौंपी गई है" in mailer.sent[0].text


async def test_an_assignment_to_a_team_with_nobody_named_is_skipped(
    owner_engine: AsyncEngine,
) -> None:
    mailer = RecordingMailer()
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        issue = await _issue(conn, tenant.id)
        event = await _event(conn, tenant.id, {"assignee_id": None, "issue_id": str(issue)})

    delivery = await EmailChannel(mailer).deliver(event)

    assert delivery.outcome == "skipped"
    assert delivery.detail == "the assignment names nobody to email"
    assert mailer.sent == []


async def test_an_assignee_without_an_address_is_skipped(owner_engine: AsyncEngine) -> None:
    mailer = RecordingMailer()
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id, email=None)
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    delivery = await EmailChannel(mailer).deliver(event)

    assert delivery.outcome == "skipped"
    assert delivery.detail == "the assignee has no email address"
    assert mailer.sent == []


async def test_a_deactivated_assignee_is_not_emailed(owner_engine: AsyncEngine) -> None:
    mailer = RecordingMailer()
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id, is_active=False)
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    delivery = await EmailChannel(mailer).deliver(event)

    assert delivery.outcome == "skipped"
    assert mailer.sent == []


async def test_a_message_is_never_built_with_a_blank_reference(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id)
        event = await _event(conn, tenant.id, {"assignee_id": str(assignee)})

    async with owner_engine.connect() as conn:
        composed = await compose(conn, event)

    assert composed.email is None
    assert composed.skip == "the issue is gone"


def test_with_no_relay_the_channel_skips_and_says_so() -> None:
    import asyncio

    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_type="issue.assigned",
        aggregate_type="issue",
        aggregate_id=uuid.uuid4(),
        payload={"assignee_id": str(uuid.uuid4())},
        created_at=NOW,
        attempts=0,
    )
    delivery = asyncio.run(EmailChannel(None).deliver(event))

    assert delivery.outcome == "skipped"
    assert delivery.detail == "no SMTP relay is configured"


def test_the_channel_claims_assignments_only() -> None:
    channel = EmailChannel(RecordingMailer())

    assert channel.handles("issue.assigned")
    assert not channel.handles("issue.closed")
    assert not channel.handles("report.created")


# --- through the dispatcher -----------------------------------------------


async def test_a_relay_failure_is_retried_not_recorded_as_delivered(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id)
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    await dispatch(channels=(EmailChannel(RecordingMailer(raise_on_send=True)),))

    async with owner_engine.connect() as conn:
        assert await _deliveries(conn, event.id) == [
            ("email", "failed", "RuntimeError: relay refused the message")
        ]
        row = (
            await conn.execute(
                text("SELECT dispatched_at, attempts FROM outbox_events WHERE id = :e"),
                {"e": event.id},
            )
        ).one()
    # Not dispatched: the next tick tries again.
    assert row.dispatched_at is None
    assert row.attempts == 1


async def test_a_successful_send_is_recorded_with_its_subject(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assignee = await _staff(conn, tenant.id)
        issue = await _issue(conn, tenant.id)
        event = await _event(
            conn, tenant.id, {"assignee_id": str(assignee), "issue_id": str(issue)}
        )

    await dispatch(channels=(EmailChannel(RecordingMailer()),))

    async with owner_engine.connect() as conn:
        rows = await _deliveries(conn, event.id)
    assert rows[0][0] == "email"
    assert rows[0][1] == "delivered"
    assert rows[0][2].startswith("[CP-99-")


async def test_an_event_no_channel_handles_is_still_accounted_for(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        event_id = (
            await conn.execute(
                text(
                    "INSERT INTO outbox_events "
                    "(tenant_id, event_type, aggregate_type, aggregate_id, payload, created_at) "
                    "VALUES (:t, 'issue.closed', 'issue', gen_random_uuid(), '{}'::jsonb, :c) "
                    "RETURNING id"
                ),
                {"t": tenant.id, "c": NOW},
            )
        ).scalar_one()

    await dispatch(channels=(EmailChannel(RecordingMailer()),))

    async with owner_engine.connect() as conn:
        assert await _deliveries(conn, event_id) == [("none", "skipped", NO_CHANNEL)]


# --- the registry ---------------------------------------------------------


def test_no_relay_configured_registers_no_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """With SMTP_HOST unset the registry is empty, so behaviour is unchanged."""
    from app.core import mail

    monkeypatch.setattr(mail, "_configured", lambda: None)

    assert default_channels() == ()
    assert channels_for("issue.assigned", None) == []


def test_a_configured_relay_registers_the_email_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import mail

    monkeypatch.setattr(mail, "_configured", lambda: RecordingMailer())

    assert [c.name for c in default_channels()] == ["email"]
    assert [c.name for c in channels_for("issue.assigned")] == ["email"]
    # An event it does not handle falls through to the "no channel" record.
    assert channels_for("issue.closed") == []
