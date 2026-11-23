"""The `require(...)` dependency: server-side permission checks."""

from __future__ import annotations

from typing import Any

from fastapi import Depends

from app.core.config import get_settings
from app.core.errors import Forbidden, MfaRequired
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.rbac.permissions import Permission, is_staff_permission
from app.domains.rbac.principal import Principal


def require(*permissions: Permission) -> Any:
    """Depend on this to require every listed permission.

        principal: Annotated[Principal, require(Permission.USER_MANAGE)]

    Missing permission -> 403 forbidden. When REQUIRE_STAFF_MFA is on, a staff
    permission additionally needs a session that passed TOTP -> otherwise 403
    mfa_required. The permission check comes first, so a citizen probing an
    admin endpoint always gets plain `forbidden`.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.has(*permissions):
            raise Forbidden()
        if (
            get_settings().staff_mfa_required
            and not principal.mfa_verified
            and any(is_staff_permission(p) for p in permissions)
        ):
            raise MfaRequired()
        return principal

    dependency.__name__ = "require_" + "_".join(p.value.replace(":", "_") for p in permissions)
    return Depends(dependency)


def require_any(*permissions: Permission) -> Any:
    """Like `require`, but one of the listed permissions is enough.

    The staff-MFA gate applies only when every permission the caller could
    be relying on is a staff one: a citizen uploading evidence through
    `report:create` doesn't need TOTP just because field workers can do the
    same through `evidence:upload`.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        held = [p for p in permissions if principal.has(p)]
        if not held:
            raise Forbidden()
        if (
            get_settings().staff_mfa_required
            and not principal.mfa_verified
            and all(is_staff_permission(p) for p in held)
        ):
            raise MfaRequired()
        return principal

    dependency.__name__ = "require_any_" + "_".join(p.value.replace(":", "_") for p in permissions)
    return Depends(dependency)
