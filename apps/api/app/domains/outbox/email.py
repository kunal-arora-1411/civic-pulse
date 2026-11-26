"""The outbox's email channel.

An assignee learns by email that work was given to them, which is the one
event that needs somebody to act. It mirrors the in-app `assignment`
notification the database writes (migration 0008) but has to render its text
server-side, because the reader's client is a mail program, not the web app.

Copy lives here in both launch languages and is chosen by the recipient's
`users.locale`, falling back to English. That is a deliberate exception to the
"messages are i18n keys" rule: an email leaves the building before any client
can resolve a key against its catalogue.

Every reason for not sending is a `skipped` delivery carrying the reason —
nobody named, no address, no relay — so the log separates "we chose not to"
from "the relay refused", which is a `failed` and gets retried.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import get_settings
from app.core.mail import Email, Mailer
from app.core.tenancy import system_session
from app.domains.outbox.channels import Delivery
from app.domains.outbox.models import OutboxEvent
from app.domains.priority.rules import PriorityBand

CHANNEL = "email"

# Only events that ask a person to do something justify an email. A status
# change the citizen can see in the app does not.
EMAIL_EVENTS = frozenset({"issue.assigned"})

# Where a field user acts on their work.
LINK_PATH = "/field"


@dataclass(frozen=True, slots=True)
class Assignee:
    id: uuid.UUID
    email: str | None
    locale: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class IssueFacts:
    reference: str
    category_en: str
    category_local: str
    address: str | None
    priority: str | None


@dataclass(frozen=True, slots=True)
class Composed:
    """Either a message to send, or the reason there isn't one."""

    email: Email | None = None
    skip: str | None = None


class EmailChannel:
    """Sends one email per event, to the person it concerns."""

    name = CHANNEL

    def __init__(self, mailer: Mailer | None) -> None:
        self.mailer = mailer

    def handles(self, event_type: str) -> bool:
        return event_type in EMAIL_EVENTS

    async def deliver(self, event: OutboxEvent) -> Delivery:
        if self.mailer is None:
            return Delivery.skipped(CHANNEL, "no SMTP relay is configured")

        async with system_session(reason="outbox: email channel") as db:
            composed = await compose(db, event)

        if composed.email is None:
            return Delivery.skipped(CHANNEL, composed.skip or "nothing to send")

        # An error here is the relay's; the dispatcher records a `failed`
        # delivery and the next tick tries again (at-least-once).
        await self.mailer.send(composed.email)
        return Delivery(channel=CHANNEL, detail=composed.email.subject[:120])


async def compose(db: AsyncConnection | AsyncSession, event: OutboxEvent) -> Composed:
    """Build the message for an event, or explain why there is none."""
    person = await _assignee(db, event)
    if person is None:
        # An assignment can go to a team with nobody named, and a team has no
        # address to write to.
        return Composed(skip="the assignment names nobody to email")
    if not person.email:
        return Composed(skip="the assignee has no email address")
    issue = await _issue_facts(db, event)
    if issue is None:
        return Composed(skip="the issue is gone")

    web_url = get_settings().web_url
    return Composed(email=render_assignment(person, issue, web_url))


async def _assignee(db: AsyncConnection | AsyncSession, event: OutboxEvent) -> Assignee | None:
    raw = event.payload.get("assignee_id")
    if not raw:
        return None
    try:
        assignee_id = uuid.UUID(str(raw))
    except ValueError:
        return None
    row = (
        await db.execute(
            text(
                "SELECT id, email, locale, display_name FROM users "
                "WHERE id = :id AND tenant_id = :tenant AND is_active"
            ),
            {"id": assignee_id, "tenant": event.tenant_id},
        )
    ).one_or_none()
    if row is None:
        return None
    return Assignee(id=row[0], email=row[1], locale=row[2] or "en", display_name=row[3])


async def _issue_facts(db: AsyncConnection | AsyncSession, event: OutboxEvent) -> IssueFacts | None:
    issue_id = event.payload.get("issue_id")
    if not issue_id:
        return None
    row = (
        await db.execute(
            text(
                "SELECT i.reference, c.code, c.name_i18n, i.address_text, i.priority_band "
                "FROM civic_issues i JOIN categories c ON c.id = i.category_id "
                "WHERE i.id = :id AND i.tenant_id = :tenant"
            ),
            {"id": issue_id, "tenant": event.tenant_id},
        )
    ).one_or_none()
    if row is None:
        return None
    reference, code, name_i18n, address, band = row
    names: dict[str, str] = name_i18n or {}
    # Mirrors `coalesce(name_i18n->>'en', code)`: a category may have no
    # translation for a language yet.
    return IssueFacts(
        reference=reference,
        category_en=names.get("en") or code,
        category_local=names.get("hi") or names.get("en") or code,
        address=address,
        priority=band,
    )


PRIORITY_LABELS = {
    PriorityBand.LOW.value: ("Low", "कम"),
    PriorityBand.MEDIUM.value: ("Medium", "मध्यम"),
    PriorityBand.HIGH.value: ("High", "उच्च"),
    PriorityBand.CRITICAL.value: ("Critical", "अति गंभीर"),
}


def priority_label(band: str | None, *, hindi: bool) -> str:
    """A band in the reader's language; the raw value if it is unknown."""
    english, localised = PRIORITY_LABELS.get(band or "", (band or "—", band or "—"))
    return localised if hindi else english


def render_assignment(person: Assignee, issue: IssueFacts, web_url: str) -> Email:
    """The subject and body for "this issue is now yours"."""
    url = f"{web_url.rstrip('/')}{LINK_PATH}"
    hindi = (person.locale or "en").lower().startswith("hi")
    category = issue.category_local if hindi else issue.category_en
    priority = priority_label(issue.priority, hindi=hindi)

    if hindi:
        name = person.display_name or "महोदय"
        subject = f"[{issue.reference}] आपको एक समस्या सौंपी गई है: {category}"
        lines = [
            f"नमस्ते {name},",
            "",
            f"{issue.reference} ({category}) अब आपको सौंपी गई है।",
        ]
        if issue.address:
            lines.append(f"स्थान: {issue.address}")
        lines.append(f"प्राथमिकता: {priority}")
        lines += [
            "",
            f"अपनी कार्य सूची खोलें: {url}",
            "",
            "यह ईमेल आपको इसलिए मिला क्योंकि CivicPulse कर्मचारियों को काम सौंपे जाने पर सूचित करता है।",
        ]
    else:
        name = person.display_name or "there"
        subject = f"[{issue.reference}] Assigned to you: {category}"
        lines = [
            f"Hello {name},",
            "",
            f"{issue.reference} ({category}) is now assigned to you.",
        ]
        if issue.address:
            lines.append(f"Where: {issue.address}")
        lines.append(f"Priority: {priority}")
        lines += [
            "",
            f"Open your work queue: {url}",
            "",
            "You are receiving this because CivicPulse emails staff when work is",
            "assigned to them.",
        ]

    return Email(to=person.email or "", subject=subject, text="\n".join(lines))
