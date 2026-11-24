"""Where domain code gets its models: one instance of each per process.

``AI_PROVIDER=onnx`` loads the real models from ``AI_MODEL_DIR`` (checked
against the lock that sits there); ``AI_PROVIDER=fake`` uses the
deterministic fakes in ``app.ai.fake``. The ONNX classes need the ``ai``
extra and the fakes don't, so each branch imports its implementation only
when it is chosen. In a Celery prefork worker every child process loads its
own copy on first use, which is what ONNX Runtime wants: sessions don't
survive a fork.
"""

from __future__ import annotations

import importlib
from functools import cache
from pathlib import Path
from typing import Any, cast

from app.ai.interfaces import FaceDetector, VisionModel, ZeroShotClassifier
from app.ai.models_lock import LockedModel, load_model_dir_lock
from app.core.config import get_settings


def _fake(name: str) -> Any:
    # Imported by name so this module doesn't depend on the fakes at import time.
    return getattr(importlib.import_module("app.ai.fake"), name)()


def _model_dir() -> Path:
    return Path(get_settings().ai_model_dir)


@cache
def get_vision_model() -> VisionModel:
    if get_settings().ai_provider == "fake":
        return cast(VisionModel, _fake("FakeVisionModel"))
    from app.ai.clip import ClipOnnxModel

    return ClipOnnxModel.from_model_dir(_model_dir())


@cache
def get_classifier() -> ZeroShotClassifier:
    """The classifier with no confidence threshold of its own.

    Each tenant sets ``matching_config.classification_threshold`` and can
    change it at any time, while this instance lives for the whole
    process. So the classifier always returns the plain distribution and
    the API applies the tenant's threshold when it answers.
    """
    if get_settings().ai_provider == "fake":
        return cast(ZeroShotClassifier, _fake("FakeZeroShotClassifier"))
    from app.ai.zero_shot import PromptZeroShotClassifier

    return PromptZeroShotClassifier(get_vision_model(), threshold=0.0)


@cache
def get_face_detector() -> FaceDetector:
    if get_settings().ai_provider == "fake":
        return cast(FaceDetector, _fake("FakeFaceDetector"))
    from app.ai.faces import YuNetFaceDetector

    return YuNetFaceDetector.from_model_dir(_model_dir())


def deployed_models() -> list[LockedModel]:
    """The models in ``AI_MODEL_DIR`` per its lock, for ``model_registry`` rows.

    Empty with the fake provider: there is nothing on disk to describe.
    ``LockedModel.registry_row()`` gives the columns.
    """
    if get_settings().ai_provider == "fake":
        return []
    return list(load_model_dir_lock(_model_dir()).models.values())


def reset_registry() -> None:
    """Forget the cached instances (tests, or after changing settings)."""
    get_vision_model.cache_clear()
    get_classifier.cache_clear()
    get_face_detector.cache_clear()
