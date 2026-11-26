"""Phase 3: teams, assignment, field work orders, notes, closure,
verification, reopen, withdraw and workload (docs/api/phase-3-contract.md)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401  (configure every mapper before using the service)
from app.domains.ai.analysis import ensure_embeddings
from app.domains.operations.closure import close_expired
from tests.helpers import RecordingSms
from tests.phase1 import NW, SW, login_new
from tests.phase2 import ISSUES, issue, report, view
from tests.phase3 import (
    FIELD,
    TEAMS,
    Ops,
    act,
    assign,
    evidence,
    make_ops,
    to_pending_verification,
    verified_issue,
    work_order,
)


@pytest.fixture
async def ops(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> Ops:
    return await make_ops(client, sms, owner_engine)


def _types(detail: dict[str, Any]) -> list[str]:
    return [e["type"] for e in detail["timeline"]]


async def _citizen_timeline(
    client: httpx.AsyncClient, ops: Ops, report_id: str
) -> list[dict[str, Any]]:
    return (await view(client, ops.city.citizen, report_id))["issue"]["timeline"]


# --- teams -----------------------------------------------------------------------------------


async def test_admin_creates_and_lists_teams_and_it_is_audited(
    client: httpx.AsyncClient, ops: Ops, owner_engine: AsyncEngine
) -> None:
    response = await client.get(TEAMS, headers=ops.city.admin.headers)
    assert response.status_code == 200
    (team,) = response.json()["items"]
    assert team["name"] == "Roads North"
    assert {m["team_role"] for m in team["members"]} == {"lead", "member"}
    assert team["jurisdiction_ids"] == [str(ops.city.zones["N"])]
    async with owner_engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action = 'team.created' AND entity_id = :id"
                ),
                {"id": ops.team_id},
            )
        ).scalar_one()
    assert n == 1


async def test_team_members_must_be_staff(client: httpx.AsyncClient, ops: Ops) -> None:
    response = await client.post(
        TEAMS,
        headers=ops.city.admin.headers,
        json={
            "department_id": str(ops.city.roads),
            "name": "Citizens",
            "members": [{"user_id": ops.city.citizen.user["id"]}],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_operator_cannot_manage_teams(client: httpx.AsyncClient, ops: Ops) -> None:
    response = await client.post(
        TEAMS,
        headers=ops.city.operator.headers,
        json={"department_id": str(ops.city.roads), "name": "X"},
    )
    assert response.status_code == 403


async def test_eligible_teams_follow_category_and_ward(client: httpx.AsyncClient, ops: Ops) -> None:
    north = await verified_issue(client, ops)
    response = await client.get(
        f"{ISSUES}/{north['id']}/eligible-teams", headers=ops.city.supervisor.headers
    )
    assert [t["team"]["id"] for t in response.json()] == [ops.team_id]
    south = await verified_issue(client, ops, seed=2, point=SW)
    response = await client.get(
        f"{ISSUES}/{south['id']}/eligible-teams", headers=ops.city.supervisor.headers
    )
    assert response.json() == []


# --- assignment (AC-10) ----------------------------------------------------------------------


async def test_assigning_creates_a_work_order_and_a_public_event(
    client: httpx.AsyncClient, ops: Ops, owner_engine: AsyncEngine
) -> None:
    detail = await verified_issue(client, ops)
    response = await assign(client, ops, detail, ops.worker, note="Bring cold mix")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "assigned"
    assignment = body["operations"]["assignment"]
    assert assignment["team"]["id"] == ops.team_id
    assert assignment["work_order"]["state"] == "pending_acceptance"
    assert _types(body)[-1] == "assigned"

    wo = await work_order(client, ops.worker)
    assert wo["issue"]["id"] == detail["id"]
    async with owner_engine.connect() as conn:
        outbox = (
            (
                await conn.execute(
                    text("SELECT event_type FROM outbox_events WHERE aggregate_id = :id"),
                    {"id": detail["id"]},
                )
            )
            .scalars()
            .all()
        )
    assert outbox == ["issue.assigned"]


async def test_out_of_area_team_is_refused(client: httpx.AsyncClient, ops: Ops) -> None:
    south = await verified_issue(client, ops, seed=2, point=SW)
    response = await assign(client, ops, south, ops.worker)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "team_not_eligible"
    assert response.json()["error"]["details"]["reason"] == "area"


async def test_assignee_must_be_in_the_team(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    outsider = await login_new(client, sms, owner_engine, ops.city, "field_worker")
    detail = await verified_issue(client, ops)
    response = await assign(client, ops, detail, outsider)
    assert response.json()["error"]["code"] == "assignee_not_in_team"


async def test_operator_cannot_assign(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await verified_issue(client, ops)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/assignments",
        headers=ops.city.operator.headers,
        json={"team_id": ops.team_id, "version": detail["version"]},
    )
    assert response.status_code == 403


async def test_reassignment_needs_a_reason_and_keeps_history(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = (await assign(client, ops, await verified_issue(client, ops), ops.worker)).json()
    response = await assign(client, ops, detail, ops.worker2)
    assert response.json()["error"]["code"] == "reason_required"
    response = await assign(client, ops, detail, ops.worker2, reason="Farah is on leave")
    assert response.status_code == 201, response.text

    history = (
        await client.get(
            f"{ISSUES}/{detail['id']}/assignments", headers=ops.city.supervisor.headers
        )
    ).json()
    assert [h["end_reason"] for h in history] == [None, "reassigned"]
    assert history[1]["work_order"]["state"] == "cancelled"
    assert (await client.get(FIELD, headers=ops.worker.headers)).json()["items"] == []
    assert (await work_order(client, ops.worker2))["state"] == "pending_acceptance"


# --- field work orders -----------------------------------------------------------------------


async def test_field_flow_accept_start_progress(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await verified_issue(client, ops)
    await assign(client, ops, detail, ops.worker)
    wo = await work_order(client, ops.worker)

    wo = (await act(client, ops.worker, wo, "accept")).json()
    assert wo["state"] == "accepted"
    assert wo["issue"]["status"] == "assigned"
    wo = (await act(client, ops.worker, wo, "start")).json()
    assert wo["issue"]["status"] == "in_progress"
    before = await evidence(client, ops.worker, "before")
    response = await act(
        client,
        ops.worker,
        wo,
        "progress",
        note="Cordoned off",
        location={"lat": 12.99, "lng": 77.61},
        media_ids=[before],
    )
    assert response.status_code == 200, response.text
    wo = response.json()
    assert wo["updates"][0]["note"] == "Cordoned off"
    assert [e["phase"] for e in wo["evidence"]] == ["before"]


async def test_field_worker_sees_no_reporter_data_and_not_others_orders(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    wo = await work_order(client, ops.worker)
    raw = (await client.get(f"{FIELD}/{wo['id']}", headers=ops.worker.headers)).text
    assert ops.city.citizen.user["id"] not in raw
    for word in ("reporter", "phone", "email"):
        assert word not in raw
    assert (await client.get(f"{FIELD}/{wo['id']}", headers=ops.worker2.headers)).status_code == 404
    assert (await act(client, ops.worker2, wo, "accept")).status_code == 404


async def test_field_worker_cannot_read_staff_issue_endpoints(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await verified_issue(client, ops)
    assert (
        await client.get(f"{ISSUES}/{detail['id']}", headers=ops.worker.headers)
    ).status_code == 403


async def test_stale_version_returns_current_work_order(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    stale = await work_order(client, ops.worker)
    assert (await act(client, ops.worker, stale, "accept")).status_code == 200
    response = await act(client, ops.worker, stale, "start")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["work_order"]["state"] == "accepted"


async def test_action_out_of_order_is_refused(client: httpx.AsyncClient, ops: Ops) -> None:
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    wo = await work_order(client, ops.worker)
    response = await act(client, ops.worker, wo, "start")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_work_order_action"


async def test_decline_needs_reason_and_returns_issue_to_verified(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await verified_issue(client, ops)
    await assign(client, ops, detail, ops.worker)
    wo = await work_order(client, ops.worker)
    assert (await act(client, ops.worker, wo, "decline", reason=" ")).status_code == 422
    assert (await act(client, ops.worker, wo, "decline", reason="Needs a JCB")).status_code == 200
    after = await issue(client, ops.city.supervisor, detail["id"])
    assert after["status"] == "verified"
    assert after["operations"]["assignment"] is None


async def test_work_evidence_needs_a_phase(client: httpx.AsyncClient, ops: Ops) -> None:
    response = await client.post(
        "/api/v1/media/uploads",
        headers=ops.worker.headers,
        json={
            "purpose": "work_evidence",
            "content_type": "image/jpeg",
            "size_bytes": 10,
            "checksum_sha256": "0" * 64,
        },
    )
    assert response.status_code == 422


async def test_citizen_cannot_upload_work_evidence(client: httpx.AsyncClient, ops: Ops) -> None:
    response = await client.post(
        "/api/v1/media/uploads",
        headers=ops.city.citizen.headers,
        json={
            "purpose": "work_evidence",
            "phase": "after",
            "content_type": "image/jpeg",
            "size_bytes": 10,
            "checksum_sha256": "0" * 64,
        },
    )
    assert response.status_code == 403


# --- notes -----------------------------------------------------------------------------------


async def test_internal_notes_never_reach_citizens(client: httpx.AsyncClient, ops: Ops) -> None:
    own = await report(client, ops.city, ops.city.citizen, category=ops.city.waste)
    issue_id = own["issue"]["id"]
    for visibility, body in (
        ("internal", "Contractor is slow"),
        ("public", "Crew booked for Monday"),
    ):
        response = await client.post(
            f"{ISSUES}/{issue_id}/notes",
            headers=ops.city.operator.headers,
            json={"body": body, "visibility": visibility},
        )
        assert response.status_code == 201, response.text
    timeline = await _citizen_timeline(client, ops, own["id"])
    notes = [e["public_note"] for e in timeline if e["type"] == "note"]
    assert notes == ["Crew booked for Monday"]
    assert "Contractor is slow" not in str(timeline)


async def test_field_worker_cannot_post_staff_notes(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await verified_issue(client, ops)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/notes",
        headers=ops.worker.headers,
        json={"body": "x", "visibility": "public"},
    )
    assert response.status_code == 403


# --- closure (AC-11) -------------------------------------------------------------------------


async def test_closure_needs_after_photo_or_allowed_reason(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    wo = await work_order(client, ops.worker)
    wo = (await act(client, ops.worker, wo, "accept")).json()
    wo = (await act(client, ops.worker, wo, "start")).json()
    response = await act(client, ops.worker, wo, "request-closure")
    assert response.json()["error"]["code"] == "evidence_required"
    response = await act(client, ops.worker, wo, "request-closure", reason_code="made_up")
    assert response.json()["error"]["code"] == "evidence_required"


async def test_closure_request_then_supervisor_approval(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await to_pending_verification(client, ops)
    assert detail["status"] == "pending_verification"
    closure = detail["operations"]["closure_request"]
    assert closure["requires_approval"] is True
    assert len(closure["after_photos"]) == 1

    response = await client.post(
        f"{ISSUES}/{detail['id']}/closure/approve",
        headers=ops.city.supervisor.headers,
        json={"version": detail["version"], "public_note": "Pothole filled"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert (await work_order(client, ops.worker))["state"] == "done"


async def _closure_with_after_photo(
    client: httpx.AsyncClient, ops: Ops, *, after_seed: int
) -> tuple[dict[str, Any], str]:
    """A pothole reported with scene 1, closed with an after photo of
    `after_seed`. Returns the supervisor's issue detail and the photo id."""
    detail = await verified_issue(client, ops, seed=1)
    assert (await assign(client, ops, detail, ops.worker)).status_code == 201
    wo = await work_order(client, ops.worker)
    wo = (await act(client, ops.worker, wo, "accept")).json()
    wo = (await act(client, ops.worker, wo, "start")).json()
    photo = await evidence(client, ops.worker, "after", seed=after_seed)
    response = await act(client, ops.worker, wo, "request-closure", media_ids=[photo])
    assert response.status_code == 200, response.text
    return await issue(client, ops.city.supervisor, detail["id"]), photo


async def _embed_all(ops: Ops, detail: dict[str, Any], after_photo: str) -> None:
    report_photos = [m["id"] for r in detail["reports"] for m in r["media"]]
    await ensure_embeddings(
        ops.city.tenant.id, [uuid.UUID(m) for m in [*report_photos, after_photo]]
    )


async def test_scene_match_compares_after_photos_with_the_reports(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail, photo = await _closure_with_after_photo(client, ops, after_seed=1)
    # Nothing to compare until both sides are analysed.
    assert detail["operations"]["closure_request"]["scene_match"] is None

    await _embed_all(ops, detail, photo)
    detail = await issue(client, ops.city.supervisor, detail["id"])
    match = detail["operations"]["closure_request"]["scene_match"]
    assert match is not None
    assert match["similarity"] > 0.9
    assert match["model_id"]


async def test_scene_match_is_low_for_a_different_place(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail, photo = await _closure_with_after_photo(client, ops, after_seed=7)
    await _embed_all(ops, detail, photo)
    detail = await issue(client, ops.city.supervisor, detail["id"])
    match = detail["operations"]["closure_request"]["scene_match"]
    assert match is not None
    assert match["similarity"] < 0.6
    # Advice only: the closure is still pending the supervisor's decision.
    assert detail["status"] == "pending_verification"


async def test_closure_rejection_sends_work_back(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await to_pending_verification(client, ops)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/closure/reject",
        headers=ops.city.supervisor.headers,
        json={"version": detail["version"], "reason": "Photo shows a different road"},
    )
    assert response.json()["status"] == "in_progress"
    assert (await work_order(client, ops.worker))["state"] == "in_progress"


async def test_operator_cannot_approve_closure(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await to_pending_verification(client, ops)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/closure/approve",
        headers=ops.city.operator.headers,
        json={"version": detail["version"]},
    )
    assert response.status_code == 403


async def test_staff_status_endpoint_refuses_system_moves(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await to_pending_verification(client, ops)
    response = await client.patch(
        f"{ISSUES}/{detail['id']}/status",
        headers=ops.city.supervisor.headers,
        json={"to_status": "resolved", "version": detail["version"]},
    )
    assert response.json()["error"]["code"] == "invalid_transition"


# --- verification and reopen (AC-12) ---------------------------------------------------------


async def test_unresolved_answer_sends_issue_back(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await to_pending_verification(client, ops)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "unresolved", "note": "Still a crater"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["issue"]["status"] == "in_progress"
    again = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "resolved"},
    )
    assert again.status_code == 422  # no closure round open any more


async def test_one_answer_per_citizen(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await to_pending_verification(client, ops)
    url = f"{ISSUES}/{detail['id']}/verification"
    assert (
        await client.post(url, headers=ops.city.citizen.headers, json={"outcome": "resolved"})
    ).status_code == 200
    second = await client.post(url, headers=ops.city.citizen.headers, json={"outcome": "resolved"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_verified"


async def test_strangers_cannot_verify(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    detail = await to_pending_verification(client, ops)
    stranger = await login_new(client, sms, owner_engine, ops.city, "citizen")
    response = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=stranger.headers,
        json={"outcome": "resolved"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_eligible"


async def test_citizen_reopens_after_resolution_and_supervisor_reassigns(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await to_pending_verification(client, ops)
    resolved = (
        await client.post(
            f"{ISSUES}/{detail['id']}/closure/approve",
            headers=ops.city.supervisor.headers,
            json={"version": detail["version"]},
        )
    ).json()
    response = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "unresolved", "note": "Opened up again after rain"},
    )
    assert response.json()["issue"]["status"] == "reopened"
    reopened = await issue(client, ops.city.supervisor, detail["id"])
    assert reopened["version"] > resolved["version"]
    response = await assign(client, ops, reopened, ops.worker2)
    assert response.status_code == 201, response.text


async def test_resolution_window_closes_resolved_issues(
    client: httpx.AsyncClient, ops: Ops, owner_engine: AsyncEngine
) -> None:
    detail = await to_pending_verification(client, ops)
    await client.post(
        f"{ISSUES}/{detail['id']}/closure/approve",
        headers=ops.city.supervisor.headers,
        json={"version": detail["version"]},
    )
    await close_expired(now=datetime.now(UTC) + timedelta(hours=1))
    assert (await issue(client, ops.city.supervisor, detail["id"]))["status"] == "resolved"
    await close_expired(now=datetime.now(UTC) + timedelta(days=8))
    closed = await issue(client, ops.city.supervisor, detail["id"])
    assert closed["status"] == "closed"
    assert _types(closed)[-1] == "closed"
    response = await client.post(
        f"{ISSUES}/{detail['id']}/reopen",
        headers=ops.city.supervisor.headers,
        json={"reason": "Recurred"},
    )
    # Supervisors hold issue:update; the issue goes back to the queue.
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reopened"


# --- withdraw --------------------------------------------------------------------------------


async def test_withdraw_keeps_the_report_and_recounts(client: httpx.AsyncClient, ops: Ops) -> None:
    own = await report(client, ops.city, ops.city.citizen, category=ops.city.waste)
    response = await client.post(
        f"/api/v1/reports/{own['id']}/withdraw", headers=ops.city.citizen.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "withdrawn"
    detail = await issue(client, ops.city.operator, own["issue"]["id"])
    assert detail["report_count"] == 0
    assert [r["id"] for r in detail["reports"]] == [own["id"]]
    again = await client.post(
        f"/api/v1/reports/{own['id']}/withdraw", headers=ops.city.citizen.headers
    )
    assert again.status_code == 200


async def test_others_cannot_withdraw_a_report(client: httpx.AsyncClient, ops: Ops) -> None:
    own = await report(client, ops.city, ops.city.citizen, category=ops.city.waste)
    response = await client.post(
        f"/api/v1/reports/{own['id']}/withdraw", headers=ops.city.operator.headers
    )
    assert response.status_code in (403, 404)


# --- workload --------------------------------------------------------------------------------


async def test_workload_counts_open_work_per_member(client: httpx.AsyncClient, ops: Ops) -> None:
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    await assign(
        client, ops, await verified_issue(client, ops, seed=3, point=(77.62, 13.0)), ops.worker2
    )
    response = await client.get("/api/v1/workload", headers=ops.city.supervisor.headers)
    assert response.status_code == 200, response.text
    (team,) = response.json()["items"]
    assert (team["open"], team["pending_acceptance"], team["overdue"]) == (2, 2, 0)
    assert sorted(m["open"] for m in team["members"]) == [1, 1]
    assert (await client.get("/api/v1/workload", headers=ops.worker.headers)).status_code == 403


# --- tenancy ---------------------------------------------------------------------------------


async def test_other_tenant_cannot_see_teams_or_work_orders(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    other = await make_ops(client, sms, owner_engine)
    await assign(client, ops, await verified_issue(client, ops), ops.worker)
    wo = await work_order(client, ops.worker)
    assert (
        await client.get(f"{TEAMS}/{ops.team_id}", headers=other.city.admin.headers)
    ).status_code == 404
    assert (
        await client.get(f"{FIELD}/{wo['id']}", headers=other.worker.headers)
    ).status_code == 404


async def test_every_phase3_table_has_forced_rls(owner_engine: AsyncEngine) -> None:
    tables = (
        "teams",
        "team_members",
        "team_jurisdictions",
        "team_categories",
        "issue_assignments",
        "work_orders",
        "closure_requests",
        "issue_verifications",
        "outbox_events",
    )
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = ANY(:t)"
                ),
                {"t": list(tables)},
            )
        ).all()
    assert {r[0] for r in rows} == set(tables)
    assert all(r[1] and r[2] for r in rows)


# --- bulk actions (FR-078) -------------------------------------------------------------------

BULK = "/api/v1/issues/bulk"


async def test_bulk_assign_reports_each_item_and_audits(
    client: httpx.AsyncClient, ops: Ops, owner_engine: AsyncEngine
) -> None:
    first = await verified_issue(client, ops, seed=1)
    second = await verified_issue(client, ops, seed=9, point=NW)
    response = await client.post(
        BULK,
        headers=ops.city.supervisor.headers,
        json={
            "action": "assign",
            "team_id": ops.team_id,
            "assignee_id": ops.worker.user["id"],
            "items": [
                {"issue_id": first["id"], "version": first["version"]},
                # Stale: someone changed it since the queue was loaded.
                {"issue_id": second["id"], "version": second["version"] - 1},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["succeeded"], body["failed"]) == (1, 1)
    assert body["results"] == [
        {"issue_id": first["id"], "ok": True, "error": None},
        {"issue_id": second["id"], "ok": False, "error": "version_conflict"},
    ]
    assert (await issue(client, ops.city.supervisor, first["id"]))["status"] == "assigned"
    assert (await issue(client, ops.city.supervisor, second["id"]))["status"] == "verified"
    async with owner_engine.connect() as conn:
        assigned = (
            (
                await conn.execute(
                    text(
                        "SELECT entity_id::text FROM audit_events "
                        "WHERE action = 'issue.assigned' AND entity_id::text IN (:a, :b)"
                    ),
                    {"a": first["id"], "b": second["id"]},
                )
            )
            .scalars()
            .all()
        )
        summary = (
            await conn.execute(
                text(
                    "SELECT after FROM audit_events WHERE action = 'issue.bulk_action' "
                    "AND jsonb_exists(CAST(after AS jsonb) -> 'succeeded', :a)"
                ),
                {"a": first["id"]},
            )
        ).scalar_one()
    assert assigned == [first["id"]]
    assert summary["failed"] == {second["id"]: "version_conflict"}


async def _reported_issue(
    client: httpx.AsyncClient, ops: Ops, seed: int, point: tuple[float, float]
) -> dict[str, Any]:
    from tests.phase2 import scene_photo

    photo = await scene_photo(client, ops.city.citizen, seed)
    own = await report(client, ops.city, ops.city.citizen, point=point, media_ids=[photo])
    return await issue(client, ops.city.operator, own["issue"]["id"])


async def test_bulk_status_change_uses_the_single_issue_rules(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    first = await _reported_issue(client, ops, 1, NW)
    second = await _reported_issue(client, ops, 9, SW)
    items = [
        {"issue_id": first["id"], "version": first["version"]},
        {"issue_id": second["id"], "version": second["version"]},
    ]
    # Rejecting needs a reason, exactly as for one issue.
    response = await client.post(
        BULK,
        headers=ops.city.operator.headers,
        json={"action": "status", "to_status": "rejected", "items": items},
    )
    assert response.status_code == 200, response.text
    assert {r["error"] for r in response.json()["results"]} == {"reason_required"}

    response = await client.post(
        BULK,
        headers=ops.city.operator.headers,
        json={
            "action": "status",
            "to_status": "rejected",
            "reason": "Private land, not a municipal road",
            "items": items,
        },
    )
    assert response.json()["succeeded"] == 2, response.text
    assert (await issue(client, ops.city.operator, first["id"]))["status"] == "rejected"


async def test_bulk_assign_needs_the_assign_permission(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await verified_issue(client, ops)
    response = await client.post(
        BULK,
        headers=ops.city.operator.headers,
        json={
            "action": "assign",
            "team_id": ops.team_id,
            "items": [{"issue_id": detail["id"], "version": detail["version"]}],
        },
    )
    assert response.status_code == 404
    assert (await issue(client, ops.city.supervisor, detail["id"]))["status"] == "verified"


async def test_bulk_refuses_duplicates_and_oversized_batches(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await verified_issue(client, ops)
    item = {"issue_id": detail["id"], "version": detail["version"]}
    response = await client.post(
        BULK,
        headers=ops.city.operator.headers,
        json={"action": "status", "to_status": "under_review", "items": [item, item]},
    )
    assert response.status_code == 422
    response = await client.post(
        BULK,
        headers=ops.city.operator.headers,
        json={"action": "status", "to_status": "under_review", "items": [item] * 51},
    )
    assert response.status_code == 422
