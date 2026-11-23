"""The error envelope and the exception handlers that produce it.

Every error the API returns, including validation failures, unknown routes and
unhandled exceptions, has the same shape:

    {"error": {"code": "...", "message": "...", "details": {}, "request_id": "..."}}
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str = Field(examples=["validation_error"])
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base for errors we raise deliberately. Subclasses fix code and status."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = dict(details or {})
        self.headers = dict(headers or {})
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    message = "The request is invalid."


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Authentication is required."

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        headers = {"WWW-Authenticate": "Bearer", **kwargs.pop("headers", {})}
        super().__init__(message, headers=headers, **kwargs)


class TokenExpired(Unauthenticated):
    code = "token_expired"
    message = "The access token has expired."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class TenantMismatch(Forbidden):
    code = "tenant_mismatch"
    message = "The X-Tenant header does not match the authenticated tenant."


class MfaRequired(Forbidden):
    code = "mfa_required"
    message = "Multi-factor authentication is required for this action."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Try again later."

    def __init__(self, retry_after: int, message: str | None = None, **kwargs: Any) -> None:
        retry_after = max(1, int(retry_after))
        super().__init__(
            message,
            details={"retry_after": retry_after, **kwargs.pop("details", {})},
            headers={"Retry-After": str(retry_after)},
            **kwargs,
        )


class IdempotencyKeyReused(AppError):
    status_code = 422
    code = "idempotency_key_reused"
    message = "This Idempotency-Key was already used with a different request."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required service is temporarily unavailable."


_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def error_payload(
    code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": dict(details or {}),
            "request_id": get_request_id(),
        }
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        error_payload(code, message, details), status_code=status_code, headers=headers
    )


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    # Deliberately drop `input` and `ctx`: they can echo back OTP codes,
    # tokens or other request content into logs and responses.
    return {
        "errors": [
            {
                "loc": list(err.get("loc", ())),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
    }


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        422, "validation_error", "The request is invalid.", _validation_details(exc)
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code, "error")
    try:
        default_message = HTTPStatus(exc.status_code).phrase
    except ValueError:
        default_message = "Error"
    message = exc.detail if isinstance(exc.detail, str) else default_message
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    # Unhandled exceptions are turned into the envelope by RequestContextMiddleware,
    # which sits inside CORS so the browser can still read the 500.


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Declare error responses on a route so OpenAPI documents the envelope."""
    return {
        status: {"model": ErrorResponse, "description": HTTPStatus(status).phrase}
        for status in statuses
    }
