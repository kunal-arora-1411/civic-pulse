"""Structured JSON logging.

Every record is one JSON object per line, enriched with the request ID, tenant
and user from the current context. Extra fields can be attached with
`logger.info("msg", extra={"fields": {...}})`.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import request_id_var, tenant_id_var, user_id_var

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "fields"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
        }
        for key, var in (
            ("request_id", request_id_var),
            ("tenant_id", tenant_id_var),
            ("user_id", user_id_var),
        ):
            value = var.get()
            if value is not None:
                payload[key] = value

        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        # Anything passed as a plain `extra=` key is kept too.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload.setdefault(key, value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", service: str = "civicpulse-api") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through ours instead. The
    # access log is replaced by our request middleware, which knows the
    # request ID.
    for name in ("uvicorn", "uvicorn.error", "celery"):
        logger = logging.getLogger(name)
        logger.handlers[:] = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True


def log_fields(**fields: Any) -> dict[str, dict[str, Any]]:
    """Shorthand for `extra={"fields": {...}}`."""
    return {"fields": fields}
