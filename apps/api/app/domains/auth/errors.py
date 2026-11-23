"""Auth-specific errors.

Verify steps (OTP and MFA) distinguish three outcomes the client handles
differently:

* 400 invalid_code: wrong code; `details.attempts_remaining` when known.
* 400 code_expired: the challenge or mfa_token expired or was already used;
  start again.
* 429 too_many_attempts: the attempt limit for this challenge is used up;
  start again (no Retry-After: a new code can be requested right away,
  subject to the usual rate limit).
"""

from __future__ import annotations

from app.core.errors import AppError, Forbidden


class InvalidCode(AppError):
    status_code = 400
    code = "invalid_code"
    message = "That code is not correct."


class CodeExpired(AppError):
    status_code = 400
    code = "code_expired"
    message = "This code has expired or was already used. Request a new one."


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"
    message = "Too many incorrect attempts. Request a new code."


class AccountDisabled(Forbidden):
    code = "account_disabled"
    message = "This account has been deactivated."


class PlatformAccount(Forbidden):
    code = "platform_account"
    message = (
        "This number belongs to a platform administrator. Sign in without a tenant to continue."
    )
