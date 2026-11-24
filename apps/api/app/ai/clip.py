"""CLIP-family ``VisionModel`` on ONNX Runtime (CPU only, no torch).

The vision and text towers are separate ONNX graphs, so the AI worker can
embed photos without loading the text tower until the first classification
needs prompt embeddings. Everything the loader needs to know (which file is
which, preprocessing constants, tokenizer padding) comes from the model lock
entry written by ``scripts/download_models.py``; nothing about a particular
export is hard-coded here beyond the defaults for OpenAI CLIP.

Preprocessing reproduces ``CLIPImageProcessor`` (what the reference
exports were validated with): RGB, resize the shortest edge to 224 with
bicubic filtering, centre-crop 224x224, scale to [0, 1] and normalise with
CLIP's channel means and standard deviations. ``tests/ai`` checks it against
the transformers.js model card result.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.ai.models_lock import LockedModel, model_path, verify_model_dir

if TYPE_CHECKING:
    import onnxruntime
    from tokenizers import Tokenizer

CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)

_RESAMPLE = {
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
}


@dataclass(frozen=True, slots=True)
class ClipConfig:
    """How to feed one particular export. Defaults match OpenAI CLIP ViT-B/32."""

    dim: int = 512
    image_size: int = 224
    resize: Literal["shortest_edge_center_crop", "squash"] = "shortest_edge_center_crop"
    interpolation: Literal["bicubic", "bilinear"] = "bicubic"
    mean: tuple[float, float, float] = CLIP_MEAN
    std: tuple[float, float, float] = CLIP_STD
    context_length: int = 77
    pad_to_context: bool = False
    """Pad every prompt to ``context_length`` (fixed-shape exports) or only to the batch max."""
    pad_id: int = 49407
    text_dtype: Literal["int64", "int32"] = "int64"
    vision_input: str = "pixel_values"
    text_input: str = "input_ids"
    max_batch: int = 16
    """Largest batch sent to one ``run`` call; 1 for exports with a fixed batch axis."""
    logit_scale: float = 100.0
    """The model's learned inverse temperature; a starting point for calibration."""

    @classmethod
    def from_lock(cls, config: dict[str, Any]) -> ClipConfig:
        known = {name for name in cls.__dataclass_fields__ if name in config}
        values: dict[str, Any] = {name: config[name] for name in known}
        for name in ("mean", "std"):
            if name in values:
                values[name] = tuple(values[name])
        return cls(**values)


def preprocess(images: Sequence[Image.Image], config: ClipConfig) -> NDArray[np.float32]:
    """Turn PIL images into a normalised ``(n, 3, size, size)`` float32 batch."""
    size = config.image_size
    resample = _RESAMPLE[config.interpolation]
    mean = np.asarray(config.mean, dtype=np.float32).reshape(1, 1, 3)
    std = np.asarray(config.std, dtype=np.float32).reshape(1, 1, 3)
    batch = np.empty((len(images), 3, size, size), dtype=np.float32)
    for index, image in enumerate(images):
        rgb = image.convert("RGB")
        if config.resize == "squash":
            rgb = rgb.resize((size, size), resample)
        else:
            rgb = _resize_shortest_edge(rgb, size, resample)
            rgb = _center_crop(rgb, size)
        pixels = np.asarray(rgb, dtype=np.float32) / 255.0
        batch[index] = ((pixels - mean) / std).transpose(2, 0, 1)
    return batch


def _resize_shortest_edge(image: Image.Image, size: int, resample: Image.Resampling) -> Image.Image:
    # Same arithmetic as transformers' get_resize_output_image_size: the long
    # side is truncated, not rounded.
    width, height = image.size
    short, long = (width, height) if width <= height else (height, width)
    new_short, new_long = size, int(size * long / short)
    new_size = (new_short, new_long) if width <= height else (new_long, new_short)
    if new_size == image.size:
        return image
    return image.resize(new_size, resample)


def _center_crop(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    left = (width - size) // 2
    top = (height - size) // 2
    return image.crop((left, top, left + size, top + size))


def l2_normalize(vectors: NDArray[np.floating]) -> NDArray[np.float32]:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def default_threads() -> int:
    """Intra-op threads for a small CPU box: all cores, but at most four.

    Past four threads a ViT-B/32 forward pass barely gets faster, and the
    worker runs one task at a time, so more threads would only contend with
    Postgres and the other services on the same host.
    """
    return max(1, min(4, os.cpu_count() or 1))


def _session_options(threads: int) -> onnxruntime.SessionOptions:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.log_severity_level = 3  # errors only; the shape-inference warnings are noise
    return options


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class ClipOnnxModel:
    """``VisionModel`` backed by separate CLIP vision and text ONNX graphs."""

    def __init__(
        self,
        *,
        model_id: str,
        vision_path: Path,
        text_path: Path,
        tokenizer_path: Path,
        config: ClipConfig | None = None,
        threads: int | None = None,
    ) -> None:
        self._model_id = model_id
        self._config = config or ClipConfig()
        self._vision_path = vision_path
        self._text_path = text_path
        self._tokenizer_path = tokenizer_path
        self._threads = threads or default_threads()
        self._lock = threading.Lock()
        self._vision: onnxruntime.InferenceSession | None = None
        self._text: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        for path in (vision_path, text_path, tokenizer_path):
            if not path.is_file():
                raise FileNotFoundError(f"model file not found: {path}")

    @classmethod
    def from_model_dir(
        cls, model_dir: Path, key: str = "clip", *, threads: int | None = None
    ) -> ClipOnnxModel:
        """Load the model recorded under ``key`` in ``<model_dir>/models.lock.json``.

        Checks presence and size of every locked file (cheap), not hashes.
        """
        lock = verify_model_dir(model_dir, [key], check_hashes=False)
        entry: LockedModel = lock.get(key)
        return cls(
            model_id=entry.model_id,
            vision_path=model_path(model_dir, entry, "vision"),
            text_path=model_path(model_dir, entry, "text"),
            tokenizer_path=model_path(model_dir, entry, "tokenizer"),
            config=ClipConfig.from_lock(entry.config),
            threads=threads,
        )

    # -- VisionModel --------------------------------------------------------

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dim(self) -> int:
        return self._config.dim

    @property
    def config(self) -> ClipConfig:
        return self._config

    def embed_images(self, images: list[Image.Image]) -> NDArray[np.float32]:
        if not images:
            return np.empty((0, self.dim), dtype=np.float32)
        session = self._vision_session()
        output = session.get_outputs()[0].name
        parts: list[NDArray[np.float32]] = []
        for chunk in _chunks(images, self._config.max_batch):
            pixels = preprocess(chunk, self._config)
            (embeds,) = session.run([output], {self._config.vision_input: pixels})
            parts.append(np.asarray(embeds, dtype=np.float32))
        return self._finish(np.concatenate(parts))

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        session = self._text_session()
        output = session.get_outputs()[0].name
        parts: list[NDArray[np.float32]] = []
        for chunk in _chunks(texts, self._config.max_batch):
            ids = self.tokenize(list(chunk))
            (embeds,) = session.run([output], {self._config.text_input: ids})
            parts.append(np.asarray(embeds, dtype=np.float32))
        return self._finish(np.concatenate(parts))

    # -- helpers ------------------------------------------------------------

    def tokenize(self, texts: list[str]) -> NDArray[np.integer]:
        """Token ids padded to a rectangle, with the end-of-text token kept on truncation."""
        tokenizer = self._get_tokenizer()
        limit = self._config.context_length
        rows: list[list[int]] = []
        for encoding in tokenizer.encode_batch(texts):
            ids = list(encoding.ids)
            if len(ids) > limit:
                ids = [*ids[: limit - 1], ids[-1]]
            rows.append(ids)
        width = limit if self._config.pad_to_context else max(len(r) for r in rows)
        out = np.full((len(rows), width), self._config.pad_id, dtype=self._config.text_dtype)
        for index, ids in enumerate(rows):
            out[index, : len(ids)] = ids
        return out

    def warm_up(self) -> None:
        """Load both graphs and run one dummy pass, so the first task isn't slow."""
        size = self._config.image_size
        self.embed_images([Image.new("RGB", (size, size))])
        self.embed_texts(["a photo"])

    def _finish(self, embeds: NDArray[np.float32]) -> NDArray[np.float32]:
        if embeds.ndim != 2 or embeds.shape[1] != self.dim:
            raise ValueError(f"model returned shape {embeds.shape}, expected (n, {self.dim})")
        return l2_normalize(embeds)

    def _vision_session(self) -> onnxruntime.InferenceSession:
        if self._vision is None:
            with self._lock:
                if self._vision is None:
                    self._vision = self._open(self._vision_path)
        return self._vision

    def _text_session(self) -> onnxruntime.InferenceSession:
        if self._text is None:
            with self._lock:
                if self._text is None:
                    self._text = self._open(self._text_path)
        return self._text

    def _get_tokenizer(self) -> Tokenizer:
        if self._tokenizer is None:
            from tokenizers import Tokenizer

            with self._lock:
                if self._tokenizer is None:
                    self._tokenizer = Tokenizer.from_file(str(self._tokenizer_path))
        return self._tokenizer

    def _open(self, path: Path) -> onnxruntime.InferenceSession:
        import onnxruntime as ort

        # Some builds send usage telemetry; citizen photos never leave the box,
        # and neither should anything about how we process them.
        ort.disable_telemetry_events()
        return ort.InferenceSession(
            str(path),
            sess_options=_session_options(self._threads),
            providers=["CPUExecutionProvider"],
        )
