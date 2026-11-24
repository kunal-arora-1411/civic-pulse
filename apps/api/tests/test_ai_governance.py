"""The model registry and AI quality counts for administrators."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.ai.analysis import register_models
from tests.phase1 import NE, City, make_city
from tests.phase2 import REVIEW, issue, north_of, report, scene_photo

MODELS = "/api/v1/admin/ai/models"
QUALITY = "/api/v1/admin/ai/quality"
LOCK = Path(__file__).resolve().parents[1] / "models.lock.json"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def test_the_model_registry_marks_the_active_model(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 70)]
    )
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO model_registry (id, task, name, version, deployed_at) VALUES "
                "('old-model@0', 'embedding', 'Retired model', '0', now() - interval '1 year') "
                "ON CONFLICT DO NOTHING"
            )
        )
    body = (await client.get(MODELS, headers=city.admin.headers)).json()
    by_id = {m["model_id"]: m for m in body["items"]}
    assert by_id["fake-vision@1"]["task"] == "embedding"
    assert by_id["fake-vision@1"]["active"] is True
    assert by_id["old-model@0"]["active"] is False
    assert set(by_id["fake-vision@1"]) == {
        "model_id", "task", "name", "version", "source", "license", "deployed_at",
        "intended_use", "metrics", "active",
    }  # fmt: skip


async def test_quality_counts_each_outcome(client: httpx.AsyncClient, city: City) -> None:
    async def classify(seed: int, label: str) -> tuple[str, str]:
        media = await scene_photo(client, city.citizen, seed, label=label)
        response = await client.post(
            "/api/v1/ai/classifications", headers=city.citizen.headers, json={"media_ids": [media]}
        )
        return media, response.json()["id"]

    media, classification = await classify(71, "pothole")
    first = await report(
        client, city, city.citizen, media_ids=[media], classification_id=classification
    )
    media, classification = await classify(72, "pothole")
    await report(
        client,
        city,
        city.citizen,
        category=city.waste,
        point=north_of(NE, 500),
        media_ids=[media],
        classification_id=classification,
    )
    dup = await report(
        client,
        city,
        city.citizen,
        media_ids=[await scene_photo(client, city.citizen, 71, variant=1)],
    )
    await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 71, variant=2)],
    )
    (task,) = (await client.get(REVIEW, headers=city.operator.headers)).json()["items"]
    await client.post(
        f"{REVIEW}/{task['id']}/resolve",
        headers=city.operator.headers,
        json={"action": "new_issue"},
    )
    detail = await issue(client, city.operator, first["issue"]["id"])
    (dup_view,) = [r for r in detail["reports"] if r["id"] == dup["id"]]
    await client.post(
        f"/api/v1/match-decisions/{dup_view['match_decisions'][0]['id']}/feedback",
        headers=city.operator.headers,
        json={"correct": True},
    )

    response = await client.get(QUALITY, headers=city.operator.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["to"] >= body["from"]
    assert body["classifications"] == {
        "done": 2,
        "failed": 0,
        "accepted_by_category": {"pothole": 1},
        "corrected_by_category": {"waste": 1},
    }
    assert body["matching"] == {"auto_linked": 1, "sent_to_review": 1, "new_issue": 2}
    assert body["reviews"] == {"linked": 0, "new_issue": 1}
    assert body["auto_link_feedback"] == {"correct": 1, "incorrect": 0}

    empty = (
        await client.get(
            QUALITY, headers=city.admin.headers, params={"from": "2020-01-01", "to": "2020-01-31"}
        )
    ).json()
    assert empty["matching"] == {"auto_linked": 0, "sent_to_review": 0, "new_issue": 0}
    assert (empty["from"], empty["to"]) == ("2020-01-01", "2020-01-31")


async def test_governance_endpoints_need_config_read(client: httpx.AsyncClient, city: City) -> None:
    for path in (MODELS, QUALITY):
        assert (await client.get(path, headers=city.citizen.headers)).status_code == 403
        assert (await client.get(path)).status_code == 401
    reversed_window = await client.get(
        QUALITY, headers=city.admin.headers, params={"from": "2026-02-01", "to": "2026-01-01"}
    )
    assert reversed_window.status_code == 422


# --- the AI worker registers its models at start-up -----------------------------------------


class _Consumer:
    """What Celery's worker_ready hands the signal: just the queue table."""

    def __init__(self, queues: list[str]) -> None:
        from app.worker import celery_app

        selected = celery_app.amqp.Queues([])
        for name in queues:
            selected.select_add(name)
        self.app = type("App", (), {"amqp": type("Amqp", (), {"queues": selected})()})()


def test_only_the_worker_on_the_ai_queue_registers_models() -> None:
    from app.domains.ai.tasks import consumes_ai_queue

    assert consumes_ai_queue(_Consumer(["ai"]))
    assert consumes_ai_queue(_Consumer(["default", "ai"]))
    assert not consumes_ai_queue(_Consumer(["default"]))


async def test_registering_the_real_models_records_lock_details_and_metrics(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Only the lock is read to describe the models; no weights needed.
    shutil.copy(LOCK, tmp_path / "models.lock.json")
    monkeypatch.setattr(settings, "ai_provider", "onnx")
    monkeypatch.setattr(settings, "ai_model_dir", str(tmp_path))

    assert await register_models() == ["clip-vit-b32@onnx-1", "yunet-2023mar@onnx-1"]

    body = (await client.get(MODELS, headers=city.admin.headers)).json()
    by_id = {m["model_id"]: m for m in body["items"]}
    clip = by_id["clip-vit-b32@onnx-1"]
    assert (clip["task"], clip["license"], clip["active"]) == ("embedding", "MIT", True)
    assert clip["source"].startswith("https://huggingface.co/Xenova/clip-vit-base-patch32@")
    assert clip["metrics"]["matching"] == {"visual_min": 0.92}
    assert by_id["yunet-2023mar@onnx-1"]["task"] == "face_detection"
    assert by_id["yunet-2023mar@onnx-1"]["active"] is True

    # A restart registers them again: details refreshed, still one row each.
    first_deployed = clip["deployed_at"]
    await register_models()
    again = {
        m["model_id"]: m
        for m in (await client.get(MODELS, headers=city.admin.headers)).json()["items"]
    }
    assert again["clip-vit-b32@onnx-1"]["deployed_at"] >= first_deployed
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM model_registry WHERE id = 'clip-vit-b32@onnx-1'")
        )
    assert count == 1


async def test_matching_uses_the_registered_model_floor(
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core.db import get_session_factory
    from app.domains.matching.service import model_visual_floor

    shutil.copy(LOCK, tmp_path / "models.lock.json")
    monkeypatch.setattr(settings, "ai_provider", "onnx")
    monkeypatch.setattr(settings, "ai_model_dir", str(tmp_path))
    await register_models()
    async with get_session_factory()() as db:
        assert await model_visual_floor(db, "clip-vit-b32@onnx-1") == 0.92
        assert await model_visual_floor(db, "yunet-2023mar@onnx-1") is None
        assert await model_visual_floor(db, None) is None
