from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, Response, status
from redis.asyncio import Redis

from app.core.db import DbSession
from app.core.errors import Unauthenticated, error_responses
from app.core.redis import get_redis
from app.domains.auth import mfa, service
from app.domains.auth.cookies import (
    REFRESH_COOKIE,
    clear_refresh_cookie,
    clear_refresh_cookie_headers,
    set_refresh_cookie,
)
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.auth.schemas import (
    MfaChallengeResponse,
    MfaEnableIn,
    MfaSetupOut,
    MfaVerifyIn,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    RefreshIn,
    TokenResponse,
)
from app.domains.auth.sms import SmsProvider, get_sms_provider
from app.domains.tenants.dependencies import OptionalHeaderTenant
from app.domains.users.service import to_me

router = APIRouter(prefix="/auth", tags=["auth"])


def token_response(response: Response, tokens: service.IssuedTokens) -> TokenResponse:
    set_refresh_cookie(response, tokens.refresh_token)
    response.headers["cache-control"] = "no-store"
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
        user=to_me(tokens.user),
    )


@router.post(
    "/otp/request",
    operation_id="auth_request_otp",
    response_model=OtpRequestOut,
    responses=error_responses(404, 422, 429, 503),
    summary="Send a one-time code to a phone number",
)
async def request_otp(
    body: OtpRequestIn,
    db: DbSession,
    tenant: OptionalHeaderTenant,
    redis: Annotated[Redis, Depends(get_redis)],
    sms: Annotated[SmsProvider, Depends(get_sms_provider)],
) -> OtpRequestOut:
    issued = await service.request_otp(db, redis, sms, tenant=tenant, phone=body.phone)
    return OtpRequestOut(
        challenge_id=issued.challenge_id,
        expires_in=issued.expires_in,
        resend_after=issued.resend_after,
    )


@router.post(
    "/otp/verify",
    operation_id="auth_verify_otp",
    response_model=TokenResponse | MfaChallengeResponse,
    responses=error_responses(400, 403, 404, 422, 429),
    summary="Exchange a one-time code for tokens (or an MFA challenge)",
)
async def verify_otp(
    body: OtpVerifyIn, db: DbSession, response: Response, tenant: OptionalHeaderTenant
) -> TokenResponse | MfaChallengeResponse:
    result = await service.verify_otp(
        db, challenge_id=body.challenge_id, code=body.code, header_tenant=tenant
    )
    if isinstance(result, service.MfaPending):
        return MfaChallengeResponse(mfa_token=result.mfa_token)
    return token_response(response, result)


@router.post(
    "/refresh",
    operation_id="auth_refresh",
    response_model=TokenResponse,
    responses=error_responses(401, 422),
    summary="Rotate the refresh token and get a new access token",
)
async def refresh(
    db: DbSession,
    response: Response,
    body: Annotated[RefreshIn | None, Body()] = None,
    cp_refresh: Annotated[str | None, Cookie(alias=REFRESH_COOKIE, include_in_schema=False)] = None,
) -> TokenResponse:
    token = (body.refresh_token if body else None) or cp_refresh
    if not token:
        raise Unauthenticated(
            "No refresh token was provided.", headers=clear_refresh_cookie_headers()
        )
    tokens = await service.refresh(db, token)
    return token_response(response, tokens)


@router.post(
    "/logout",
    operation_id="auth_logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(401),
    summary="End the current session",
)
async def logout(principal: CurrentPrincipal, db: DbSession) -> Response:
    await service.logout(db, principal)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)
    return response


@router.post(
    "/sessions/revoke-all",
    operation_id="auth_revoke_all_sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(401),
    summary="End every session of the current user, on every device",
)
async def revoke_all_sessions(principal: CurrentPrincipal, db: DbSession) -> Response:
    await service.revoke_all_sessions(
        db, principal.user_id, principal.tenant_id, reason="revoke_all", actor=principal
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)
    return response


@router.post(
    "/mfa/verify",
    operation_id="auth_verify_mfa",
    response_model=TokenResponse,
    responses=error_responses(400, 401, 403, 422, 429),
    summary="Complete login with a TOTP code",
)
async def verify_mfa(body: MfaVerifyIn, db: DbSession, response: Response) -> TokenResponse:
    tokens = await mfa.verify(db, body.mfa_token, body.code)
    return token_response(response, tokens)


@router.post(
    "/mfa/setup",
    operation_id="auth_setup_mfa",
    response_model=MfaSetupOut,
    responses=error_responses(401, 403, 409),
    summary="Start TOTP enrolment (staff only)",
)
async def setup_mfa(principal: CurrentPrincipal, db: DbSession, response: Response) -> MfaSetupOut:
    secret, uri = await mfa.setup(db, principal)
    response.headers["cache-control"] = "no-store"
    return MfaSetupOut(secret=secret, otpauth_uri=uri)


@router.post(
    "/mfa/enable",
    operation_id="auth_enable_mfa",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(400, 401, 403, 409, 422, 429),
    summary="Confirm TOTP enrolment with a code from the authenticator app",
)
async def enable_mfa(
    body: MfaEnableIn,
    principal: CurrentPrincipal,
    db: DbSession,
    redis: Annotated[Redis, Depends(get_redis)],
) -> Response:
    await mfa.enable(db, redis, principal, body.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
