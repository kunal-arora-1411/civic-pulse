"""Community support endpoints: "I face this too" and follow."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.community import comments, service
from app.domains.community.models import CommentState
from app.domains.community.schemas import SupportState
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(tags=["community"])

Citizen = Annotated[Principal, require(Permission.REPORT_CREATE)]


@router.get(
    "/issues/{issue_id}/support",
    operation_id="issues_support_get",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def get_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """The support count and whether the caller supports the issue."""
    return await service.get_state(db, principal, issue_id)


@router.post(
    "/issues/{issue_id}/support",
    operation_id="issues_support_add",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def add_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """Say "I face this too": one per citizen per issue (repeating is harmless),
    and it follows the issue. Rejected or closed issues: `422
    invalid_transition`; a merged one: `422 issue_merged`. Support from
    citizens who did not report the issue adds a small, capped bonus to its
    priority (factor `community`)."""
    return await service.support(db, principal, issue_id)


@router.delete(
    "/issues/{issue_id}/support",
    operation_id="issues_support_remove",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def remove_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """Withdraw support and stop following. Idempotent."""
    return await service.withdraw(db, principal, issue_id)


# --- comments and moderation (FR-017, FR-086) ---------------------------------------------------

Commenter = Annotated[Principal, require(Permission.ISSUE_COMMENT)]
Moderator = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_UPDATE)]


@router.get(
    "/issues/{issue_id}/comments",
    operation_id="issues_comments_list",
    response_model=comments.CommentList,
    responses=error_responses(401, 404, 422),
)
async def list_comments(
    principal: CurrentPrincipal, db: DbSession, issue_id: uuid.UUID
) -> comments.CommentList:
    """Comments on the issue, oldest first. Citizens see approved comments
    and their own (with the moderator's reason if it was removed), never
    who wrote the others. Staff in scope see every comment and its flags."""
    return await comments.list_for_issue(db, principal, issue_id)


@router.post(
    "/issues/{issue_id}/comments",
    operation_id="issues_comments_create",
    response_model=comments.CommentOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 422, 429),
)
async def create_comment(
    principal: Commenter, db: DbSession, issue_id: uuid.UUID, body: comments.CommentCreate
) -> comments.CommentOut:
    """Add a comment (1 to 1000 characters). It is `pending` and visible to its
    author only until a moderator approves it. At most 10 a day per citizen
    (`429 rate_limited`); a merged issue is `422 issue_merged`."""
    return await comments.create(db, principal, issue_id, body)


@router.post(
    "/comments/{comment_id}/flag",
    operation_id="comments_flag",
    response_model=comments.CommentOut,
    responses=error_responses(401, 403, 404, 422),
)
async def flag_comment(
    principal: Commenter, db: DbSession, comment_id: uuid.UUID
) -> comments.CommentOut:
    """Report an approved comment as abusive or misleading. Once per
    citizen; three flags take it back to the moderation queue. Your own
    comment: `422 invalid_transition`."""
    return await comments.flag(db, principal, comment_id)


@router.get(
    "/moderation/comments",
    operation_id="moderation_comments_list",
    response_model=comments.ModerationPage,
    responses=error_responses(401, 403, 422),
)
async def moderation_queue(
    principal: Moderator,
    db: DbSession,
    page: PageParamsDep,
    state: CommentState = CommentState.PENDING,
) -> comments.ModerationPage:
    """The moderation queue for issues in the caller's scope: most flagged,
    then oldest, first."""
    return await comments.queue(db, principal, page, state)


@router.post(
    "/moderation/comments/{comment_id}",
    operation_id="moderation_comments_decide",
    response_model=comments.ModerationItem,
    responses=error_responses(401, 403, 404, 422),
)
async def moderate_comment(
    principal: Moderator,
    db: DbSession,
    comment_id: uuid.UUID,
    body: comments.ModerationDecision,
) -> comments.ModerationItem:
    """Approve a comment (it becomes public and its flags are cleared) or
    reject it with a reason its author sees. Audited."""
    return await comments.decide(db, principal, comment_id, body)
