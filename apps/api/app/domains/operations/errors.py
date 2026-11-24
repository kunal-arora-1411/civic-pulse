from __future__ import annotations

from app.core.errors import AppError


class InvalidWorkOrderAction(AppError):
    status_code = 409
    code = "invalid_work_order_action"
    message = "That action doesn't fit the work order's current state."


class WorkOrderConflict(AppError):
    status_code = 409
    code = "version_conflict"
    message = "The work order changed since you loaded it. Review the current state."


class NotAssignable(AppError):
    status_code = 422
    code = "not_assignable"
    message = "This issue can't be assigned in its current status."


class TeamNotEligible(AppError):
    status_code = 422
    code = "team_not_eligible"
    message = "That team can't take this issue."


class AssigneeNotInTeam(AppError):
    status_code = 422
    code = "assignee_not_in_team"
    message = "The assignee isn't a member of that team."


class ClosureEvidenceRequired(AppError):
    status_code = 422
    code = "evidence_required"
    message = "A closure request needs an after photo or an allowed closure reason."


class NotEligible(AppError):
    status_code = 403
    code = "not_eligible"
    message = "Only citizens who reported this issue can do that."


class AlreadyVerified(AppError):
    status_code = 409
    code = "already_verified"
    message = "You've already answered for this issue."
