"""Fetch the pinned model files into AI_MODEL_DIR and check them against the lock.

    uv run --extra ai python scripts/download_models.py --model-dir .models
    uv run --extra ai python scripts/download_models.py --verify-only
    uv run --extra ai python scripts/download_models.py --update-lock      # after changing a pin

Every file comes from an exact Hugging Face revision (a commit hash, never
a branch). Hashes are checked against the committed ``models.lock.json``;
``--update-lock`` rewrites it, and only after confirming each large file's
sha256 against the hash the Hub publishes for that revision. The lock is
also copied into the model directory, where the worker reads it.

``--candidate NAME`` installs an alternative model under the ``clip`` key in
a separate directory, for side-by-side evaluation. It never touches the
committed lock.

Runs without the application settings (no database URL needed), so the AI
worker image can call it at build time.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.models_lock import (
    LOCK_FILENAME,
    LockedFile,
    LockedModel,
    ModelFilesError,
    ModelLock,
    load_lock,
    sha256_file,
    verify_model,
)

API_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_LOCK = API_ROOT / LOCK_FILENAME

_CLIP_CONFIG_OPENAI: dict[str, Any] = {
    "dim": 512,
    "image_size": 224,
    "resize": "shortest_edge_center_crop",
    "interpolation": "bicubic",
    "mean": [0.48145466, 0.4578275, 0.40821073],
    "std": [0.26862954, 0.26130258, 0.27577711],
    "context_length": 77,
    "pad_to_context": False,
    "pad_id": 49407,
    "text_dtype": "int64",
    "vision_input": "pixel_values",
    "text_input": "input_ids",
    "max_batch": 16,
    "logit_scale": 100.0,
}


@dataclass(frozen=True)
class Source:
    """A pinned model: what to fetch and what to record about it."""

    key: str
    model_id: str
    task: str
    name: str
    repo: str
    revision: str
    license: str
    license_url: str
    intended_use: str
    files: tuple[str, ...]
    config: dict[str, Any] = field(default_factory=dict)


CLIP = Source(
    key="clip",
    model_id="clip-vit-b32@onnx-1",
    task="embedding",
    name="CLIP ViT-B/32 (OpenAI weights), fp32 ONNX export by Xenova",
    repo="Xenova/clip-vit-base-patch32",
    revision="6b7c523703ae26e39be4b03774966f8571c7f523",
    license="MIT",
    license_url="https://github.com/openai/CLIP/blob/main/LICENSE",
    intended_use=(
        "Image embeddings for duplicate matching and zero-shot category suggestions. "
        "Suggestions are confirmed by the citizen or staff; never the sole basis for a decision."
    ),
    files=(
        "onnx/vision_model.onnx",
        "onnx/text_model.onnx",
        "tokenizer.json",
        "preprocessor_config.json",
    ),
    config={
        **_CLIP_CONFIG_OPENAI,
        "files": {
            "vision": "onnx/vision_model.onnx",
            "text": "onnx/text_model.onnx",
            "tokenizer": "tokenizer.json",
        },
    },
)

YUNET = Source(
    key="yunet",
    model_id="yunet-2023mar@onnx-1",
    task="face_detection",
    name="YuNet face detector (OpenCV Zoo, 2023mar)",
    repo="opencv/face_detection_yunet",
    revision="3cc26e7f1014a5ee5d74a42acee58bafc9d0a310",
    license="MIT",
    license_url="https://huggingface.co/opencv/face_detection_yunet/blob/3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/LICENSE",
    intended_use="Find faces in public copies of citizen photos so they can be blurred.",
    files=("face_detection_yunet_2023mar.onnx", "LICENSE"),
    config={"files": {"detector": "face_detection_yunet_2023mar.onnx"}},
)

PINNED: tuple[Source, ...] = (CLIP, YUNET)

# Alternatives evaluated against the default (docs/eval/phase-2-baseline.md).
CANDIDATES: dict[str, Source] = {
    "clip-int8": replace(
        CLIP,
        model_id="clip-vit-b32-int8@onnx-1",
        name="CLIP ViT-B/32 (OpenAI weights), int8 dynamic-quantised ONNX export by Xenova",
        files=(
            "onnx/vision_model_quantized.onnx",
            "onnx/text_model_quantized.onnx",
            "tokenizer.json",
        ),
        config={
            **_CLIP_CONFIG_OPENAI,
            "files": {
                "vision": "onnx/vision_model_quantized.onnx",
                "text": "onnx/text_model_quantized.onnx",
                "tokenizer": "tokenizer.json",
            },
        },
    ),
    "clip-laion2b": Source(
        key="clip",
        model_id="clip-vit-b32-laion2b@onnx-1",
        task="embedding",
        name="OpenCLIP ViT-B/32 laion2b_s34b_b79k, ONNX export by Immich",
        repo="immich-app/ViT-B-32__laion2b-s34b-b79k",
        revision="19a057a0fb927cf239541300e74237cd56c7ffe2",
        license="MIT (upstream laion/CLIP-ViT-B-32-laion2B-s34B-b79K; export repo has no tag)",
        license_url="https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        intended_use="Evaluation candidate only.",
        files=("visual/model.onnx", "textual/model.onnx", "textual/tokenizer.json"),
        config={
            **_CLIP_CONFIG_OPENAI,
            # Fixed-shape export: batch of one, prompts padded with zeros to 77.
            "pad_to_context": True,
            "pad_id": 0,
            "text_dtype": "int32",
            "vision_input": "image",
            "text_input": "text",
            "max_batch": 1,
            "files": {
                "vision": "visual/model.onnx",
                "text": "textual/model.onnx",
                "tokenizer": "textual/tokenizer.json",
            },
        },
    ),
}


def _fetch(source: Source, model_dir: Path, locked: LockedModel | None) -> LockedModel:
    from huggingface_hub import hf_hub_download  # pyright: ignore[reportMissingImports]

    target = model_dir / source.key
    files: list[LockedFile] = []
    for name in source.files:
        path = target / name
        expected = next((f for f in locked.files if f.path == name), None) if locked else None
        if expected and path.is_file() and path.stat().st_size == expected.size:
            digest = sha256_file(path)
            if digest == expected.sha256:
                print(f"  {source.key}/{name}: present, sha256 ok")
                files.append(expected)
                continue
            print(f"  {source.key}/{name}: hash mismatch, downloading again")
            path.unlink()
        print(f"  {source.key}/{name}: downloading {source.repo}@{source.revision[:12]}")
        hf_hub_download(source.repo, name, revision=source.revision, local_dir=target)
        files.append(LockedFile(path=name, sha256=sha256_file(path), size=path.stat().st_size))
    # hf_hub_download leaves resume metadata next to the files; it isn't needed once done.
    shutil.rmtree(target / ".cache", ignore_errors=True)
    return LockedModel(
        key=source.key,
        model_id=source.model_id,
        task=source.task,
        name=source.name,
        repo=source.repo,
        revision=source.revision,
        license=source.license,
        license_url=source.license_url,
        intended_use=source.intended_use,
        files=tuple(files),
        config=source.config,
    )


def _git_blob_id(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _check_against_hub(model: LockedModel, model_dir: Path) -> None:
    """Check every downloaded file against the hashes the Hub publishes for the revision.

    Large files are stored in LFS and listed with their sha256. Small ones
    (tokenizer, licence) only have a git blob id, which is a sha1 over the
    content; that still proves the bytes are the ones committed at the pin.
    """
    from huggingface_hub import HfApi  # pyright: ignore[reportMissingImports]

    info = HfApi().model_info(model.repo, revision=model.revision, files_metadata=True)
    siblings = {s.rfilename: s for s in info.siblings or []}
    for locked in model.files:
        sibling = siblings.get(locked.path)
        if sibling is None:
            raise ModelFilesError(
                f"{model.key}/{locked.path}: not in {model.repo}@{model.revision}"
            )
        if sibling.lfs is not None:
            ok, kind = sibling.lfs.sha256 == locked.sha256, "LFS sha256"
        else:
            actual = _git_blob_id(model_dir / model.key / locked.path)
            ok, kind = sibling.blob_id == actual, "git blob id"
        if not ok:
            raise ModelFilesError(f"{model.key}/{locked.path}: {kind} differs from the Hub's")
        print(f"  {model.key}/{locked.path}: {kind} matches the Hub")


def _compare(fetched: LockedModel, locked: LockedModel) -> list[str]:
    problems = []
    if (fetched.repo, fetched.revision) != (locked.repo, locked.revision):
        problems.append(
            f"{fetched.key}: pinned {fetched.repo}@{fetched.revision} but the lock has "
            f"{locked.repo}@{locked.revision} (run with --update-lock)"
        )
    elif replace(fetched, files=locked.files) != locked:
        problems.append(
            f"{fetched.key}: model id, licence or loader config differ from the lock "
            "(run with --update-lock)"
        )
    lock_files = {f.path: f for f in locked.files}
    for f in fetched.files:
        if f.path not in lock_files:
            problems.append(f"{fetched.key}/{f.path}: not in the lock (run with --update-lock)")
        elif lock_files[f.path] != f:
            problems.append(f"{fetched.key}/{f.path}: sha256 {f.sha256} doesn't match the lock")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(os.environ.get("AI_MODEL_DIR", "/models")),
        help="Where the weights go (default: $AI_MODEL_DIR or /models)",
    )
    parser.add_argument("--update-lock", action="store_true", help="Rewrite models.lock.json")
    parser.add_argument(
        "--verify-only", action="store_true", help="Hash the files in --model-dir; no network"
    )
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), help="Evaluation alternative")
    args = parser.parse_args(argv)
    model_dir: Path = args.model_dir.resolve()

    if args.verify_only:
        lock = load_lock(model_dir / LOCK_FILENAME)
        problems = [p for m in lock.models.values() for p in verify_model(model_dir, m)]
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("model files ok" if not problems else "model files don't match the lock")
        return 1 if problems else 0

    model_dir.mkdir(parents=True, exist_ok=True)

    if args.candidate:
        source = CANDIDATES[args.candidate]
        fetched = _fetch(source, model_dir, None)
        _check_against_hub(fetched, model_dir)
        (model_dir / LOCK_FILENAME).write_text(
            ModelLock(models={fetched.key: fetched}).to_json(), encoding="utf-8", newline="\n"
        )
        print(f"candidate {args.candidate} ({fetched.model_id}) installed in {model_dir}")
        return 0

    committed = None if args.update_lock else load_lock(COMMITTED_LOCK)
    models: dict[str, LockedModel] = {}
    problems: list[str] = []
    for source in PINNED:
        locked = committed.models.get(source.key) if committed else None
        if committed is not None and locked is None:
            problems.append(f"{source.key}: not in the lock (run with --update-lock)")
            continue
        fetched = _fetch(source, model_dir, locked)
        if locked is not None:
            problems.extend(_compare(fetched, locked))
            # The lock is the record of truth for metadata (licence, model id).
            fetched = replace(locked, files=fetched.files)
        else:
            _check_against_hub(fetched, model_dir)
        models[source.key] = fetched

    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("model files don't match the lock; nothing was recorded", file=sys.stderr)
        return 1

    lock = ModelLock(models=models)
    if args.update_lock:
        COMMITTED_LOCK.write_text(lock.to_json(), encoding="utf-8", newline="\n")
        print(f"wrote {COMMITTED_LOCK}")
    (model_dir / LOCK_FILENAME).write_text(lock.to_json(), encoding="utf-8", newline="\n")
    print(f"models ready in {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
