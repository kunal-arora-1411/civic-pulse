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
    message = "This status change needs a reason."
