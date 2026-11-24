"""Helpers from the model package that domain code needs, with stand-ins.

`perceptual_hash`, `blur_regions` and the default category prompts belong
to the ML side of app/ai (phash.py, faces.py, prompts.py). Until those
modules exist in a build, the simple versions here keep the pipeline
working; once they do, they are used automatically.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any, cast

from PIL import Image, ImageFilter

from app.ai.fake import fake_perceptual_hash
from app.ai.interfaces import Box

# Used only until app/ai/prompts.py provides tuned prompts.
_FALLBACK_NOT_CIVIC = [
    "a selfie",
    "a photo of food",
    "a screenshot of a phone screen",
    "a photo of a document",
    "an indoor scene",
]


def _optional(module: str, name: str) -> Any | None:
    try:
        return getattr(importlib.import_module(f"app.ai.{module}"), name)
    except (ImportError, AttributeError):
        return None


@cache
def _phash() -> Callable[[Image.Image], int]:
    real = _optional("phash", "perceptual_hash")
    return cast(Callable[[Image.Image], int], real) if real else fake_perceptual_hash


def perceptual_hash(image: Image.Image) -> int:
    """Unsigned 64-bit pHash."""
    return _phash()(image)


def to_signed64(value: int) -> int:
    """Store an unsigned 64-bit hash in a Postgres bigint (two's complement)."""
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= 1 << 63 else value


def _fallback_blur(image: Image.Image, boxes: Sequence[Box]) -> Image.Image:
    blurred = image.copy()
    for box in boxes:
        pad_x, pad_y = box.width // 4, box.height // 4
        area = (
            max(0, box.x - pad_x),
            max(0, box.y - pad_y),
            min(image.width, box.x + box.width + pad_x),
            min(image.height, box.y + box.height + pad_y),
        )
        if area[2] <= area[0] or area[3] <= area[1]:
            continue
        region = blurred.crop(area)
        radius = max(8, max(region.size) // 4)
        blurred.paste(region.filter(ImageFilter.GaussianBlur(radius)), area[:2])
    return blurred


def blur_regions(image: Image.Image, boxes: Sequence[Box]) -> Image.Image:
    real = _optional("faces", "blur_regions")
    if real is not None:
        return real(image, list(boxes))
    return _fallback_blur(image, boxes)


def default_prompts() -> dict[str, list[str]]:
    real = _optional("prompts", "DEFAULT_PROMPTS")
    if isinstance(real, dict):
        return {str(code): list(texts) for code, texts in real.items()}
    return {"not_civic": list(_FALLBACK_NOT_CIVIC)}


def category_prompts(code: str, name_en: str, override: list[str] | None) -> list[str]:
    if override:
        return list(override)
    built_in = default_prompts().get(code)
    return built_in or [f"a photo of {name_en.lower()}"]
