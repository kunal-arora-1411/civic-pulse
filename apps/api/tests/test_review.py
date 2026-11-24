"""The review queue and match feedback (FR-031, FR-035, FR-037)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import REVIEW, issue, north_of, report, scene_photo, view


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def _decisions(engine: AsyncEngine, report_id: str) -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT candidate_issue_id, rank, score, signals, decision, decided_by "
                        "FROM match_decisions WHERE report_id = :r ORDER BY rank"
                    ),
                    {"r": report_id},
                )
            ).all()
        )


async def test_a_review_task_shows_candidates_and_signals_and_resolves(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 6)]
    )
    # The same scene, but twenty metres away: strong visual, weaker distance.
    unsure = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 6, variant=1)],
    )
    assert unsure["matching_status"] == "review"
    assert unsure["issue"] is None

    page = (await client.get(REVIEW, headers=city.operator.headers)).json()
    assert page["total"] == 1
    (task,) = page["items"]
    assert task["status"] == "open"
    assert task["report"]["id"] == unsure["id"]
    assert task["report"]["view"] == "staff"
    (candidate,) = task["candidates"]
    assert candidate["issue"]["id"] == first["issue"]["id"]
    assert candidate["decision"] == "sent_to_review"
    assert 0.6 <= candidate["score"] < 0.85
    assert candidate["signals"]["visual"] >= 0.8
    assert candidate["signals"]["distance_m"] == pytest.approx(20, abs=0.5)
    single = await client.get(f"{REVIEW}/{task['id']}", headers=city.operator.headers)
    assert single.json() == task

    # Resolving links the report and records the choice.
    resolved = await client.post(
        f"{REVIEW}/{task['id']}/resolve",
        headers=city.operator.headers,
        json={"action": "link", "issue_id": first["issue"]["id"]},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert (body["status"], body["resolution"]) == ("resolved", "linked")
    assert body["resolved_issue_id"] == first["issue"]["id"]
    assert body["resolved_by"]["display_name"] == "Omar Operator"
    linked = await view(client, city.citizen, unsure["id"])
    assert linked["matching_status"] == "linked"
    assert linked["issue"]["id"] == first["issue"]["id"]
    (row,) = await _decisions(owner_engine, unsure["id"])
    assert row.decision == "chosen_by_reviewer"
    assert str(row.decided_by) == city.operator.user["id"]
    detail = await issue(client, city.operator, first["issue"]["id"])
    assert detail["report_count"] == 2
    assert (await client.get(REVIEW, headers=city.operator.headers)).json()["total"] == 0
    resolved_page = await client.get(
        REVIEW, headers=city.operator.headers, params={"status": "resolved"}
    )
    assert [t["id"] for t in resolved_page.json()["items"]] == [task["id"]]

    # Resolving again is a conflict.
    again = await client.post(
        f"{REVIEW}/{task['id']}/resolve",
        headers=city.operator.headers,
        json={"action": "new_issue"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


async def test_a_reviewer_can_start_a_new_issue_instead(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 7)]
    )
    unsure = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 7, variant=1)],
    )
    (task,) = (await client.get(REVIEW, headers=city.operator.headers)).json()["items"]
    not_a_candidate = await client.post(
        f"{REVIEW}/{task['id']}/resolve",
        headers=city.operator.headers,
        json={"action": "link", "issue_id": str(uuid.uuid4())},
    )
    assert not_a_candidate.status_code == 422
    response = await client.post(
        f"{REVIEW}/{task['id']}/resolve",
        headers=city.operator.headers,
        json={"action": "new_issue"},
    )
    assert response.status_code == 200, response.text
    placed = await view(client, city.citizen, unsure["id"])
    assert placed["matching_status"] == "new_issue"
    assert placed["issue"]["id"] not in (None, first["issue"]["id"])
    (row,) = await _decisions(owner_engine, unsure["id"])
    assert row.decision == "not_chosen"


async def test_two_reviewers_resolving_at_once_one_wins(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    second_operator = await login_new(client, sms, owner_engine, city, "operator")
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 8)]
    )
    await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 8, variant=1)],
    )
    (task,) = (await client.get(REVIEW, headers=city.operator.headers)).json()["items"]
    url = f"{REVIEW}/{task['id']}/resolve"
    responses = await asyncio.gather(
        client.post(
            url,
            headers=city.operator.headers,
            json={"action": "link", "issue_id": first["issue"]["id"]},
        ),
        client.post(url, headers=second_operator.headers, json={"action": "new_issue"}),
    )
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    # Exactly one outcome happened: either the link or a new issue, not both.
    issues = await _scalar(
        owner_engine, "SELECT count(*) FROM civic_issues WHERE tenant_id = :t", t=city.tenant.id
    )
    linked = await _scalar(
        owner_engine,
        "SELECT report_count FROM civic_issues WHERE id = :i",
        i=first["issue"]["id"],
    )
    assert (issues, linked) in {(1, 2), (2, 1)}


async def test_review_tasks_and_feedback_respect_scope_and_permissions(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    await report(client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 9)])
    unsure = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 9, variant=1)],
    )
    (task,) = (await client.get(REVIEW, headers=city.operator.headers)).json()["items"]
    decision_id = task["candidates"][0]["match_decision_id"]

    south = await login_new(
        client, sms, owner_engine, city, "operator", jurisdiction_id=city.zones["S"]
    )
    assert (await client.get(REVIEW, headers=south.headers)).json()["total"] == 0
    for session in (south,):
        assert (
            await client.get(f"{REVIEW}/{task['id']}", headers=session.headers)
        ).status_code == 404
        resolve = await client.post(
            f"{REVIEW}/{task['id']}/resolve", headers=session.headers, json={"action": "new_issue"}
        )
        assert resolve.status_code == 404
        feedback = await client.post(
            f"/api/v1/match-decisions/{decision_id}/feedback",
            headers=session.headers,
            json={"correct": True},
        )
        assert feedback.status_code == 404

    other = await make_city(client, sms, owner_engine)
    assert (
        await client.get(f"{REVIEW}/{task['id']}", headers=other.operator.headers)
    ).status_code == 404
    assert (await client.get(REVIEW, headers=other.operator.headers)).json()["total"] == 0

    # Supervisors and admins don't triage; citizens certainly don't.
    for session in (city.citizen, city.supervisor, city.admin):
        assert (await client.get(REVIEW, headers=session.headers)).status_code == 403
    assert (await client.get(REVIEW)).status_code == 401
    assert unsure["matching_status"] == "review"


async def test_feedback_on_an_auto_link_is_stored_and_audited(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 10)]
    )
    dup = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 10, variant=1)],
    )
    detail = await issue(client, city.operator, first["issue"]["id"])
    (dup_view,) = [r for r in detail["reports"] if r["id"] == dup["id"]]
    (auto,) = dup_view["match_decisions"]
    assert auto["candidate_issue_id"] == first["issue"]["id"]
    assert auto["decision"] == "auto_linked"
    assert auto["candidate_issue"]["reference"] == detail["reference"]

    url = f"/api/v1/match-decisions/{auto['id']}/feedback"
    response = await client.post(
        url, headers=city.operator.headers, json={"correct": False, "note": " Two potholes "}
    )
    assert response.status_code == 200, response.text
    assert (response.json()["feedback"], response.json()["feedback_note"]) == (
        "incorrect",
        "Two potholes",
    )
    response = await client.post(url, headers=city.operator.headers, json={"correct": True})
    assert response.json()["feedback"] == "correct"
    assert (
        await _scalar(
            owner_engine,
            "SELECT count(*) FROM audit_events WHERE action = 'match_decision.feedback' "
            "AND entity_id = :d",
            d=auto["id"],
        )
        == 2
    )
    assert (
        await client.post(url, headers=city.citizen.headers, json={"correct": True})
    ).status_code == 403
