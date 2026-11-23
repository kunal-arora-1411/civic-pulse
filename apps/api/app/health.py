"""Liveness and readiness probes (outside /api/v1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.db import get_engine
from app.core.logging import log_fields
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]
_TIMEOUT_SECONDS = 2.0


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessOut(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckStatus]


@router.get("/health", operation_id="health_live", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut()


async def _check_database() -> CheckStatus:
    async def probe() -> None:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(probe(), _TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("readiness: database check failed", extra=log_fields(error=repr(exc)))
        return "error"
    return "ok"


async def _check_redis(redis: Redis) -> CheckStatus:
    try:
        await asyncio.wait_for(redis.ping(), _TIMEOUT_SECONDS)  # pyright: ignore[reportGeneralTypeIssues]
    except Exception as exc:
        logger.warning("readiness: redis check failed", extra=log_fields(error=repr(exc)))
        return "error"
    return "ok"


@router.get(
    "/ready",
    operation_id="health_ready",
    response_model=ReadinessOut,
    responses={503: {"model": ReadinessOut, "description": "A dependency is unavailable"}},
)
async def ready(redis: Annotated[Redis, Depends(get_redis)]) -> JSONResponse:
    database, redis_status = await asyncio.gather(_check_database(), _check_redis(redis))
    checks: dict[str, CheckStatus] = {"database": database, "redis": redis_status}
    healthy = all(value == "ok" for value in checks.values())
    body = ReadinessOut(status="ok" if healthy else "unavailable", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if healthy else 503)
