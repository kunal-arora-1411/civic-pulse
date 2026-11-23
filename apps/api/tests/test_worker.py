from __future__ import annotations

from app.worker import celery_app, ping


def test_ping_task_is_registered_and_returns_pong() -> None:
    assert "civicpulse.ping" in celery_app.tasks
    assert ping.apply().get(timeout=5) == "pong"


def test_worker_uses_json_only() -> None:
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_acks_late is True
