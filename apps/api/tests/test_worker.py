from __future__ import annotations

from app.worker import celery_app, ping


def test_ping_task_is_registered_and_returns_pong() -> None:
    assert "civicpulse.ping" in celery_app.tasks
    assert ping.apply().get(timeout=5) == "pong"


def test_worker_uses_json_only() -> None:
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_acks_late is True


def test_model_work_goes_to_the_ai_queue() -> None:
    celery_app.loader.import_default_modules()
    router = celery_app.amqp.router
    ai = (
        "civicpulse.ai.analyze_media",
        "civicpulse.ai.classify",
        "civicpulse.matching.match_report",
    )
    for name in ai:
        assert name in celery_app.tasks
        assert router.route({}, name)["queue"].name == "ai"
    for name in ("civicpulse.media.process", "civicpulse.matching.watchdog"):
        assert router.route({}, name)["queue"].name == "default"


def test_beat_runs_the_watchdog_and_the_nightly_recompute() -> None:
    tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert {"civicpulse.matching.watchdog", "civicpulse.priority.nightly"} <= tasks
