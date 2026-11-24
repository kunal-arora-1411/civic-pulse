from __future__ import annotations

from app.core.errors import AppError


class VersionConflict(AppError):
    status_code = 409
    code = "version_conflict"
    message = "The issue changed since you loaded it. Reload and try again."


class InvalidTransition(AppError):
    status_code = 422
    code = "invalid_transition"
    message = "You can't move this issue to that status."


class ReasonRequired(AppError):
    status_code = 422
    code = "reason_required"
    message = "This change needs a reason."


class InvalidMerge(AppError):
    status_code = 422
    code = "invalid_merge"
    message = "These issues can't be merged that way."


class CannotEmptyIssue(AppError):
    status_code = 422
    code = "cannot_empty_issue"
    message = "A split must leave at least one report on the issue."


class IssueMerged(AppError):
    status_code = 422
    code = "issue_merged"
    message = "This issue was merged into another; act on that one instead."
