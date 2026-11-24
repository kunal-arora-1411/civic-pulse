"""Fixtures for the model tests.

Everything here is pure computation, so these tests can also run without
the database and storage the rest of the suite needs:

    uv run pytest tests/ai --confcutdir=tests/ai

Tests marked ``models`` need the real weights (``scripts/download_models.py``)
in ``AI_MODEL_DIR`` (default ``apps/api/.models``) and the ``ai`` extra; they
skip cleanly when either is missing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

from app.ai.models_lock import LOCK_FILENAME, ModelFilesError, verify_model_dir

API_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CACHE = API_ROOT / ".eval-cache" / "fixtures"
USER_AGENT = "CivicPulse-tests/0.1 (open-source civic issue reporting; test fixtures)"


def _model_dir() -> Path:
    return Path(os.environ.get("AI_MODEL_DIR") or API_ROOT / ".models")


def has_ai_extra() -> bool:
    return all(importlib.util.find_spec(m) for m in ("onnxruntime", "tokenizers", "cv2"))


@pytest.fixture(scope="session")
def model_dir() -> Path:
    """The verified model directory, or a skip when the weights aren't installed."""
    if not has_ai_extra():
        pytest.skip("the ai extra is not installed (uv sync --extra ai)")
    path = _model_dir()
    if not (path / LOCK_FILENAME).is_file():
        pytest.skip(f"no models in {path} (run scripts/download_models.py)")
    try:
        verify_model_dir(path, check_hashes=False)
    except ModelFilesError as exc:
        pytest.skip(str(exc))
    return path


def fetch_image(url: str) -> Image.Image:
    """Download a test image once (cached under .eval-cache/fixtures), or skip when offline."""
    cached = FIXTURE_CACHE / hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
    if not cached.is_file():
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                data = response.read()
        except OSError as exc:
            pytest.skip(f"could not fetch {url}: {exc}")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return Image.open(io.BytesIO(cached.read_bytes())).convert("RGB")
