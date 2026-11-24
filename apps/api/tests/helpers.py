from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


class RecordingSms:
    """SMS provider for tests: remembers the last code sent to each phone."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.sent: list[tuple[str, str]] = []

    async def send_otp(self, phone: str, code: str, *, ttl_seconds: int) -> None:
        self.codes[phone] = code
        self.sent.append((phone, code))


class RecordingMediaQueue:
    """Stands in for the Celery queue: remembers what would have been processed."""

    def __init__(self) -> None:
        self.queued: list[tuple[uuid.UUID, uuid.UUID]] = []

    def enqueue(self, asset_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.queued.append((asset_id, tenant_id))


class InlineJobs:
    """Stands in for app.jobs.CeleryJobs: runs each job inline, after the
    request's transaction has committed (FastAPI background tasks), and
    remembers what ran. A test can set `inline = False` to only record."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.inline = True
        self.broker_up = True
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.outcomes: list[Any] = []

    async def recompute_priorities(
        self, tenant_id: uuid.UUID, category_id: uuid.UUID | None = None
    ) -> None:
        self.calls.append(("recompute_priorities", (tenant_id, category_id)))
        if self.inline:
            from app.domains.priority.service import recompute_tenant

            await recompute_tenant(tenant_id, category_id=category_id)

    async def match_report(self, report_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.calls.append(("match_report", (report_id, tenant_id)))
        if self.inline:
            from app.domains.matching.service import process_report

            outcome = await process_report(report_id, tenant_id)
            self.outcomes.append(outcome)

    async def classify(self, classification_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        self.calls.append(("classify", (classification_id, tenant_id)))
        if not self.broker_up:
            return False
        if self.inline:
            from app.domains.ai.classifications import run

            await run(classification_id, tenant_id)
        return True

    def called(self, name: str) -> list[tuple[Any, ...]]:
        return [args for job, args in self.calls if job == name]


@dataclass
class Session:
    access_token: str
    refresh_token: str
    user: dict[str, Any]
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def request_otp(
    client: httpx.AsyncClient, phone: str, tenant_slug: str | None
) -> httpx.Response:
    headers = {"X-Tenant": tenant_slug} if tenant_slug else {}
    return await client.post("/api/v1/auth/otp/request", json={"phone": phone}, headers=headers)


async def verify_otp(
    client: httpx.AsyncClient, challenge_id: str, code: str, tenant_slug: str | None = None
) -> httpx.Response:
    headers = {"X-Tenant": tenant_slug} if tenant_slug else {}
    return await client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": code},
        headers=headers,
    )


async def start_login(
    client: httpx.AsyncClient, sms: RecordingSms, phone: str, tenant_slug: str | None
) -> dict[str, Any]:
    """Request + verify an OTP; returns the verify response body."""
    requested = await request_otp(client, phone, tenant_slug)
    assert requested.status_code == 200, requested.text
    verified = await verify_otp(
        client, requested.json()["challenge_id"], sms.codes[phone], tenant_slug
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def login(
    client: httpx.AsyncClient, sms: RecordingSms, phone: str, tenant_slug: str | None
) -> Session:
    body = await start_login(client, sms, phone, tenant_slug)
    assert "access_token" in body, body
    return Session(
        access_token=body["access_token"], refresh_token=body["refresh_token"], user=body["user"]
    )


async def clear_otp_limits(redis: Any, phone: str) -> None:
    await redis.delete(f"otp:cooldown:{phone}", f"otp:hourly:{phone}")
