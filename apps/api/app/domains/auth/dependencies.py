"""Resolving the bearer token to a Principal."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.context import user_id_var
from app.core.db import DbSession
from app.core.errors import TenantMismatch, Unauthenticated
from app.core.security import decode_access_token
from app.domains.auth import service
from app.domains.rbac.principal import Principal
from app.domains.tenants import service as tenants_service

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Access token from /auth/otp/verify, /auth/mfa/verify or /auth/refresh.",
)


async def get_principal(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    x_tenant: Annotated[
        str | None,
        Header(
            alias="X-Tenant",
            max_length=63,
            description="Optional. If sent, it must match the token's tenant.",
        ),
    ] = None,
) -> Principal:
    if credentials is None:
        raise Unauthenticated()
    claims = decode_access_token(credentials.credentials)

    if x_tenant is not None:
        tenant = await tenants_service.get_active_by_slug(db, x_tenant)
        if tenant is None or tenant.id != claims.tenant_id:
            raise TenantMismatch()

    principal = await service.load_principal(db, claims)
    user_id_var.set(str(principal.user_id))
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
