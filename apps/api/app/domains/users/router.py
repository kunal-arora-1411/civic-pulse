from __future__ import annotations

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.users import service
from app.domains.users.schemas import UserMe, UserMeUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    operation_id="users_get_me",
    response_model=UserMe,
    responses=error_responses(401, 403),
)
async def get_me(principal: CurrentPrincipal, db: DbSession) -> UserMe:
    user = await service.get_self(db, principal.user_id, principal.tenant_id)
    return service.to_me(user)


@router.patch(
    "/me",
    operation_id="users_update_me",
    response_model=UserMe,
    responses=error_responses(401, 403, 409, 422),
)
async def update_me(principal: CurrentPrincipal, db: DbSession, body: UserMeUpdate) -> UserMe:
    user = await service.update_self(db, principal.user_id, principal.tenant_id, body)
    return service.to_me(user)
