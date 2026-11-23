"""Small Redis-backed rate limits.

These fail closed: if Redis is unreachable the caller gets a 503 rather than
an unmetered endpoint. The only limited endpoint in Phase 0 sends SMS, where
"unlimited" would mean an open bill and an open brute-force window.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimited, ServiceUnavailable
from app.core.logging import log_fields

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
