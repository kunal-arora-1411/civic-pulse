"""Which vision models this process uses (chosen by AI_PROVIDER).

Interim version with only the `fake` provider; the ONNX branch arrives
with the real models. Instances are cached per process.
"""

from __future__ import annotations

from functools import lru_cache

from app.ai.interfaces import FaceDetector, VisionModel, ZeroShotClassifier
from app.core.config import get_settings


class ProviderUnavailable(RuntimeError):
    """The configured AI provider can't be loaded in this process."""


def _require_fake() -> None:
    provider = get_settings().ai_provider
    if provider != "fake":
        raise ProviderUnavailable(f"AI_PROVIDER={provider} is not available in this build")


@lru_cache
def get_vision_model() -> VisionModel:
    _require_fake()
    from app.ai.fake import FakeVisionModel

    return FakeVisionModel()


@lru_cache
def get_classifier() -> ZeroShotClassifier:
    _require_fake()
    from app.ai.fake import FakeZeroShotClassifier

    return FakeZeroShotClassifier()


@lru_cache
def get_face_detector() -> FaceDetector:
    _require_fake()
    from app.ai.fake import FakeFaceDetector

    return FakeFaceDetector()
