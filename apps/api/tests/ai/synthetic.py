"""Deterministic, photo-like test images (no files, no network)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def scene(seed: int, size: tuple[int, int] = (640, 480)) -> Image.Image:
    """A smooth, textured RGB image whose layout depends on ``seed``.

    Gradients, a few large shapes and mild noise: enough low-frequency
    structure for perceptual hashing and enough detail that recompression
    actually changes pixels.
    """
    rng = np.random.default_rng(seed)
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.zeros((height, width, 3), dtype=np.float32)
    for channel in range(3):
        angle = rng.uniform(0, 2 * np.pi)
        freq = rng.uniform(0.5, 3.0)
        phase = rng.uniform(0, 2 * np.pi)
        proj = (xs * np.cos(angle) + ys * np.sin(angle)) / max(width, height)
        base[..., channel] = 128 + 90 * np.sin(2 * np.pi * freq * proj + phase)
    image = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for _ in range(6):
        x0, y0 = int(rng.integers(0, width - 40)), int(rng.integers(0, height - 40))
        x1 = x0 + int(rng.integers(40, width // 2))
        y1 = y0 + int(rng.integers(40, height // 2))
        colour = tuple(int(c) for c in rng.integers(0, 256, size=3))
        if rng.random() < 0.5:
            draw.ellipse((x0, y0, x1, y1), fill=colour)
        else:
            draw.rectangle((x0, y0, x1, y1), fill=colour)
    image = image.filter(ImageFilter.GaussianBlur(2))
    noise = rng.normal(0, 6, size=(height, width, 3))
    pixels = np.asarray(image, dtype=np.float32) + noise
    return Image.fromarray(pixels.clip(0, 255).astype(np.uint8))


def recompress(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")
