"""Localised text fields (`*_i18n`): objects keyed by locale.

The API returns the whole object and the client picks the user's locale,
falling back to `en`, so every required text must at least have `en`.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import AfterValidator, Field

_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
MAX_LOCALES = 10


def _clean(value: dict[str, Any], *, max_length: int, require_en: bool) -> dict[str, str]:
    if len(value) > MAX_LOCALES:
        raise ValueError(f"At most {MAX_LOCALES} locales.")
    cleaned: dict[str, str] = {}
    for locale, text in value.items():
        if not _LOCALE.match(locale):
            raise ValueError(f"'{locale}' is not a locale code like 'en' or 'hi'.")
        if not isinstance(text, str):
            raise ValueError("Translations must be strings.")
        text = text.strip()
        if len(text) > max_length:
            raise ValueError(f"Translations are limited to {max_length} characters.")
        if text:
            cleaned[locale] = text
    if require_en and "en" not in cleaned:
        raise ValueError("An English ('en') text is required.")
    return cleaned


def _label(value: dict[str, Any]) -> dict[str, str]:
    return _clean(value, max_length=200, require_en=True)


def _description(value: dict[str, Any]) -> dict[str, str]:
    return _clean(value, max_length=2000, require_en=False)


I18nLabel = Annotated[
    dict[str, str],
    AfterValidator(_label),
    Field(examples=[{"en": "Pothole / road damage", "hi": "गड्ढा / सड़क क्षति"}]),
]
"""Required short text: `en` must be present, 200 characters per locale."""

I18nDescription = Annotated[dict[str, str], AfterValidator(_description)]
"""Optional longer text: may be empty, 2000 characters per locale."""
