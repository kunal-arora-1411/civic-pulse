"""Merge, split and related issues (AC-07, AC-08, FR-060)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import Session
from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, north_of, report, scene_photo, view


@dataclass
class Setup:
    city: City
    neighbour: Session
    a: dict[str, Any]  # issue with two reports from two citizens
    a_reports: list[str]
    b: dict[str, Any]  # issue with one report, 200 m away
    b_report: str


@pytest.fixture
async def setup(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> Setup:
    city = await make_city(client, sms, owner_engine)
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 40)]
    )
    second = await report(
        client,
        city,
        neighbour,
        point=north_of(NE, 2),
        media_ids=[await scene_photo(client, neighbour, 40, variant=1)],
    )
    assert second["issue"]["id"] == first["issue"]["id"]
    other = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 200),
        media_ids=[await scene_photo(client, city.citizen, 41)],
    )
    return Setup(
        city=city,
        neighbour=neighbour,
        a=await issue(client, city.operator, first["issue"]["id"]),
        a_reports=[first["id"], second["id"]],
        b=await issue(client, city.operator, other["issue"]["id"]),
        b_report=other["id"],
    )


async def _merge(
    client: httpx.AsyncClient, session: Session, survivor: dict, *sources: dict, **body: Any
) -> httpx.Response:
    payload = {
        "source_issue_ids": [s["id"] for s in sources],
        "reason": "Same pothole",
        "version": survivor["version"],
        **body,
    }
    return await client.post(
        f"{ISSUES}/{survivor['id']}/merge", headers=session.headers, json=payload
    )


async def _actions(engine: AsyncEngine, entity_id: str) -> list[str]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text("SELECT action FROM audit_events WHERE entity_id = :e ORDER BY id"),
                    {"e": entity_id},
                )
            ).scalars()
        )


# --- merge (AC-07) ---------------------------------------------------------------------------


async def test_merge_moves_reports_and_keeps_history_and_references(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    response = await _merge(client, op, s.a, s.b)
    assert response.status_code == 200, response.text
    survivor = response.json()
    assert (survivor["report_count"], survivor["unique_reporter_count"]) == (3, 2)
    assert survivor["status"] == "reported"  # keeps its own status
    assert survivor["version"] == s.a["version"] + 1
    assert sorted(r["id"] for r in survivor["reports"]) == sorted([*s.a_reports, s.b_report])
    merged_event = survivor["timeline"][-1]
    assert (merged_event["type"], merged_event["visibility"]) == ("merged", "public")
    assert merged_event["related_issue"] == {"id": s.b["id"], "reference": s.b["reference"]}
    assert merged_event["reason"] == "Same pothole"
    assert merged_event["data"]["report_ids"] == [s.b_report]

    # The merged issue is still readable, with its reference and history.
    gone = await issue(client, op, s.b["id"])
    assert gone["merged_into"] == {"id": s.a["id"], "reference": s.a["reference"]}
    assert gone["reference"] == s.b["reference"]
    assert (gone["report_count"], gone["reports"], gone["allowed_transitions"]) == (0, [], [])
    assert [e["type"] for e in gone["timeline"]] == ["created", "merged_into"]
    assert gone["priority"]["score"] == 0
    assert gone["priority"]["factors"][0]["value"] == "merged"

    # ...but drops out of the list, the map and search.
    ids = [i["id"] for i in (await client.get(ISSUES, headers=op.headers)).json()["items"]]
    assert s.b["id"] not in ids
    assert s.a["id"] in ids
    features = (
        await client.get(
            f"{ISSUES}/geojson", headers=op.headers, params={"bbox": "77.5,12.9,77.7,13.1"}
        )
    ).json()
    assert s.b["id"] not in [f["id"] for f in features["features"]]
    found = (await client.get(ISSUES, headers=op.headers, params={"q": s.b["reference"]})).json()
    assert s.b["id"] not in [i["id"] for i in found["items"]]

    # The citizen's report follows; the public timeline says what happened.
    moved = await view(client, s.city.citizen, s.b_report)
    assert moved["issue"]["id"] == s.a["id"]
    assert moved["matching_status"] == "new_issue"  # how it was first placed
    public = moved["issue"]["timeline"][-1]
    assert public == {
        "at": public["at"],
        "type": "merged",
        "from_status": None,
        "to_status": None,
        "public_note": None,
    }

    assert await _actions(owner_engine, s.a["id"]) == [
        "issue.created", "issue.report_linked", "issue.merged",
    ]  # fmt: skip
    assert (await _actions(owner_engine, s.b["id"]))[-1] == "issue.merged_into"


async def test_merged_issues_are_never_matching_candidates(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, setup: Setup
) -> None:
    s = setup
    assert (await _merge(client, s.city.operator, s.a, s.b)).status_code == 200
    again = await report(
        client,
        s.city,
        s.city.citizen,
        point=north_of(NE, 200),
        media_ids=[await scene_photo(client, s.city.citizen, 41, variant=1)],
    )
    async with owner_engine.connect() as conn:
        candidates = (
            (
                await conn.execute(
                    text("SELECT candidate_issue_id FROM match_decisions WHERE report_id = :r"),
                    {"r": again["id"]},
                )
            )
            .scalars()
            .all()
        )
    assert s.b["id"] not in [str(c) for c in candidates]


async def test_invalid_merges_are_rejected(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    itself = await _merge(client, op, s.a, s.a)
    assert (itself.status_code, itself.json()["error"]["code"]) == (422, "invalid_merge")
    stale = await _merge(client, op, s.a, s.b, version=s.a["version"] + 5)
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")
    blank = await _merge(client, op, s.a, s.b, reason="  ")
    assert blank.json()["error"]["code"] == "reason_required"
    assert (await _merge(client, s.city.supervisor, s.a, s.b)).status_code == 403  # no issue:merge

    south = await login_new(
        client, sms, owner_engine, s.city, "operator", jurisdiction_id=s.city.zones["S"]
    )
    assert (await _merge(client, south, s.a, s.b)).status_code == 404
    other = await make_city(client, sms, owner_engine)
    assert (await _merge(client, other.operator, s.a, s.b)).status_code == 404

    assert (await _merge(client, op, s.a, s.b)).status_code == 200
    b = await issue(client, op, s.b["id"])
    into_merged = await _merge(client, op, b, s.a)
    assert (into_merged.status_code, into_merged.json()["error"]["code"]) == (422, "invalid_merge")
    a = await issue(client, op, s.a["id"])
    twice = await _merge(client, op, a, b)
    assert twice.json()["error"]["details"]["reason"] == "source_is_merged"


async def test_merging_a_survivor_again_keeps_redirects_one_hop(
    client: httpx.AsyncClient, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    d_report = await report(
        client,
        s.city,
        s.city.citizen,
        point=north_of(NE, 600),
        media_ids=[await scene_photo(client, s.city.citizen, 42)],
    )
    d = await issue(client, op, d_report["issue"]["id"])
    assert (await _merge(client, op, s.a, s.b)).status_code == 200
    a = await issue(client, op, s.a["id"])
    assert (await _merge(client, op, d, a)).status_code == 200
    assert (await issue(client, op, s.b["id"]))["merged_into"]["id"] == d["id"]
    final = await issue(client, op, d["id"])
    assert (final["report_count"], final["unique_reporter_count"]) == (4, 2)


# --- split (AC-08) ---------------------------------------------------------------------------


async def test_split_moves_reports_to_a_new_issue(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    response = await client.post(
        f"{ISSUES}/{s.a['id']}/split",
        headers=op.headers,
        json={
            "report_ids": [s.a_reports[1]],
            "target": {"new_issue": True},
            "reason": "Two different potholes",
            "version": s.a["version"],
        },
    )
    assert response.status_code == 200, response.text
    source, target = response.json()["source"], response.json()["target"]
    assert [r["id"] for r in source["reports"]] == [s.a_reports[0]]
    assert [r["id"] for r in target["reports"]] == [s.a_reports[1]]
    assert (source["report_count"], source["unique_reporter_count"]) == (1, 1)
    assert (target["report_count"], target["unique_reporter_count"]) == (1, 1)
    assert target["status"] == "reported"
    assert target["category"]["id"] == s.a["category"]["id"]
    assert target["location"]["lat"] == pytest.approx(north_of(NE, 2)[1], abs=1e-6)
    assert target["reference"] != source["reference"]
    assert source["version"] == s.a["version"] + 1
    assert target["thumb_url"] is not None or target["reports"][0]["media"]
    out, into = source["timeline"][-1], target["timeline"][-1]
    assert (out["type"], out["visibility"], out["data"]["direction"]) == (
        "split",
        "internal",
        "out",
    )
    assert (into["type"], into["related_issue"]["id"]) == ("split", source["id"])
    assert target["timeline"][0]["type"] == "created"

    # The neighbour sees their report on the new issue, and no internal note.
    mine = await view(client, s.neighbour, s.a_reports[1])
    assert mine["issue"]["id"] == target["id"]
    assert [e["type"] for e in mine["issue"]["timeline"]] == ["created"]
    assert "issue.split" in await _actions(owner_engine, s.a["id"])


async def test_split_into_an_existing_issue_and_invalid_splits(
    client: httpx.AsyncClient, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    url = f"{ISSUES}/{s.a['id']}/split"

    async def split(**body: Any) -> httpx.Response:
        payload = {
            "report_ids": [s.a_reports[1]],
            "target": {"issue_id": s.b["id"]},
            "reason": "Belongs there",
            "version": s.a["version"],
            **body,
        }
        return await client.post(url, headers=op.headers, json=payload)

    everything = await split(report_ids=s.a_reports)
    assert (everything.status_code, everything.json()["error"]["code"]) == (
        422,
        "cannot_empty_issue",
    )
    foreign = await split(report_ids=[s.b_report])
    assert foreign.status_code == 422
    assert foreign.json()["error"]["details"]["report_ids"] == [s.b_report]
    itself = await split(target={"issue_id": s.a["id"]})
    assert itself.status_code == 422
    assert (await split(reason="")).json()["error"]["code"] == "reason_required"
    assert (await split(version=99)).status_code == 409
    assert (await split(target={"issue_id": s.b["id"], "new_issue": True})).status_code == 422

    moved = await split()
    assert moved.status_code == 200, moved.text
    target = moved.json()["target"]
    assert target["id"] == s.b["id"]
    assert (target["report_count"], target["unique_reporter_count"]) == (2, 2)
    assert target["version"] == s.b["version"] + 1


# --- related issues --------------------------------------------------------------------------


async def test_related_issues_are_linked_listed_and_unlinked(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, setup: Setup
) -> None:
    s, op = setup, setup.city.operator
    url = f"{ISSUES}/{s.a['id']}/related"
    created = await client.post(
        url, headers=op.headers, json={"issue_id": s.b["id"], "note": " Same drain line "}
    )
    assert created.status_code == 201, created.text
    assert created.json()["issue"]["id"] == s.b["id"]
    assert created.json()["note"] == "Same drain line"
    # Stored once per pair, visible from both sides.
    assert [r["issue"]["id"] for r in (await issue(client, op, s.b["id"]))["related"]] == [
        s.a["id"]
    ]
    again = await client.post(
        f"{ISSUES}/{s.b['id']}/related", headers=op.headers, json={"issue_id": s.a["id"]}
    )
    assert again.status_code == 409
    itself = await client.post(url, headers=op.headers, json={"issue_id": s.a["id"]})
    assert itself.status_code == 422
    assert (
        await client.post(url, headers=s.city.supervisor.headers, json={"issue_id": s.b["id"]})
    ).status_code == 409
    assert (
        await client.post(url, headers=s.city.admin.headers, json={"issue_id": s.b["id"]})
    ).status_code == 403

    removed = await client.delete(f"{url}/{s.b['id']}", headers=op.headers)
    assert removed.status_code == 204
    assert (await issue(client, op, s.a["id"]))["related"] == []
    assert (await client.delete(f"{url}/{s.b['id']}", headers=op.headers)).status_code == 404
    assert await _actions(owner_engine, s.a["id"]) == [
        "issue.created", "issue.report_linked", "issue.related_added", "issue.related_removed",
    ]  # fmt: skip
