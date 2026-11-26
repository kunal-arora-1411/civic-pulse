"""Bulk assignment and status changes from the work queue (FR-078).

Each item runs the single-issue action in its own savepoint, with the
version the user saw, so one stale or refused item never undoes the
others and nothing is overwritten silently. Every item is audited by the
action it runs; the batch adds one summary audit event.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound
from app.domains.audit import service as audit
from app.domains.issues import service as issues
from app.domains.issues.schemas import StatusChange
from app.domains.operations import service
from app.domains.operations.schemas import AssignmentCreate
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.workflow.statuses import IssueStatus

BULK_MAX = 50


class BulkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: uuid.UUID
    version: int = Field(ge=1, description="The issue's `version` you last saw.")


class BulkAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["status", "assign"]
    items: list[BulkItem] = Field(min_length=1, max_length=BULK_MAX)
    to_status: IssueStatus | None = Field(default=None, description="For `status`.")
    team_id: uuid.UUID | None = Field(default=None, description="For `assign`.")
    assignee_id: uuid.UUID | None = Field(default=None, description="For `assign`; optional.")
    reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Internal. Required where the single action needs one.",
    )
    public_note: str | None = Field(default=None, max_length=2000, description="For `status`.")
    note: str | None = Field(default=None, max_length=2000, description="For `assign`.")

    @model_validator(mode="after")
    def _fits_action(self) -> BulkAction:
        if self.action == "status" and self.to_status is None:
            raise ValueError("`to_status` is required for a status change.")
        if self.action == "assign" and self.team_id is None:
            raise ValueError("`team_id` is required for an assignment.")
        if len({item.issue_id for item in self.items}) != len(self.items):
            raise ValueError("Each issue may appear once.")
        return self


class BulkItemResult(BaseModel):
    issue_id: uuid.UUID
    ok: bool
    error: str | None = Field(default=None, description="The error code when `ok` is false.")


class BulkResult(BaseModel):
    succeeded: int
    failed: int
    results: list[BulkItemResult]


async def run(db: AsyncSession, principal: Principal, body: BulkAction) -> BulkResult:
    if body.action == "assign" and not principal.has(Permission.ISSUE_ASSIGN):
        # Same answer as for an issue the caller can't see.
        raise NotFound()
    results: list[BulkItemResult] = []
    for item in body.items:
        try:
            async with db.begin_nested():
                if body.action == "status":
                    assert body.to_status is not None
                    await issues.change_status(
                        db,
                        principal,
                        item.issue_id,
                        StatusChange(
                            to_status=body.to_status,
                            reason=body.reason,
                            public_note=body.public_note,
                            version=item.version,
                        ),
                    )
                else:
                    assert body.team_id is not None
                    await service.assign(
                        db,
                        principal,
                        item.issue_id,
                        AssignmentCreate(
                            team_id=body.team_id,
                            assignee_id=body.assignee_id,
                            note=body.note,
                            reason=body.reason,
                            version=item.version,
                        ),
                    )
            results.append(BulkItemResult(issue_id=item.issue_id, ok=True))
        except AppError as exc:
            results.append(BulkItemResult(issue_id=item.issue_id, ok=False, error=exc.code))
        except ValidationError:
            # A blank reason and the like: the same for every item.
            results.append(
                BulkItemResult(issue_id=item.issue_id, ok=False, error="validation_error")
            )
    succeeded = sum(1 for r in results if r.ok)
    await audit.record(
        db,
        action="issue.bulk_action",
        entity_type="issue",
        actor=principal,
        after={
            "action": body.action,
            "to_status": body.to_status.value if body.to_status else None,
            "team_id": str(body.team_id) if body.team_id else None,
            "assignee_id": str(body.assignee_id) if body.assignee_id else None,
            "succeeded": [str(r.issue_id) for r in results if r.ok],
            "failed": {str(r.issue_id): r.error for r in results if not r.ok},
        },
    )
    return BulkResult(succeeded=succeeded, failed=len(results) - succeeded, results=results)
