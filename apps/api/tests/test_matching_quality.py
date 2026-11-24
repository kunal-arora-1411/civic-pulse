"""Weekly matching quality rollups and the drift alert job."""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import system_session
from app.domains.matching import quality
from app.domains.matching.quality import WeekRollup, find_alerts, week_start
from tests.phase1 import City, make_city
from tests.phase2 import issue, report, scene_photo

TENANT = uuid.uuid4()
WEEK = date(2026, 11, 16)


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _history(**counts: int) -> list[dict[quality.Key, WeekRollup]]:
    return [{(TENANT, "pothole"): WeekRollup(**counts)} for _ in range(4)]


def test_a_jump_in_false_merges_raises_an_alert() -> None:
    current = {(TENANT, "pothole"): WeekRollup(auto_linked=20, auto_link_undone=6)}
    (alert,) = find_alerts(
        WEEK, current, _history(auto_linked=10, auto_link_undone=1), ratio=1.5, min_samples=10
    )
    assert (alert.metric, alert.category, alert.samples) == ("false_merge_rate", "pothole", 20)
    assert alert.rate == pytest.approx(0.3)
    assert alert.baseline == pytest.approx(0.1)


def test_a_jump_in_corrections_raises_an_alert() -> None:
    current = {(TENANT, "pothole"): WeekRollup(suggested=10, corrected=5)}
    (alert,) = find_alerts(
        WEEK, current, _history(suggested=10, corrected=2), ratio=1.5, min_samples=10
    )
    assert alert.metric == "correction_rate"


def test_steady_or_sparse_weeks_stay_quiet() -> None:
    steady = {(TENANT, "pothole"): WeekRollup(auto_linked=20, auto_link_undone=2)}
    assert (
        find_alerts(
            WEEK, steady, _history(auto_linked=10, auto_link_undone=1), ratio=1.5, min_samples=10
        )
        == []
    )
    sparse = {(TENANT, "pothole"): WeekRollup(auto_linked=3, auto_link_undone=3)}
    assert (
        find_alerts(
            WEEK, sparse, _history(auto_linked=10, auto_link_undone=1), ratio=1.5, min_samples=10
        )
        == []
    )
    no_baseline = {(TENANT, "pothole"): WeekRollup(auto_linked=20, auto_link_undone=10)}
    assert find_alerts(WEEK, no_baseline, [], ratio=1.5, min_samples=10) == []


def test_the_job_checks_the_last_complete_week() -> None:
    assert quality.latest_complete_week(date(2026, 11, 25)) == WEEK
    assert quality.latest_complete_week(date(2026, 11, 23)) == WEEK


def test_the_job_runs_on_the_default_queue() -> None:
    from app.domains.matching.tasks import quality_check
    from app.worker import celery_app

    assert celery_app.amqp.router.route({}, quality_check.name)["queue"].name == "default"
    schedule = celery_app.conf.beat_schedule["matching-quality-weekly"]
    assert schedule["task"] == quality_check.name


async def test_rollup_counts_auto_links_undone_reviews_and_corrections(
    client: httpx.AsyncClient, city: City, caplog: pytest.LogCaptureFixture
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 81)]
    )
    dup = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 81, variant=1)],
    )
    detail = await issue(client, city.operator, first["issue"]["id"])
    (dup_view,) = [r for r in detail["reports"] if r["id"] == dup["id"]]
    response = await client.post(
        f"/api/v1/match-decisions/{dup_view['match_decisions'][0]['id']}/feedback",
        headers=city.operator.headers,
        json={"correct": False},
    )
    assert response.status_code < 300, response.text

    today = quality.latest_complete_week() + timedelta(days=7)
    async with system_session(reason="test") as db:
        rollups = await quality.weekly_rollup(db, week_start(today))
    mine = {code: r for (tenant, code), r in rollups.items() if tenant == city.tenant.id}
    total = WeekRollup()
    for r in mine.values():
        total.add(r)
    assert total.auto_linked == 1
    assert total.auto_link_undone == 1
    assert total.false_merge_rate == 1.0

    # The job is read-only and only logs; with no baseline it stays quiet.
    with caplog.at_level(logging.WARNING):
        run = await quality.check_latest_week(today + timedelta(days=7))
    assert run.alerts == []
