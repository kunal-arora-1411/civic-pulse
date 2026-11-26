"""Error reporting (Sentry) and tracing (OpenTelemetry), both opt-in (P6-10).

Nothing is sent anywhere unless configured:
- SENTRY_DSN turns on Sentry error reporting; SENTRY_TRACES_SAMPLE_RATE
  adds performance traces.
- OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://otel-collector:4318) turns on
  OpenTelemetry traces over OTLP/HTTP, for Grafana Tempo or any collector.

Citizens' phone numbers, OTP codes and report text travel in request
bodies, so Sentry never gets bodies, cookies, headers that identify a
user, or local variables, and spans carry no SQL parameters.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_DROP_HEADERS = {"authorization", "cookie", "x-forwarded-for", "x-real-ip"}
_initialised: set[str] = set()


def _scrub(event: Any, _hint: Any) -> Any:
    """Last line of defence: drop anything that could identify a citizen."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in _DROP_HEADERS:
                    headers.pop(key)
    event.pop("user", None)
    return event


def init_sentry(component: str) -> bool:
    settings = get_settings()
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if not dsn or "sentry" in _initialised:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.env.value,
        release=settings.release or None,
        server_name=component,
        max_request_body_size="never",
        data_collection={
            "user_info": False,
            "http_bodies": [],
            "database_query_data": False,
            "queues": False,
            "stack_frame_variables": False,
        },
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub,
    )
    _initialised.add("sentry")
    logger.info("sentry enabled")
    return True


def init_tracing(component: str) -> bool:
    """Set up the OTLP exporter and instrument SQLAlchemy (and Celery in
    the worker). Call before the first database engine is created."""
    settings = get_settings()
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint or "otel" in _initialised:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": component,
            "service.version": settings.release or "dev",
            "deployment.environment": settings.env.value,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    SQLAlchemyInstrumentor().instrument(enable_commenter=False)
    if component.endswith("worker"):
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    _initialised.add("otel")
    logger.info("opentelemetry tracing enabled", extra={"endpoint": endpoint})
    return True


def instrument_app(app: FastAPI) -> None:
    """Trace HTTP requests, except the health probes."""
    if "otel" not in _initialised:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready")


def init_observability(component: str) -> None:
    init_sentry(component)
    init_tracing(component)
