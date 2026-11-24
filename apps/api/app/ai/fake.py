"""Deterministic stand-ins for the vision models (tests and development).

Nothing here is learned. The fakes exist so that the domain code (duplicate
matching, classification records, face blurring) can be exercised for real,
end to end, without model weights, and so that a test can decide what the
"model" will see:

* **Same scene / different scene.** `FakeVisionModel` builds an embedding
  from the image's own pixels (a 12 x 12 RGB thumbnail, centred), so two
  copies of one picture, even recompressed or resized, score a cosine near
  1, and unrelated pictures score near 0. `make_scene(seed, variant=...)`
  draws such pictures: the same seed is the same scene, a different
  `variant` is a slightly different shot of it.
* **A chosen classification.** An image may carry a `CP_TEST_LABEL` text
  value (a PNG text chunk, or `CP_TEST_LABEL=...` in a JPEG comment) such
  as `pothole` or `pothole:0.62`. The label is written into a reserved part
  of the embedding, where `FakeZeroShotClassifier` reads it back: the
  labelled code gets that confidence (0.9 by default) and the rest is
  shared equally. Without a label the result is the reserved `unknown`
  code followed by every code scoring the same, which asks the citizen
  to choose.
* **Faces.** `CP_TEST_FACES=x,y,w,h;x,y,w,h` lists the boxes
  `FakeFaceDetector` will "find".

Embedding layout (512 floats, L2-normalised as a whole): dimensions 0-62
hold the label direction, 63 its confidence, 64-495 the pixels, and the
rest are zero. The label part is small next to the pixel part, so a shared
label adds only about 0.2 to the cosine of two different scenes.

Only numpy and Pillow are used, so this module loads anywhere the API does.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, PngImagePlugin

from app.ai.interfaces import Box, CategoryScore

FAKE_MODEL_ID = "fake-vision@1"
EMBEDDING_DIM = 512
LABEL_KEY = "CP_TEST_LABEL"
FACES_KEY = "CP_TEST_FACES"
DEFAULT_LABEL_CONFIDENCE = 0.9

_LABEL_DIMS = 63
_CONFIDENCE_DIM = 63
_PIXEL_SIDE = 12
_PIXEL_START = 64
_PIXEL_END = _PIXEL_START + _PIXEL_SIDE * _PIXEL_SIDE * 3  # 496
_LABEL_WEIGHT = 0.35
# A label whose direction is this far from every prompt code is "no label".
_MIN_LABEL_MATCH = 0.5


# --- test hooks carried inside the image -------------------------------------------------


def read_test_hooks(image: Image.Image) -> dict[str, str]:
    """`CP_TEST_*` values from PNG text chunks or a JPEG comment."""
    hooks: dict[str, str] = {}
    for key, value in image.info.items():
        if isinstance(key, str) and key.startswith("CP_TEST_") and isinstance(value, str):
            hooks[key] = value
    comment = image.info.get("comment")
    if isinstance(comment, bytes):
        comment = comment.decode("utf-8", errors="ignore")
    if isinstance(comment, str):
        for part in comment.replace("\n", "|").split("|"):
            key, _, value = part.strip().partition("=")
            if key.startswith("CP_TEST_") and value:
                hooks[key] = value.strip()
    return hooks


def parse_label(value: str) -> tuple[str, float]:
    """`"pothole"` or `"pothole:0.62"` -> (code, confidence)."""
    code, _, confidence = value.strip().partition(":")
    level = float(confidence) if confidence else DEFAULT_LABEL_CONFIDENCE
    return code.strip(), min(1.0, max(0.0, level))


def parse_faces(value: str) -> list[Box]:
    boxes: list[Box] = []
    for part in value.split(";"):
        numbers = [int(n) for n in part.split(",") if n.strip()]
        if len(numbers) == 4:
            x, y, width, height = numbers
            boxes.append(Box(x=x, y=y, width=width, height=height, score=0.99))
    return boxes


# --- the fake models ---------------------------------------------------------------------


def _unit(vector: NDArray[np.float64]) -> NDArray[np.float64]:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


def label_direction(code: str) -> NDArray[np.float64]:
    """A fixed unit vector per code, in the label part of the embedding."""
    seed = int.from_bytes(hashlib.sha256(code.encode()).digest()[:8], "big")
    return _unit(np.random.default_rng(seed).standard_normal(_LABEL_DIMS))


def _pixels(image: Image.Image) -> NDArray[np.float64]:
    small = ImageOps.exif_transpose(image).convert("RGB")
    small = small.resize((_PIXEL_SIDE, _PIXEL_SIDE), Image.Resampling.BOX)
    values = np.asarray(small, dtype=np.float64) / 255.0 - 0.5
    return _unit(values.reshape(-1))


class FakeVisionModel:
    """A `VisionModel` whose embeddings are the image's own thumbnail."""

    @property
    def model_id(self) -> str:
        return FAKE_MODEL_ID

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def _embed_one(self, image: Image.Image) -> NDArray[np.float64]:
        vector = np.zeros(EMBEDDING_DIM)
        vector[_PIXEL_START:_PIXEL_END] = _pixels(image)
        label = read_test_hooks(image).get(LABEL_KEY)
        if label:
            code, confidence = parse_label(label)
            vector[:_LABEL_DIMS] = label_direction(code) * _LABEL_WEIGHT
            vector[_CONFIDENCE_DIM] = confidence * _LABEL_WEIGHT
        return _unit(vector)

    def embed_images(self, images: list[Image.Image]) -> NDArray[np.float32]:
        if not images:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        return np.stack([self._embed_one(image) for image in images]).astype(np.float32)

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        rows = []
        for text in texts:
            vector = np.zeros(EMBEDDING_DIM)
            vector[:_LABEL_DIMS] = label_direction(text)
            rows.append(vector)
        return np.array(rows, dtype=np.float32).reshape(len(texts), EMBEDDING_DIM)


class FakeZeroShotClassifier:
    """Reads back the label `FakeVisionModel` wrote into the embedding."""

    def classify(
        self, image_embeddings: NDArray[np.float32], prompts: dict[str, list[str]]
    ) -> list[CategoryScore]:
        codes = sorted(prompts)
        if not codes:
            return []
        mean = np.asarray(image_embeddings, dtype=np.float64).reshape(-1, EMBEDDING_DIM)
        mean = mean.mean(axis=0)
        direction = mean[:_LABEL_DIMS]
        strength = float(np.linalg.norm(direction))
        winner: str | None = None
        confidence = 0.0
        if strength > 1e-9:
            unit = direction / strength
            matches = {code: float(label_direction(code) @ unit) for code in codes}
            best = max(codes, key=lambda code: (matches[code], code))
            if matches[best] >= _MIN_LABEL_MATCH:
                winner = best
                confidence = min(1.0, max(0.0, float(mean[_CONFIDENCE_DIM]) / strength))
        if winner is None:
            # Like the real classifier below its threshold: the reserved
            # `unknown` code first, with confidence 1 - top score.
            share = 1.0 / len(codes)
            uniform = [CategoryScore(code=code, confidence=share) for code in codes]
            return [CategoryScore(code="unknown", confidence=1.0 - share), *uniform]
        rest = (1.0 - confidence) / (len(codes) - 1) if len(codes) > 1 else 0.0
        scores = [
            CategoryScore(code=code, confidence=confidence if code == winner else rest)
            for code in codes
        ]
        return sorted(scores, key=lambda score: (-score.confidence, score.code))


class FakeFaceDetector:
    """ "Finds" exactly the boxes listed in the image's `CP_TEST_FACES` hook."""

    def detect(self, image: Image.Image) -> list[Box]:
        value = read_test_hooks(image).get(FACES_KEY)
        return parse_faces(value) if value else []


def fake_perceptual_hash(image: Image.Image) -> int:
    """A 64-bit difference hash: a stand-in until app/ai/phash.py lands.

    Each bit says whether a pixel of a 9 x 8 greyscale thumbnail is brighter
    than its right-hand neighbour, which survives recompression and resizing.
    """
    grey = ImageOps.exif_transpose(image).convert("L").resize((9, 8), Image.Resampling.BOX)
    pixels = np.asarray(grey, dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


# --- pictures for tests and the development seed ------------------------------------------


def make_scene(
    seed: int,
    *,
    variant: int = 0,
    size: tuple[int, int] = (640, 480),
    label: str | None = None,
    faces: Sequence[tuple[int, int, int, int]] = (),
    image_format: str = "JPEG",
) -> bytes:
    """A synthetic photo: a grid of coloured blocks chosen by `seed`.

    The same seed is the same scene. `variant` > 0 is another shot of it,
    with a little noise and a small change in brightness, which the fake
    model still sees as near-identical (cosine about 0.99, pHash within a
    few bits). `label` and `faces` become the test hooks described above.
    """
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 256, size=(6, 8, 3)).astype(np.float64)
    width, height = size
    image = np.kron(blocks, np.ones((height // 6 + 1, width // 8 + 1, 1)))[:height, :width]
    if variant:
        jitter = np.random.default_rng(seed * 1000 + variant)
        image = image * (1.0 + jitter.uniform(-0.03, 0.03))
        image = image + jitter.normal(0.0, 3.0, size=image.shape)
    picture = Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), "RGB")

    hooks: dict[str, str] = {}
    if label:
        hooks[LABEL_KEY] = label
    if faces:
        hooks[FACES_KEY] = ";".join(",".join(str(n) for n in box) for box in faces)

    buffer = io.BytesIO()
    if image_format.upper() == "PNG":
        info = PngImagePlugin.PngInfo()
        for key, value in hooks.items():
            info.add_text(key, value)
        picture.save(buffer, "PNG", pnginfo=info)
    else:
        extra = {"comment": "|".join(f"{k}={v}" for k, v in hooks.items())} if hooks else {}
        picture.save(buffer, "JPEG", quality=88, **extra)
    return buffer.getvalue()
