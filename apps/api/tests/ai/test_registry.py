from __future__ import annotations

import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.ai import registry
from app.ai.models_lock import ModelFilesError
from tests.ai.conftest import API_ROOT


class _Settings:
    def __init__(self, provider: str, model_dir: Path | str = "/nonexistent") -> None:
        self.ai_provider = provider
        self.ai_model_dir = str(model_dir)
        self.ai_face_blur = True


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    registry.reset_registry()
    yield
    registry.reset_registry()


def _use(monkeypatch: pytest.MonkeyPatch, settings: _Settings) -> None:
    monkeypatch.setattr(registry, "get_settings", lambda: settings)


@pytest.fixture
def fake_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Stand-in for app.ai.fake (the backend's), so the fake branch is testable on its own."""
    module = types.ModuleType("app.ai.fake")

    class FakeVisionModel:
        model_id = "fake@1"
        dim = 4

    class FakeZeroShotClassifier:
        pass

    class FakeFaceDetector:
        pass

    module.FakeVisionModel = FakeVisionModel  # type: ignore[attr-defined]
    module.FakeZeroShotClassifier = FakeZeroShotClassifier  # type: ignore[attr-defined]
    module.FakeFaceDetector = FakeFaceDetector  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.ai.fake", module)
    return module


def test_fake_provider_uses_the_fakes_and_caches_them(
    monkeypatch: pytest.MonkeyPatch, fake_module: types.ModuleType
) -> None:
    _use(monkeypatch, _Settings("fake"))
    model = registry.get_vision_model()
    assert type(model).__name__ == "FakeVisionModel"
    assert registry.get_vision_model() is model
    assert type(registry.get_classifier()).__name__ == "FakeZeroShotClassifier"
    assert type(registry.get_face_detector()).__name__ == "FakeFaceDetector"
    assert registry.deployed_models() == []


def test_reset_registry_drops_cached_instances(
    monkeypatch: pytest.MonkeyPatch, fake_module: types.ModuleType
) -> None:
    _use(monkeypatch, _Settings("fake"))
    first = registry.get_vision_model()
    registry.reset_registry()
    assert registry.get_vision_model() is not first


def test_onnx_provider_without_models_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch, _Settings("onnx", tmp_path))
    with pytest.raises(ModelFilesError, match="download_models"):
        registry.get_vision_model()
    with pytest.raises(ModelFilesError):
        registry.get_face_detector()


def test_importing_the_registry_pulls_in_no_model_runtime() -> None:
    """The API container imports app.ai without the ai extra; that must keep working."""
    code = (
        "import sys; import app.ai.registry, app.ai.clip, app.ai.faces, app.ai.zero_shot; "
        "heavy = {'onnxruntime', 'cv2', 'tokenizers', 'huggingface_hub'} & set(sys.modules); "
        "print(sorted(heavy)); sys.exit(1 if heavy else 0)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], cwd=API_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.models
def test_onnx_provider_loads_the_real_models_once(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path
) -> None:
    from app.ai.clip import ClipOnnxModel
    from app.ai.faces import YuNetFaceDetector
    from app.ai.zero_shot import PromptZeroShotClassifier

    _use(monkeypatch, _Settings("onnx", model_dir))
    model = registry.get_vision_model()
    assert isinstance(model, ClipOnnxModel)
    assert registry.get_vision_model() is model
    classifier = registry.get_classifier()
    assert isinstance(classifier, PromptZeroShotClassifier)
    assert classifier.model_id == model.model_id
    assert isinstance(registry.get_face_detector(), YuNetFaceDetector)
    rows = [m.registry_row() for m in registry.deployed_models()]
    assert {r["task"] for r in rows} == {"embedding", "face_detection"}
    assert all(r["license"] == "MIT" for r in rows)
