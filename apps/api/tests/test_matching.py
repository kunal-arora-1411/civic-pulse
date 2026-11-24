"""Duplicate matching end to end (AC-04 to AC-06, FR-036): real Postgres
with pgvector, real MinIO, and the deterministic fake vision model."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai import registry
from app.domains.ai.analysis import ensure_embeddings
from app.domains.matching.service import decide_and_apply, process_report, watchdog
from tests.helpers import InlineJobs
from tests.phase1 import NE, SW, City, login_new, make_city
from tests.phase2 import issue, north_of, report, scene_photo, view


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


@pytest.fixture
def ai_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> Any:
        raise RuntimeError("model weights missing")

    monkeypatch.setattr(registry, "get_vision_model", unavailable)


# --- AC-04: a matching report joins the issue ----------------------------------------------


async def test_a_duplicate_links_and_counts_distinct_reporters(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 1)]
    )
    assert first["matching_status"] == "new_issue"
    issue_id = first["issue"]["id"]

    # Another citizen, another shot of the same scene, three metres away.
    second = await report(
        client,
        city,
        neighbour,
        point=north_of(NE, 3),
        media_ids=[await scene_photo(client, neighbour, 1, variant=1)],
    )
    assert second["matching_status"] == "linked"
    assert second["issue"]["id"] == issue_id
    assert [e["type"] for e in second["issue"]["timeline"]] == ["created"]  # internal event
    assert (second["issue"]["report_count"], second["issue"]["unique_reporter_count"]) == (2, 2)

    detail = await issue(client, city.operator, issue_id)
    assert (detail["report_count"], detail["unique_reporter_count"]) == (2, 2)
    assert detail["version"] == 2

    # The first reporter again: one more report, still two distinct people.
    again = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 1, variant=2)],
    )
    assert again["issue"]["id"] == issue_id
    detail = await issue(client, city.operator, issue_id)
    assert (detail["report_count"], detail["unique_reporter_count"]) == (3, 2)
    assert [r["id"] for r in detail["reports"]] == [first["id"], second["id"], again["id"]]
    assert detail["priority"]["factors"]  # recomputed on every link

    # Staff see why it was linked.
    staff = await view(client, city.operator, second["id"])
    assert staff["match"]["decision"] == "auto_linked"
    signals = staff["match"]["signals"]
    assert signals["visual"] >= 0.8
    assert signals["distance_m"] == pytest.approx(3.0, abs=0.2)
    assert set(signals) == {
        "distance_m", "radius_m", "geo", "visual", "same_photo", "category", "time",
        "age_days", "weights", "thresholds", "reason",
    }  # fmt: skip
    rows = await _decisions(owner_engine, second["id"])
    assert [(str(r.candidate_issue_id), r.decision, r.decided_by) for r in rows] == [
        (issue_id, "auto_linked", None)
    ]
    assert (
        await _scalar(
            owner_engine,
            "SELECT count(*) FROM audit_events WHERE action = 'issue.report_linked' "
            "AND entity_id = :i",
            i=issue_id,
        )
        == 2
    )


# --- AC-05: close by but different: never auto-linked ----------------------------------------


async def test_nearby_but_visually_different_is_not_linked(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 2)]
    )
    other = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 10),
        media_ids=[await scene_photo(client, city.citizen, 3)],
    )
    assert other["matching_status"] == "new_issue"
    assert other["issue"]["id"] != first["issue"]["id"]
    (row,) = await _decisions(owner_engine, other["id"])
    assert row.decision == "rejected_candidate"
    assert row.signals["visual"] < 0.5


async def test_a_different_category_on_the_same_spot_is_not_a_candidate(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 4)]
    )
    waste = await report(
        client,
        city,
        city.citizen,
        category=city.waste,
        media_ids=[await scene_photo(client, city.citizen, 4, variant=1)],
        description="Rubble dumped in the pothole",
    )
    assert waste["matching_status"] == "new_issue"
    assert waste["issue"]["id"] != first["issue"]["id"]
    assert await _decisions(owner_engine, waste["id"]) == []


async def test_without_a_photo_a_report_is_never_auto_linked(
    client: httpx.AsyncClient, city: City
) -> None:
    first = await report(
        client, city, city.citizen, category=city.waste, description="Garbage heap at the corner"
    )
    same_spot = await report(
        client,
        city,
        city.citizen,
        category=city.waste,
        description="Garbage heap at the corner again",
    )
    assert first["matching_status"] == "new_issue"
    assert same_spot["matching_status"] == "review"
    assert same_spot["issue"] is None
    staff = await view(client, city.operator, same_spot["id"])
    assert staff["match"]["signals"]["reason"] == "no_photos"
    assert staff["match"]["decision"] == "sent_to_review"


# --- AC-06: ambiguous goes to a person --------------------------------------------------------


async def test_an_ambiguous_match_opens_a_review_task(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
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
    (row,) = await _decisions(owner_engine, unsure["id"])
    assert str(row.candidate_issue_id) == first["issue"]["id"]
    assert row.decision == "sent_to_review"
    assert 0.6 <= row.score < 0.85
    assert row.signals["visual"] >= 0.8
    assert row.signals["distance_m"] == pytest.approx(20, abs=0.5)
    assert (
        await _scalar(
            owner_engine,
            "SELECT count(*) FROM review_tasks WHERE report_id = :r AND status = 'open'",
            r=unsure["id"],
        )
        == 1
    )
    staff = await view(client, city.operator, unsure["id"])
    assert staff["match"]["match_decision_id"] is not None
    assert staff["match"]["decision"] == "sent_to_review"


# --- AI unavailable --------------------------------------------------------------------------


async def test_without_the_ai_matching_waits_then_never_auto_links(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 11)]
    )

    def unavailable() -> Any:
        raise RuntimeError("model weights missing")

    monkeypatch.setattr(registry, "get_vision_model", unavailable)
    # The very same photo again on the same spot: a sure link with the AI.
    dup = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 11, variant=1)],
    )
    assert dup["matching_status"] == "pending"  # waiting for embeddings
    created = await _scalar(
        owner_engine, "SELECT created_at FROM reports WHERE id = :r", r=dup["id"]
    )

    early = await process_report(
        uuid.UUID(dup["id"]), city.tenant.id, now=created + timedelta(seconds=30)
    )
    assert (early.status, early.retry_in) == ("retry", 15)

    late = await process_report(
        uuid.UUID(dup["id"]), city.tenant.id, now=created + timedelta(minutes=3)
    )
    assert (late.status, late.fallback) == ("review", True)
    (row,) = await _decisions(owner_engine, dup["id"])
    assert row.decision == "sent_to_review"
    assert row.signals["visual"] is None
    assert row.signals["reason"] == "ai_unavailable"
    assert row.signals["thresholds"]["fallback_review"] == 0.4
    detail = await issue(client, city.operator, first["issue"]["id"])
    assert detail["report_count"] == 1  # never linked automatically


@pytest.mark.usefixtures("ai_down")
async def test_the_fallback_starts_a_new_issue_when_nothing_scores_high_enough(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    lonely = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 12)]
    )
    created = await _scalar(
        owner_engine, "SELECT created_at FROM reports WHERE id = :r", r=lonely["id"]
    )
    outcome = await process_report(
        uuid.UUID(lonely["id"]), city.tenant.id, now=created + timedelta(minutes=3)
    )
    assert (outcome.status, outcome.fallback) == ("new_issue", True)


@pytest.mark.usefixtures("ai_down")
async def test_the_watchdog_requeues_then_falls_back(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City, jobs: InlineJobs
) -> None:
    jobs.inline = False  # the message was lost
    await report(
        client, city, city.citizen, category=city.waste, description="Overflowing bin by the gate"
    )
    stuck = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 13)]
    )
    assert stuck["matching_status"] == "pending"
    created = await _scalar(
        owner_engine, "SELECT created_at FROM reports WHERE id = :r", r=stuck["id"]
    )
    key = (uuid.UUID(stuck["id"]), city.tenant.id)

    soon = await watchdog(now=created + timedelta(seconds=20))
    assert key not in soon.requeue
    later = await watchdog(now=created + timedelta(seconds=90))
    assert key in later.requeue
    assert (await view(client, city.citizen, stuck["id"]))["matching_status"] == "pending"

    await watchdog(now=created + timedelta(minutes=3))
    placed = await view(client, city.citizen, stuck["id"])
    assert placed["matching_status"] == "new_issue"
    assert key not in (await watchdog(now=created + timedelta(minutes=4))).requeue


# --- idempotency and concurrency --------------------------------------------------------------


async def test_matching_a_decided_report_again_changes_nothing(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 14)]
    )
    dup = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 14, variant=1)],
    )
    before = await _decisions(owner_engine, dup["id"])
    for _ in range(3):
        again = await process_report(uuid.UUID(dup["id"]), city.tenant.id)
        assert again.status == "already_decided"
        direct = await decide_and_apply(
            uuid.UUID(dup["id"]), city.tenant.id, model_id=None, fallback=True
        )
        assert direct.status == "already_decided"
    assert await _decisions(owner_engine, dup["id"]) == before
    detail = await issue(client, city.operator, first["issue"]["id"])
    assert (detail["report_count"], detail["version"]) == (2, 2)


async def test_embeddings_are_computed_once_per_photo(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City, jobs: InlineJobs
) -> None:
    media_id = await scene_photo(client, city.citizen, 15)
    model = await ensure_embeddings(city.tenant.id, [uuid.UUID(media_id)])
    await ensure_embeddings(city.tenant.id, [uuid.UUID(media_id)])
    await report(client, city, city.citizen, media_ids=[media_id])
    rows = await _scalar(
        owner_engine, "SELECT count(*) FROM media_embeddings WHERE media_id = :m", m=media_id
    )
    assert rows == 1
    registered = await _scalar(
        owner_engine, "SELECT task FROM model_registry WHERE id = :m", m=model
    )
    assert registered == "embedding"


@pytest.mark.parametrize("attempt", range(3))
async def test_simultaneous_identical_reports_make_exactly_one_issue(
    client: httpx.AsyncClient,
    sms: Any,
    owner_engine: AsyncEngine,
    city: City,
    jobs: InlineJobs,
    attempt: int,
) -> None:
    jobs.inline = False
    citizens = [city.citizen] + [
        await login_new(client, sms, owner_engine, city, "citizen") for _ in range(9)
    ]
    reports = [
        await report(
            client,
            city,
            citizen,
            point=north_of(SW, n * 0.5),
            media_ids=[await scene_photo(client, citizen, 100 + attempt, variant=n)],
        )
        for n, citizen in enumerate(citizens)
    ]
    assert {r["matching_status"] for r in reports} == {"pending"}

    outcomes = await asyncio.gather(
        *(process_report(uuid.UUID(r["id"]), city.tenant.id) for r in reports)
    )
    assert sorted(o.status for o in outcomes) == ["auto_link"] * 9 + ["new_issue"]

    async with owner_engine.connect() as conn:
        issues = (
            await conn.execute(
                text(
                    "SELECT id, report_count, unique_reporter_count FROM civic_issues "
                    "WHERE tenant_id = :t"
                ),
                {"t": city.tenant.id},
            )
        ).all()
        statuses = (
            await conn.execute(
                text(
                    "SELECT matching_status, count(*) FROM reports WHERE tenant_id = :t "
                    "GROUP BY matching_status"
                ),
                {"t": city.tenant.id},
            )
        ).all()
        linked_events = await conn.scalar(
            text(
                "SELECT count(*) FROM issue_events WHERE issue_id = :i AND type = 'report_linked'"
            ),
            {"i": issues[0].id},
        )
    assert len(issues) == 1
    assert (issues[0].report_count, issues[0].unique_reporter_count) == (10, 10)
    assert dict(statuses) == {"new_issue": 1, "linked": 9}
    assert linked_events == 9
