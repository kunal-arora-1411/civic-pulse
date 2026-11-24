from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from app.ai.models_lock import (
    LOCK_FILENAME,
    LockedFile,
    LockedModel,
    ModelFilesError,
    ModelLock,
    load_lock,
    parse_lock,
    verify_model_dir,
)
from scripts.download_models import CANDIDATES, COMMITTED_LOCK, PINNED

COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _write_model(tmp_path: Path, files: dict[str, bytes]) -> ModelLock:
    locked = []
    for name, data in files.items():
        path = tmp_path / "toy" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        locked.append(LockedFile(name, hashlib.sha256(data).hexdigest(), len(data)))
    model = LockedModel(
        key="toy",
        model_id="toy@1",
        task="embedding",
        name="Toy",
        repo="example/toy",
        revision="0" * 40,
        license="MIT",
        license_url="https://example.invalid/LICENSE",
        intended_use="tests",
        files=tuple(locked),
        config={"files": {"weights": "weights.onnx"}},
    )
    lock = ModelLock(models={"toy": model})
    (tmp_path / LOCK_FILENAME).write_text(lock.to_json(), encoding="utf-8")
    return lock


def test_lock_round_trips_through_json(tmp_path: Path) -> None:
    lock = _write_model(tmp_path, {"weights.onnx": b"abc", "tokenizer.json": b"{}"})
    assert parse_lock(lock.to_json()) == lock
    assert load_lock(tmp_path / LOCK_FILENAME) == lock


def test_intact_files_verify(tmp_path: Path) -> None:
    lock = _write_model(tmp_path, {"weights.onnx": b"abc"})
    assert verify_model_dir(tmp_path) == lock


def test_tampered_file_fails_the_hash_check(tmp_path: Path) -> None:
    _write_model(tmp_path, {"weights.onnx": b"abc"})
    (tmp_path / "toy" / "weights.onnx").write_bytes(b"abd")  # same size, different bytes
    verify_model_dir(tmp_path, check_hashes=False)  # the cheap check can't see it
    with pytest.raises(ModelFilesError, match="sha256"):
        verify_model_dir(tmp_path)


def test_truncated_and_missing_files_fail_even_the_cheap_check(tmp_path: Path) -> None:
    _write_model(tmp_path, {"weights.onnx": b"abcdef", "extra.bin": b"x"})
    (tmp_path / "toy" / "weights.onnx").write_bytes(b"abc")
    (tmp_path / "toy" / "extra.bin").unlink()
    with pytest.raises(ModelFilesError) as excinfo:
        verify_model_dir(tmp_path, check_hashes=False)
    assert "size 3, expected 6" in str(excinfo.value)
    assert "extra.bin: missing" in str(excinfo.value)


def test_missing_lock_points_at_the_download_script(tmp_path: Path) -> None:
    with pytest.raises(ModelFilesError, match="download_models"):
        verify_model_dir(tmp_path)


def test_unknown_key_and_role_are_reported(tmp_path: Path) -> None:
    lock = _write_model(tmp_path, {"weights.onnx": b"abc"})
    with pytest.raises(ModelFilesError, match="not in the lock"):
        lock.get("nope")
    with pytest.raises(ModelFilesError, match="no file for role"):
        lock.get("toy").file("vision")


def test_registry_row_carries_source_and_licence(tmp_path: Path) -> None:
    row = _write_model(tmp_path, {"weights.onnx": b"abc"}).get("toy").registry_row()
    assert row["source"] == f"https://huggingface.co/example/toy@{'0' * 40}"
    assert row["license"] == "MIT"
    assert row["task"] == "embedding"


def test_committed_lock_pins_exact_revisions_and_hashes() -> None:
    lock = load_lock(COMMITTED_LOCK)
    assert set(lock.models) == {"clip", "yunet"}
    for model in lock.models.values():
        assert COMMIT.match(model.revision), model.key
        assert model.license
        for locked in model.files:
            assert SHA256.match(locked.sha256), locked.path
            assert locked.size > 0
        for path in model.config["files"].values():
            assert path in {f.path for f in model.files}


def test_committed_lock_matches_the_pins_in_the_download_script() -> None:
    """Changing a pin without --update-lock would leave the lock describing other weights."""
    lock = load_lock(COMMITTED_LOCK)
    for source in PINNED:
        locked = lock.get(source.key)
        assert (locked.repo, locked.revision, locked.model_id) == (
            source.repo,
            source.revision,
            source.model_id,
        )
        assert [f.path for f in locked.files] == list(source.files)
        assert locked.config == source.config
        assert locked.license == source.license


def test_candidates_never_reuse_the_default_model_id() -> None:
    default_ids = {source.model_id for source in PINNED}
    for candidate in CANDIDATES.values():
        assert candidate.model_id not in default_ids
        assert candidate.key == "clip"
