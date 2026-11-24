"""The model lock: which weights we run, where they came from, and their hashes.

``scripts/download_models.py`` fetches pinned files from the Hugging Face Hub
and records them in ``apps/api/models.lock.json``, which is committed. A copy
sits next to the weights in ``AI_MODEL_DIR``, so a running worker can tell
exactly what it loaded (model id, repo, revision, licence) and can refuse
to start on a missing or truncated file instead of failing on the first
task. The same metadata is what goes into ``model_registry`` (PRD §8.6).

Pure standard library, so the API image can read a lock without the ``ai``
extra.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOCK_FILENAME = "models.lock.json"
LOCK_SCHEMA = 1


class ModelFilesError(RuntimeError):
    """Model files are missing, incomplete or don't match the lock."""


@dataclass(frozen=True, slots=True)
class LockedFile:
    path: str
    """Path inside the repo, and inside ``<AI_MODEL_DIR>/<model key>/``."""
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class LockedModel:
    key: str
    """Directory name under ``AI_MODEL_DIR`` and the lookup key in the lock."""
    model_id: str
    """Stored with every embedding and prediction; change it when weights change."""
    task: str
    """``embedding`` / ``classification`` / ``face_detection``, as in ``model_registry``."""
    name: str
    repo: str
    revision: str
    license: str
    license_url: str
    intended_use: str
    files: tuple[LockedFile, ...]
    config: dict[str, Any] = field(default_factory=dict)
    """Loader settings (file roles, preprocessing); read by the model class."""

    @property
    def source(self) -> str:
        return f"https://huggingface.co/{self.repo}@{self.revision}"

    def file(self, role: str) -> str:
        """Repo path of the file playing ``role`` (e.g. ``"vision"``) in ``config["files"]``."""
        try:
            return self.config["files"][role]
        except KeyError as exc:
            raise ModelFilesError(f"{self.key}: lock has no file for role {role!r}") from exc

    def registry_row(self) -> dict[str, Any]:
        """The ``model_registry`` columns this lock entry can fill."""
        return {
            "model_id": self.model_id,
            "task": self.task,
            "name": self.name,
            "version": self.revision[:12],
            "source": self.source,
            "license": self.license,
            "intended_use": self.intended_use,
        }


@dataclass(frozen=True, slots=True)
class ModelLock:
    models: dict[str, LockedModel]
    schema: int = LOCK_SCHEMA

    def get(self, key: str) -> LockedModel:
        try:
            return self.models[key]
        except KeyError as exc:
            raise ModelFilesError(f"model {key!r} is not in the lock") from exc

    def to_json(self) -> str:
        payload = {
            "schema": self.schema,
            "models": {key: _model_to_dict(model) for key, model in sorted(self.models.items())},
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _model_to_dict(model: LockedModel) -> dict[str, Any]:
    data = asdict(model)
    data["files"] = [asdict(f) for f in model.files]
    return data


def parse_lock(text: str) -> ModelLock:
    raw = json.loads(text)
    if raw.get("schema") != LOCK_SCHEMA:
        raise ModelFilesError(f"unsupported model lock schema {raw.get('schema')!r}")
    models: dict[str, LockedModel] = {}
    for key, entry in raw["models"].items():
        files = tuple(LockedFile(**f) for f in entry.pop("files"))
        models[key] = LockedModel(files=files, **entry)
    return ModelLock(models=models)


def load_lock(path: Path) -> ModelLock:
    if not path.is_file():
        raise ModelFilesError(f"no model lock at {path}; run scripts/download_models.py")
    return parse_lock(path.read_text(encoding="utf-8"))


def load_model_dir_lock(model_dir: Path) -> ModelLock:
    return load_lock(model_dir / LOCK_FILENAME)


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(model_dir: Path, model: LockedModel, *, check_hashes: bool = True) -> list[str]:
    """Return a list of problems with ``model``'s files under ``model_dir`` (empty when fine).

    Without ``check_hashes`` only presence and size are checked, which is
    cheap enough for every process start; the full hash runs at download
    time and in the image healthcheck.
    """
    problems: list[str] = []
    for locked in model.files:
        path = model_dir / model.key / locked.path
        if not path.is_file():
            problems.append(f"{model.key}/{locked.path}: missing")
            continue
        size = path.stat().st_size
        if size != locked.size:
            problems.append(f"{model.key}/{locked.path}: size {size}, expected {locked.size}")
            continue
        if check_hashes and (actual := sha256_file(path)) != locked.sha256:
            problems.append(f"{model.key}/{locked.path}: sha256 {actual}, expected {locked.sha256}")
    return problems


def verify_model_dir(
    model_dir: Path, keys: Iterable[str] | None = None, *, check_hashes: bool = True
) -> ModelLock:
    """Load the lock in ``model_dir`` and check the files; raise ``ModelFilesError`` if any fail."""
    lock = load_model_dir_lock(model_dir)
    selected = list(keys) if keys is not None else list(lock.models)
    problems = [
        problem
        for key in selected
        for problem in verify_model(model_dir, lock.get(key), check_hashes=check_hashes)
    ]
    if problems:
        raise ModelFilesError("model files don't match the lock: " + "; ".join(problems))
    return lock


def model_path(model_dir: Path, model: LockedModel, role: str) -> Path:
    return model_dir / model.key / model.file(role)
