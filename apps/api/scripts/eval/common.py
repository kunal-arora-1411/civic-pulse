"""Shared helpers for the evaluation scripts: model loading, cached embeddings, tables."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.ai.clip import ClipOnnxModel
from scripts.eval.manifest import API_ROOT, DEFAULT_CACHE, Item, load_image

DEFAULT_MODEL_DIR = Path(os.environ.get("AI_MODEL_DIR") or API_ROOT / ".models")


def load_model(model_dir: Path) -> ClipOnnxModel:
    return ClipOnnxModel.from_model_dir(model_dir)


def embed_items(
    model: ClipOnnxModel,
    items: Sequence[Item],
    manifest_dir: Path,
    cache_dir: Path = DEFAULT_CACHE,
    batch: int = 16,
) -> NDArray[np.float32]:
    """Image embeddings for ``items`` in order, cached per model id under the eval cache."""
    store = cache_dir / "embeddings" / f"{model.model_id.replace('@', '_')}.npz"
    cached: dict[str, NDArray[np.float32]] = {}
    if store.is_file():
        with np.load(store) as data:
            cached = {key: data[key] for key in data.files}
    missing = [item for item in items if item.key not in cached]
    if missing:
        start = time.perf_counter()
        for offset in range(0, len(missing), batch):
            chunk = missing[offset : offset + batch]
            images = [load_image(item, manifest_dir, cache_dir) for item in chunk]
            for item, vector in zip(chunk, model.embed_images(images), strict=True):
                cached[item.key] = vector
        elapsed = time.perf_counter() - start
        print(f"embedded {len(missing)} images in {elapsed:.1f}s ({model.model_id})")
        store.parent.mkdir(parents=True, exist_ok=True)
        np.savez(store, **cached)  # pyright: ignore[reportArgumentType]
    return np.stack([cached[item.key] for item in items])


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """A GitHub-flavoured Markdown table."""

    def fmt(value: object) -> str:
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" if i == 0 else "---:" for i in range(len(headers))) + "|",
    ]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)
