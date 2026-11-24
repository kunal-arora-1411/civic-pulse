"""Helpers for Phase 3 tests: a city with a field team, and verified issues
ready to assign."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.fake import make_scene
from tests.helpers import RecordingSms, Session
from tests.images import sha256
from tests.phase1 import NE, City, login_new, make_city, put_to_storage
from tests.phase2 import ISSUES, issue, report

FIELD = "/api/v1/field/work-orders"
TEAMS = "/api/v1/admin/teams"


@dataclass
class Ops:
    city: City
    team_id: str
    worker: Session
    worker2: Session


async def make_ops(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> Ops:
    """A city whose "Roads North" team (Zone North, potholes) has two field workers."""
    city = await make_city(client, sms, owner_engine)
    worker = await login_new(
        client, sms, owner_engine, city, "field_worker", display_name="Farah Field"
    )
    worker2 = await login_new(
        client, sms, owner_engine, city, "field_worker", display_name="Gita Field"
    )
    response = await client.post(
        TEAMS,
        headers=city.admin.headers,
        json={
            "department_id": str(city.roads),
            "name": "Roads North",
            "members": [
                {"user_id": worker.user["id"], "team_role": "lead"},
                {"user_id": worker2.user["id"]},
            ],
            "jurisdiction_ids": [str(city.zones["N"])],
            "category_ids": [str(city.pothole)],
        },
    )
    assert response.status_code == 201, response.text
    return Ops(city=city, team_id=response.json()["id"], worker=worker, worker2=worker2)


async def verified_issue(
    client: httpx.AsyncClient, ops: Ops, *, seed: int = 1, point: tuple[float, float] = NE
) -> dict[str, Any]:
    """A citizen's pothole report, its issue moved to `verified` by the operator."""
    from tests.phase2 import scene_photo

    photo = await scene_photo(client, ops.city.citizen, seed)
    own = await report(client, ops.city, ops.city.citizen, point=point, media_ids=[photo])
    issue_id = own["issue"]["id"]
    current = await issue(client, ops.city.operator, issue_id)
    response = await client.patch(
        f"{ISSUES}/{issue_id}/status",
        headers=ops.city.operator.headers,
        json={"to_status": "verified", "version": current["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def assign(
    client: httpx.AsyncClient,
    ops: Ops,
    detail: dict[str, Any],
    assignee: Session | None,
    **extra: Any,
) -> httpx.Response:
    return await client.post(
        f"{ISSUES}/{detail['id']}/assignments",
        headers=ops.city.supervisor.headers,
        json={
            "team_id": ops.team_id,
            "assignee_id": assignee.user["id"] if assignee else None,
            "version": detail["version"],
            **extra,
        },
    )


async def work_order(client: httpx.AsyncClient, worker: Session) -> dict[str, Any]:
    response = await client.get(FIELD, headers=worker.headers)
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    return item


async def act(
    client: httpx.AsyncClient, worker: Session, wo: dict[str, Any], action: str, **body: Any
) -> httpx.Response:
    return await client.post(
        f"{FIELD}/{wo['id']}/{action}",
        headers=worker.headers,
        json={"version": wo["version"], **body},
    )


async def evidence(client: httpx.AsyncClient, worker: Session, phase: str, seed: int = 7) -> str:
    data = make_scene(seed)
    created = await client.post(
        "/api/v1/media/uploads",
        headers=worker.headers,
        json={
            "purpose": "work_evidence",
            "phase": phase,
            "content_type": "image/jpeg",
            "size_bytes": len(data),
            "checksum_sha256": sha256(data),
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    put = await put_to_storage(body["url"], data, "image/jpeg")
    assert put.status_code == 200, put.text
    done = await client.post(
        f"/api/v1/media/uploads/{body['upload_id']}/complete", headers=worker.headers
    )
    assert done.status_code == 200, done.text
    return done.json()["id"]


async def to_pending_verification(client: httpx.AsyncClient, ops: Ops) -> dict[str, Any]:
    """Assign to the first worker, accept, start, request closure with an
    after photo. Returns the issue detail (supervisor view)."""
    detail = await verified_issue(client, ops)
    assert (await assign(client, ops, detail, ops.worker)).status_code == 201
    wo = await work_order(client, ops.worker)
    wo = (await act(client, ops.worker, wo, "accept")).json()
    wo = (await act(client, ops.worker, wo, "start")).json()
    photo = await evidence(client, ops.worker, "after")
    response = await act(client, ops.worker, wo, "request-closure", media_ids=[photo])
    assert response.status_code == 200, response.text
    return await issue(client, ops.city.supervisor, detail["id"])
