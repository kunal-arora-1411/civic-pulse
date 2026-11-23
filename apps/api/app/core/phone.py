"""Phone number normalisation to E.164."""

from __future__ import annotations

from typing import Annotated

import phonenumbers
from pydantic import AfterValidator, Field

DEFAULT_REGION = "IN"


def normalize_phone(value: str) -> str:
    """Return the E.164 form of `value`. Bare 10-digit numbers are taken as Indian."""
    try:
        parsed = phonenumbers.parse(value.strip(), DEFAULT_REGION)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Enter a valid phone number.") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Enter a valid phone number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(phone: str) -> str:
    """+919876543210 -> +91******3210, for logs."""
    return phone[:3] + "*" * max(len(phone) - 7, 0) + phone[-4:]


PhoneNumber = Annotated[
    str,
    Field(min_length=7, max_length=24, examples=["+919876543210"]),
    AfterValidator(normalize_phone),
]
