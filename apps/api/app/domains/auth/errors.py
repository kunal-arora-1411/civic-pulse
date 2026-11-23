from __future__ import annotations

from app.core.errors import AppError, Forbidden


class InvalidCode(AppError):
    status_code = 400
    code = "invalid_code"
    message = "That code is not correct."


class ChallengeExpired(AppError):
    status_code = 400
    code = "challenge_expired"
    message = "This code has expired or was already used. Request a new one."


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"
    message = "Too many incorrect attempts. Request a new code."


class AccountDisabled(Forbidden):
    code = "account_disabled"
    message = "This account has been deactivated."
