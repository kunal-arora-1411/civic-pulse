from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Query

from app.core.errors import NotFound
from app.main import create_app


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_database_and_redis(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_ready_returns_503_when_redis_is_down(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from redis.asyncio import Redis

    from app.core.redis import get_redis

    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    app.dependency_overrides[get_redis] = lambda: dead
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_redis)
        await dead.aclose()
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "redis": "error"},
    }


async def test_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_is_generated_when_missing_or_unsafe(client: httpx.AsyncClient) -> None:
    generated = await client.get("/health")
    assert len(generated.headers["x-request-id"]) == 32

    unsafe = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert unsafe.headers["x-request-id"] != "bad id\twith spaces"


async def test_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


async def test_cors_allows_web_origin_with_credentials(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/auth/otp/request",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-tenant",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_cors_rejects_unknown_origin(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


@pytest.fixture
async def error_client() -> httpx.AsyncClient:
    """An app with a few routes that fail in each of the ways we care about."""
    application = create_app()

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @application.get("/missing")
    async def missing() -> None:
        raise NotFound("Nothing here.")

    @application.get("/typed")
    async def typed(n: int = Query()) -> dict[str, int]:
        return {"n": n}

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
    )


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope", headers={"X-Request-ID": "rid-404"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "details": {},
            "request_id": "rid-404",
        }
    }


async def test_app_error_uses_error_envelope(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Nothing here."


async def test_validation_error_uses_error_envelope(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/typed", params={"n": "secret-value"})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["errors"][0]["loc"] == ["query", "n"]
    # The offending input is never echoed back.
    assert "secret-value" not in response.text


async def test_unhandled_error_uses_error_envelope(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get(
        "/boom", headers={"X-Request-ID": "rid-500", "Origin": "http://localhost:3000"}
    )
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": {},
            "request_id": "rid-500",
        }
    }
    assert "kaboom" not in response.text
    # Still readable by the browser.
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
