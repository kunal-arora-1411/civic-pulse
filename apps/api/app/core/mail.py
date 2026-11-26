"""Outgoing email behind a small interface, so the relay can be swapped.

Same shape as `app/domains/auth/sms.py` and the geocoder: a protocol, one
real implementation, and a factory that returns `None` when nothing is
configured. Email is off unless `SMTP_HOST` names a relay, so a deployment
without one sends nothing rather than failing on every event — the outbox
records the skip instead.

The standard library speaks SMTP, so this adds no dependency. `smtplib` is
blocking, and the caller is the outbox dispatcher holding a database
transaction open, so the send runs in a worker thread with a short timeout: a
relay that accepts a connection and then stalls must not hold that
transaction, or the row locks underneath it.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.logging import log_fields

logger = logging.getLogger("civicpulse.mail")

# Long enough for a slow relay to accept the message, short enough that a
# hung one releases the dispatcher's transaction quickly.
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class Email:
    """One plain-text message to one recipient."""

    to: str
    subject: str
    text: str


class Mailer(Protocol):
    name: str

    async def send(self, email: Email) -> None: ...


def mask_email(address: str) -> str:
    """`someone@example.com` → `so***@example.com`, for logs."""
    local, _, domain = address.partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}"


def build_message(email: Email, sender: str) -> EmailMessage:
    """The MIME message for one Email. Pure, so it can be asserted on.

    `Auto-Submitted` keeps out-of-office replies and holiday autoresponders
    from bouncing back and forth with our own notifications.
    """
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(email.text)
    return message


class SmtpMailer:
    """SMTP, optionally authenticated and upgraded with STARTTLS."""

    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = False,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.starttls = starttls
        self.timeout = timeout

    def _send_blocking(self, email: Email) -> None:
        message = build_message(email, self.sender)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            smtp.ehlo()
            if self.starttls:
                smtp.starttls()
                # EHLO again: the capability list changes after the upgrade,
                # and only then does AUTH exist.
                smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(message)

    async def send(self, email: Email) -> None:
        await asyncio.to_thread(self._send_blocking, email)
        # The recipient is personal data; the domain and subject are enough
        # to correlate a delivery with a report of a missing message.
        logger.info(
            "email sent",
            extra=log_fields(to=mask_email(email.to), subject=email.subject),
        )


def mailer_from_settings(settings: Settings) -> Mailer | None:
    if not settings.mail_enabled:
        return None
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_from,
        username=settings.smtp_username,
        password=(settings.smtp_password.get_secret_value() if settings.smtp_password else None),
        starttls=settings.smtp_starttls,
    )


@lru_cache
def _configured() -> Mailer | None:
    return mailer_from_settings(get_settings())


def get_mailer() -> Mailer | None:
    """The configured mailer, or `None` when email is off."""
    return _configured()
