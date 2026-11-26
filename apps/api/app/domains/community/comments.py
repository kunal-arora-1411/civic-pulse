"""Citizen comments on issues, and the moderation queue (FR-017, FR-086).

A comment is private to its author until a moderator approves it. Other
citizens see approved comments only, with no author details. Citizens can
flag an approved comment; `FLAGS_TO_RECHECK` distinct flags take it off
the issue and back into the queue. Every moderation decision is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, RateLimited
from app.core.pagination import Page, PageParams, paginate
from app.domains.audit import service as audit
from app.domains.community.models import CommentFlag, CommentState, IssueComment
from app.domains.issues.errors import InvalidTransition, IssueMerged
from app.domains.issues.models import CivicIssue
from app.domains.issues.service import get_in_scope
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.scope import access_filter, issue_access
from app.domains.users.models import User

# A citizen may post this many comments a day, across all issues.
DAILY_LIMIT = 10
FLAGS_TO_RECHECK = 3


# --- schemas ---------------------------------------------------------------------------------


def _text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("This can't be blank.")
    return value


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1000)

    _body = field_validator("body")(_text)


class CommentOut(BaseModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    body: str
    state: CommentState
    created_at: datetime
    mine: bool = Field(description="Whether the caller wrote it.")
    flagged_by_me: bool = False
    author_name: str | None = Field(
        default=None, description="Staff only; citizens never see who wrote a comment."
    )
    flag_count: int | None = Field(default=None, description="Staff only.")
    moderation_reason: str | None = Field(
        default=None, description="Why it was rejected; for its author and staff."
    )


class CommentList(BaseModel):
    items: list[CommentOut]


class IssueRef(BaseModel):
    id: uuid.UUID
    reference: str


class ModerationItem(CommentOut):
    issue: IssueRef


class ModerationPage(Page[ModerationItem]):
    pass


class ModerationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str | None = Field(
        default=None, max_length=500, description="Required to reject; the author sees it."
    )

    @model_validator(mode="after")
    def _reason_to_reject(self) -> ModerationDecision:
        if self.decision == "reject" and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the comment is removed.")
        return self


# --- helpers ---------------------------------------------------------------------------------


def _is_staff(principal: Principal) -> bool:
    return principal.has(Permission.ISSUE_READ)


def _out(
    comment: IssueComment,
    principal: Principal,
    *,
    flagged: bool = False,
    author_name: str | None = None,
) -> CommentOut:
    staff = _is_staff(principal)
    mine = comment.author_id == principal.user_id
    return CommentOut(
        id=comment.id,
        issue_id=comment.issue_id,
        body=comment.body,
        state=CommentState(comment.state),
        created_at=comment.created_at,
        mine=mine,
        flagged_by_me=flagged,
        author_name=author_name if staff else None,
        flag_count=comment.flag_count if staff else None,
        moderation_reason=comment.moderation_reason if staff or mine else None,
    )


async def _issue_for(db: AsyncSession, principal: Principal, issue_id: uuid.UUID) -> CivicIssue:
    """Staff see issues in their scope; citizens any issue of the tenant."""
    if _is_staff(principal):
        return await get_in_scope(db, principal, issue_id)
    issue = await db.scalar(select(CivicIssue).where(CivicIssue.id == issue_id))
    if issue is None:
        raise NotFound()
    return issue


# --- citizen and issue page ------------------------------------------------------------------


async def list_for_issue(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID
) -> CommentList:
    issue = await _issue_for(db, principal, issue_id)
    stmt = (
        select(IssueComment, User.display_name)
        .join(User, User.id == IssueComment.author_id)
        .where(IssueComment.issue_id == issue.id)
        .order_by(IssueComment.created_at, IssueComment.id)
    )
    if not _is_staff(principal):
        stmt = stmt.where(
            or_(
                IssueComment.state == CommentState.APPROVED,
                IssueComment.author_id == principal.user_id,
            )
        )
    rows = (await db.execute(stmt)).all()
    flagged = set(
        await db.scalars(
            select(CommentFlag.comment_id).where(
                CommentFlag.user_id == principal.user_id,
                CommentFlag.comment_id.in_([c.id for c, _ in rows]),
            )
        )
    )
    return CommentList(
        items=[_out(c, principal, flagged=c.id in flagged, author_name=name) for c, name in rows]
    )


async def create(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: CommentCreate
) -> CommentOut:
    issue = await _issue_for(db, principal, issue_id)
    if issue.merged_into_id is not None:
        raise IssueMerged(details={"merged_into_id": str(issue.merged_into_id)})
    since = datetime.now(UTC) - timedelta(days=1)
    recent = await db.scalar(
        select(func.count()).where(
            IssueComment.author_id == principal.user_id, IssueComment.created_at >= since
        )
    )
    if recent is not None and recent >= DAILY_LIMIT:
        oldest = await db.scalar(
            select(func.min(IssueComment.created_at)).where(
                IssueComment.author_id == principal.user_id, IssueComment.created_at >= since
            )
        )
        wait = (oldest + timedelta(days=1) - datetime.now(UTC)).total_seconds() if oldest else 3600
        raise RateLimited(retry_after=int(wait))
    comment = IssueComment(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        author_id=principal.user_id,
        body=body.body,
        state=CommentState.PENDING,
        flag_count=0,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return _out(comment, principal)


async def flag(db: AsyncSession, principal: Principal, comment_id: uuid.UUID) -> CommentOut:
    """Report an approved comment. Once per citizen; flagging twice is
    harmless. Enough flags take it back to the moderation queue."""
    comment = await db.scalar(
        select(IssueComment)
        .where(IssueComment.id == comment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if comment is None or (
        comment.state != CommentState.APPROVED and comment.author_id != principal.user_id
    ):
        raise NotFound()
    if comment.author_id == principal.user_id or comment.state != CommentState.APPROVED:
        raise InvalidTransition(details={"reason": "not_flaggable"})
    inserted = await db.execute(
        insert(CommentFlag)
        .values(tenant_id=comment.tenant_id, comment_id=comment.id, user_id=principal.user_id)
        .on_conflict_do_nothing(index_elements=["comment_id", "user_id"])
        .returning(CommentFlag.id)
    )
    if inserted.first() is not None:
        comment.flag_count += 1
        if comment.flag_count >= FLAGS_TO_RECHECK:
            comment.state = CommentState.PENDING
        await db.flush()
    return _out(comment, principal, flagged=True)


# --- moderation queue ------------------------------------------------------------------------


async def queue(
    db: AsyncSession,
    principal: Principal,
    params: PageParams,
    state: CommentState = CommentState.PENDING,
) -> ModerationPage:
    """Comments to moderate in the caller's scope; most flagged first,
    then oldest first."""
    access = await issue_access(db, principal, Permission.ISSUE_UPDATE)
    stmt = (
        select(IssueComment, User.display_name, CivicIssue.reference)
        .join(User, User.id == IssueComment.author_id)
        .join(CivicIssue, CivicIssue.id == IssueComment.issue_id)
        .where(
            IssueComment.state == state,
            access_filter(CivicIssue.ward_id, CivicIssue.category_id, access),
        )
        .order_by(IssueComment.flag_count.desc(), IssueComment.created_at, IssueComment.id)
    )
    rows, total = await paginate(db, stmt, params)
    items = [
        ModerationItem(
            **_out(c, principal, author_name=name).model_dump(),
            issue=IssueRef(id=c.issue_id, reference=reference),
        )
        for c, name, reference in rows
    ]
    return ModerationPage(items=items, total=total, limit=params.limit, offset=params.offset)


async def decide(
    db: AsyncSession, principal: Principal, comment_id: uuid.UUID, body: ModerationDecision
) -> ModerationItem:
    comment = await db.scalar(
        select(IssueComment)
        .where(IssueComment.id == comment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if comment is None:
        raise NotFound()
    issue = await get_in_scope(db, principal, comment.issue_id, permission=Permission.ISSUE_UPDATE)
    before = {"state": comment.state}
    comment.state = CommentState.APPROVED if body.decision == "approve" else CommentState.REJECTED
    comment.moderation_reason = body.reason.strip() if body.reason else None
    comment.moderated_by = principal.user_id
    comment.moderated_at = datetime.now(UTC)
    if body.decision == "approve":
        # A fresh look clears the flags that brought it back, so the same
        # citizens can flag it again if it still needs it.
        await db.execute(delete(CommentFlag).where(CommentFlag.comment_id == comment.id))
        comment.flag_count = 0
    await db.flush()
    await audit.record(
        db,
        action=f"comment.{'approved' if body.decision == 'approve' else 'rejected'}",
        entity_type="issue_comment",
        entity_id=comment.id,
        actor=principal,
        before=before,
        after={
            "state": comment.state,
            "issue_id": str(issue.id),
            "reason": comment.moderation_reason,
        },
    )
    name = await db.scalar(select(User.display_name).where(User.id == comment.author_id))
    return ModerationItem(
        **_out(comment, principal, author_name=name).model_dump(),
        issue=IssueRef(id=issue.id, reference=issue.reference),
    )
