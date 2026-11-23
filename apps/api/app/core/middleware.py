"""ASGI middleware: request IDs, access logging, security headers, and the
last-resort 500 handler.

Written as plain ASGI rather than BaseHTTPMiddleware so context variables set
here are visible to the endpoint and nothing buffers the response body.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import (
    ClientInfo,
    client_var,
    request_id_var,
    tenant_id_var,
    user_id_var,
)
from app.core.errors import error_payload
from app.core.logging import log_fields

logger = logging.getLogger("civicpulse.request")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id")
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        client = scope.get("client")
        tokens = [
            request_id_var.set(request_id),
            tenant_id_var.set(None),
            user_id_var.set(None),
        ]
        client_token = client_var.set(
            ClientInfo(ip=client[0] if client else None, user_agent=headers.get("user-agent"))
        )

        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                out = MutableHeaders(scope=message)
                out["x-request-id"] = request_id
                for key, value in _SECURITY_HEADERS.items():
                    out.setdefault(key, value)
                if self.hsts:
                    out.setdefault(
                        "strict-transport-security", "max-age=63072000; includeSubDomains"
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("unhandled error")
            if response_started:
                raise
            status_code = 500
            body = json.dumps(
                error_payload("internal_error", "An unexpected error occurred.")
            ).encode()
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            path = scope.get("path", "")
            if path not in ("/health", "/ready"):
                logger.info(
                    "request",
                    extra=log_fields(
                        method=scope.get("method"),
                        path=path,
                        status=status_code,
                        duration_ms=duration_ms,
                    ),
                )
            client_var.reset(client_token)
            for token in reversed(tokens):
                token.var.reset(token)
