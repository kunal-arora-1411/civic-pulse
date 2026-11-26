"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import health
from app.api import api_router
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import error_responses, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.observability import init_observability, instrument_app
from app.core.redis import close_redis

API_DESCRIPTION = """
CivicPulse API. All errors use the envelope
`{"error": {"code", "message", "details", "request_id"}}`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.service_name)
    init_observability(settings.service_name)

    app = FastAPI(
        title="CivicPulse API",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    register_exception_handlers(app)
    instrument_app(app)

    # Middleware added later wraps earlier ones, so CORS is outermost and
    # also decorates the 500 responses produced by RequestContextMiddleware.
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
            "X-Tenant",
        ],
        expose_headers=[
            "X-Request-ID",
            "Idempotent-Replayed",
            "Retry-After",
            # The analytics CSV export reports its size and whether the cap
            # cut it short; a browser cannot read either without this.
            "X-Export-Rows",
            "X-Export-Truncated",
        ],
        max_age=600,
    )

    app.include_router(health.router)
    # Any /api/v1 route can fail validation or hit an unexpected error;
    # declaring both here documents the envelope for them in OpenAPI.
    app.include_router(api_router, prefix="/api/v1", responses=error_responses(422, 500))
    return app


app = create_app()
