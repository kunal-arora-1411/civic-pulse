"""Small Redis-backed rate limits.

These fail closed: if Redis is unreachable the caller gets a 503 rather than
an unmetered endpoint. The only limited endpoint in Phase 0 sends SMS, where
"unlimited" would mean an open bill and an open brute-force window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.context import get_client
from app.core.errors import RateLimited, ServiceUnavailable
from app.core.logging import log_fields
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def enforce_cooldown(redis: Redis, key: str, seconds: int) -> None:
    """Allow one hit per `seconds`."""
    try:
        acquired = await redis.set(key, "1", ex=seconds, nx=True)
        if acquired:
            return
        ttl = await redis.ttl(key)
    except RedisError as exc:
        logger.error("rate limit store unavailable", extra=log_fields(error=repr(exc)))
        raise ServiceUnavailable() from exc
    raise RateLimited(retry_after=ttl if ttl > 0 else seconds)


async def enforce_window(redis: Redis, key: str, limit: int, window_seconds: int) -> None:
    """Allow `limit` hits per fixed window of `window_seconds`."""
    try:
        # SET NX EX creates the counter with its TTL atomically, so a crash
        # between the two commands can't leave a counter that never expires.
        await redis.set(key, 0, ex=window_seconds, nx=True)
        count = await redis.incr(key)
        if count <= limit:
            return
        ttl = await redis.ttl(key)
    except RedisError as exc:
        logger.error("rate limit store unavailable", extra=log_fields(error=repr(exc)))
        raise ServiceUnavailable() from exc
    raise RateLimited(retry_after=ttl if ttl > 0 else window_seconds)


def per_ip_limit(
    name: str,
    limit: Callable[[Settings], int],
    window_seconds: int,
    *,
    fail_open: bool = False,
) -> Any:
    """A route dependency allowing `limit` requests per client address per window.

    Meant for unauthenticated endpoints, where the address is the only thing
    to count by. Carrier-grade NAT puts many citizens behind one address, so
    the limits are generous: they stop spraying, not ordinary use. Endpoints
    that hand out credentials fail closed when Redis is down; read-only ones
    pass `fail_open=True` so an unreachable limiter doesn't take them down.
    """

    async def dependency() -> None:
        ip = get_client().ip
        if not ip:
            return
        try:
            await enforce_window(
                get_redis(), f"ratelimit:{name}:ip:{ip}", limit(get_settings()), window_seconds
            )
        except ServiceUnavailable:
            if not fail_open:
                raise
            logger.warning("rate limit skipped", extra=log_fields(limit=name, client=ip))

    return Depends(dependency)
