"""The `cp_refresh` cookie."""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import get_settings

REFRESH_COOKIE = "cp_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def clear_refresh_cookie_headers() -> dict[str, str]:
    """Set-Cookie header that clears the cookie, for error responses."""
    response = Response()
    clear_refresh_cookie(response)
    return {"set-cookie": response.headers["set-cookie"]}
