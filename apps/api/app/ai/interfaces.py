"""Contracts between the domain layer and the vision models (Phase 2).

The domain layer (classification records, duplicate matching, media
processing) codes against these protocols only. Real implementations live
alongside this module and need the optional ``ai`` extra
(``uv sync --extra ai``); the API container never imports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray
from PIL import Image

Embedding = NDArray[np.float32]
"""A 1-D, L2-normalised float32 vector of length ``VisionModel.dim``."""


@runtime_checkable
class VisionModel(Protocol):
    """A joint image/text embedding model (CLIP-family)."""

    @property
    def model_id(self) -> str:
        """Stable identifier including version, e.g. ``"clip-vit-b32@onnx-1"``.

        Stored with every embedding and prediction so that changing the model
        can trigger re-indexing (PRD §8.2).
        """
        ...

    @property
    def dim(self) -> int:
        """Embedding dimensionality."""
        ...

    def embed_images(self, images: list[Image.Image]) -> NDArray[np.float32]:
        """Return an ``(n, dim)`` array of L2-normalised image embeddings."""
        ...

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Return an ``(n, dim)`` array of L2-normalised text embeddings."""
        ...


@dataclass(frozen=True, slots=True)
class CategoryScore:
    code: str
    """A category code, or one of the reserved codes ``not_civic`` / ``unknown``."""
    confidence: float
    """Probability in [0, 1]; scores for one classification sum to ~1."""


@runtime_checkable
class ZeroShotClassifier(Protocol):
    """Scores image embeddings against per-category text prompts."""

    def classify(
        self,
        image_embeddings: NDArray[np.float32],
        prompts: dict[str, list[str]],
    ) -> list[CategoryScore]:
        """Classify one report from one or more of its image embeddings.

        ``prompts`` maps category code -> English prompt texts and always
        includes the reserved ``not_civic`` key. Returns scores sorted by
        descending confidence. Implementations must be deterministic for the
        same inputs.
        """
        ...


@dataclass(frozen=True, slots=True)
class Box:
    """Pixel-space bounding box, ``(x, y)`` = top-left corner."""

    x: int
    y: int
    width: int
    height: int
    score: float


@runtime_checkable
class FaceDetector(Protocol):
    def detect(self, image: Image.Image) -> list[Box]:
        """Return face boxes; empty when none are found."""
        ...


_UINT64_MASK = (1 << 64) - 1


def perceptual_hash_distance(a: int, b: int) -> int:
    """Hamming distance between two 64-bit perceptual hashes.

    Either hash may be unsigned or in the signed form a Postgres ``bigint``
    holds: only the low 64 bits are compared. (``bit_count`` of a negative
    Python int would count the bits of its absolute value instead.)
    """
    return ((a ^ b) & _UINT64_MASK).bit_count()
