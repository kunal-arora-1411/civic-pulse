"""Category suggestions while reporting (contract C, AC-02 and AC-03)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import httpx
import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai import registry
from app.ai.interfaces import CategoryScore
from app.ai.zero_shot import scores_from_similarities
from app.domains.ai.classifications import run
from app.domains.matching.service import watchdog
from tests.helpers import InlineJobs, Session
from tests.phase1 import City, login_new, make_city
from tests.phase2 import report, scene_photo, view

CLASSIFY = "/api/v1/ai/classifications"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _classify(client: httpx.AsyncClient, session: Session, *media_ids: str) -> httpx.Response:
    return await client.post(CLASSIFY, headers=session.headers, json={"media_ids": list(media_ids)})


async def test_a_confident_suggestion_comes_back_at_once(
    client: httpx.AsyncClient, city: City
) -> None:
    media = await scene_photo(client, city.citizen, 1, label="pothole:0.82")
    response = await _classify(client, city.citizen, media)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["model_id"] == "fake-vision@1"
    assert body["error"] is None
    assert [(s["code"], s["category_id"]) for s in body["suggestions"]] == [
        ("pothole", str(city.pothole)),
        ("waste", str(city.waste)),
    ]
    assert body["suggestions"][0]["confidence"] == pytest.approx(0.82)
    assert (body["not_civic"], body["needs_manual"]) == (False, False)
    again = await client.get(f"{CLASSIFY}/{body['id']}", headers=city.citizen.headers)
    assert again.json() == body


@pytest.mark.parametrize(
    ("label", "not_civic", "needs_manual"),
    [
        ("pothole:0.40", False, True),  # top, but below the 0.45 threshold
        ("not_civic", True, True),  # a soft warning; the citizen may still report
        (None, False, True),  # nothing recognisable at all
    ],
)
async def test_unsure_and_not_civic_results_ask_for_a_manual_choice(
    client: httpx.AsyncClient, city: City, label: str | None, not_civic: bool, needs_manual: bool
) -> None:
    media = await scene_photo(client, city.citizen, 2, label=label)
    body = (await _classify(client, city.citizen, media)).json()
    assert body["status"] == "done"
    assert (body["not_civic"], body["needs_manual"]) == (not_civic, needs_manual)
    assert len(body["suggestions"]) <= 3


async def test_the_threshold_comes_from_the_matching_config(
    client: httpx.AsyncClient, city: City
) -> None:
    await client.put(
        "/api/v1/admin/matching-config",
        headers=city.admin.headers,
        json={"classification_threshold": 0.35},
    )
    media = await scene_photo(client, city.citizen, 3, label="pothole:0.40")
    assert (await _classify(client, city.citizen, media)).json()["needs_manual"] is False


class _ThresholdedClassifier:
    """Answers like PromptZeroShotClassifier built with a threshold of its
    own: below it, `unknown` comes first with 1 - top, then the full
    distribution, so the scores add up to more than 1."""

    def __init__(self, similarities: dict[str, float], threshold: float) -> None:
        self.similarities = similarities
        self.threshold = threshold

    def classify(self, image_embeddings: Any, prompts: dict[str, list[str]]) -> list[CategoryScore]:
        codes = sorted(prompts)
        sims = np.array([self.similarities.get(code, 0.0) for code in codes])
        return scores_from_similarities(codes, sims, temperature=0.02, threshold=self.threshold)


@pytest.mark.parametrize(
    ("tenant_threshold", "needs_manual"),
    [(0.30, False), (0.45, True), (0.60, True)],
)
async def test_the_tenant_threshold_wins_over_the_classifier_own(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    monkeypatch: pytest.MonkeyPatch,
    tenant_threshold: float,
    needs_manual: bool,
) -> None:
    # Pothole wins with about 0.42 of the probability: under the
    # classifier's own 0.45, so it also returns `unknown` at about 0.58.
    stub = _ThresholdedClassifier({"pothole": 0.30, "waste": 0.295, "not_civic": 0.29}, 0.45)
    monkeypatch.setattr(registry, "get_classifier", lambda: stub)
    await client.put(
        "/api/v1/admin/matching-config",
        headers=city.admin.headers,
        json={"classification_threshold": tenant_threshold},
    )
    media = await scene_photo(client, city.citizen, 9)
    body = (await _classify(client, city.citizen, media)).json()

    assert body["status"] == "done"
    assert body["needs_manual"] is needs_manual
    assert body["not_civic"] is False
    top = body["suggestions"][0]
    assert top["code"] == "pothole"
    assert 0.35 < top["confidence"] < 0.45
    assert sum(s["confidence"] for s in body["suggestions"]) <= 1.0

    # What is stored is the distribution alone, led by the real winner.
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT scores, top_code, top_confidence FROM classifications WHERE id = :i"),
                {"i": body["id"]},
            )
        ).one()
    assert "unknown" not in {s["code"] for s in row.scores}
    assert sum(s["confidence"] for s in row.scores) == pytest.approx(1.0, abs=1e-3)
    assert (row.top_code, row.top_confidence) == ("pothole", top["confidence"])


async def test_a_slow_classification_answers_202_and_is_polled(
    client: httpx.AsyncClient,
    city: City,
    jobs: InlineJobs,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_classification_wait_seconds", 0.2)
    jobs.inline = False  # nobody has picked it up yet
    media = await scene_photo(client, city.citizen, 4, label="waste")
    response = await _classify(client, city.citizen, media)
    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["status"], body["needs_manual"], body["suggestions"]) == ("pending", True, [])
    poll = await client.get(f"{CLASSIFY}/{body['id']}", headers=city.citizen.headers)
    assert poll.json()["status"] == "pending"

    assert await run(uuid.UUID(body["id"]), city.tenant.id) == "done"
    done = (await client.get(f"{CLASSIFY}/{body['id']}", headers=city.citizen.headers)).json()
    assert done["status"] == "done"
    assert done["suggestions"][0]["code"] == "waste"
    # Running the task again leaves the result alone.
    assert await run(uuid.UUID(body["id"]), city.tenant.id) == "done"


async def test_the_ai_being_down_is_a_failed_result_not_an_error(
    client: httpx.AsyncClient, city: City, jobs: InlineJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = await scene_photo(client, city.citizen, 5, label="pothole")
    jobs.broker_up = False
    response = await _classify(client, city.citizen, media)
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["error"]) == ("failed", "ai_unavailable")
    assert response.json()["needs_manual"] is True

    jobs.broker_up = True

    def unavailable() -> Any:
        raise RuntimeError("no weights")

    monkeypatch.setattr(registry, "get_vision_model", unavailable)
    response = await _classify(client, city.citizen, media)
    assert (response.json()["status"], response.json()["error"]) == ("failed", "ai_unavailable")


async def test_an_abandoned_classification_fails_on_read_and_in_the_watchdog(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    jobs: InlineJobs,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_classification_wait_seconds", 0.0)
    jobs.inline = False
    media = await scene_photo(client, city.citizen, 6)
    first = (await _classify(client, city.citizen, media)).json()
    second = (await _classify(client, city.citizen, media)).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE classifications SET created_at = now() - interval '5 minutes' WHERE id = :i"
            ),
            {"i": first["id"]},
        )
    stale = (await client.get(f"{CLASSIFY}/{first['id']}", headers=city.citizen.headers)).json()
    assert (stale["status"], stale["error"]) == ("failed", "ai_unavailable")

    async with owner_engine.connect() as conn:
        created = (
            await conn.execute(
                text("SELECT created_at FROM classifications WHERE id = :i"), {"i": second["id"]}
            )
        ).scalar_one()
    result = await watchdog(now=created + timedelta(minutes=2))
    assert result.failed_classifications >= 1
    after = (await client.get(f"{CLASSIFY}/{second['id']}", headers=city.citizen.headers)).json()
    assert after["status"] == "failed"


async def test_only_your_own_completed_photos_can_be_classified(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    stranger = await login_new(client, sms, owner_engine, city, "citizen")
    theirs = await scene_photo(client, stranger, 7)
    response = await _classify(client, city.citizen, theirs)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["media"] == [{"id": theirs, "reason": "not_found"}]
    assert (await _classify(client, city.citizen)).status_code == 422  # at least one

    mine = (await _classify(client, stranger, theirs)).json()
    assert (
        await client.get(f"{CLASSIFY}/{mine['id']}", headers=city.citizen.headers)
    ).status_code == 404
    other = await make_city(client, sms, owner_engine)
    assert (
        await client.get(f"{CLASSIFY}/{mine['id']}", headers=other.citizen.headers)
    ).status_code == 404
    assert (await _classify(client, city.operator, theirs)).status_code == 403


async def test_reports_record_whether_the_suggestion_was_kept(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    async def classified(seed: int, label: str) -> tuple[str, str]:
        media = await scene_photo(client, city.citizen, seed, label=label)
        return media, (await _classify(client, city.citizen, media)).json()["id"]

    media, classification = await classified(20, "pothole")
    accepted = await report(
        client, city, city.citizen, media_ids=[media], classification_id=classification
    )
    media, classification = await classified(21, "pothole")
    corrected = await report(
        client,
        city,
        city.citizen,
        category=city.waste,
        point=(77.62, 12.995),
        media_ids=[media],
        classification_id=classification,
    )
    plain = await report(
        client,
        city,
        city.citizen,
        point=(77.60, 13.0),
        media_ids=[await scene_photo(client, city.citizen, 22)],
    )
    sources = [
        (await view(client, city.operator, r["id"]))["category_source"]
        for r in (accepted, corrected, plain)
    ]
    assert sources == ["ai_accepted", "ai_corrected", "citizen"]

    stranger = await login_new(client, sms, owner_engine, city, "citizen")
    media = await scene_photo(client, stranger, 23)
    response = await client.post(
        "/api/v1/reports",
        headers={**stranger.headers, "Idempotency-Key": uuid.uuid4().hex},
        json={
            "category_id": str(city.waste),
            "description": "Not my classification",
            "location": {"lat": 12.99, "lng": 77.61, "source": "gps"},
            "media_ids": [media],
            "classification_id": classification,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["loc"] == ["body", "classification_id"]
