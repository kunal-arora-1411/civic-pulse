"""Zero-shot category suggestions from CLIP-style embeddings.

For one report:

1. Each category's prompts are embedded, normalised, averaged and
   normalised again (prompt ensembling, as in the CLIP paper). These class
   vectors are cached per prompt set, so tenants with their own prompts
   don't evict each other and nobody re-embeds text on every request.
2. The report's photo embeddings are mean-pooled into one unit vector.
   Several photos of the same problem vote together, and one odd photo
   pulls the result less than it would if we took the best single photo.
3. Cosine similarities are divided by a temperature and softmaxed. The
   temperature is fitted on the evaluation set (see
   ``docs/eval/phase-2-baseline.md``) so that the confidences mean
   roughly what they say; CLIP's own scale (100, i.e. T = 0.01) is
   overconfident on our categories.
4. If the best category is below ``threshold`` the reserved ``unknown``
   code comes first, with confidence ``1 - top``. The full softmax follows
   it unchanged, so callers can still offer the top categories as
   suggestions while asking for manual selection.

Pure numpy apart from the text embedding call, and deterministic.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from app.ai.interfaces import CategoryScore, VisionModel
from app.ai.prompts import NOT_CIVIC, UNKNOWN

# Fitted on the calibration split; see docs/eval/phase-2-baseline.md.
DEFAULT_TEMPERATURE = 0.01
DEFAULT_THRESHOLD = 0.45

PromptKey = tuple[tuple[str, tuple[str, ...]], ...]


def softmax(logits: NDArray[np.floating], axis: int = -1) -> NDArray[np.float64]:
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp = np.exp(shifted.astype(np.float64))
    return exp / exp.sum(axis=axis, keepdims=True)


def normalize(vectors: NDArray[np.floating]) -> NDArray[np.float32]:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def pool_images(image_embeddings: NDArray[np.floating]) -> NDArray[np.float32]:
    """Mean-pool one report's photo embeddings into a single unit vector."""
    embeddings = np.asarray(image_embeddings, dtype=np.float32)
    if embeddings.ndim == 1:
        embeddings = embeddings[None, :]
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError(f"expected an (n, dim) array with n >= 1, got {embeddings.shape}")
    return normalize(normalize(embeddings).mean(axis=0))


def class_vectors(
    prompt_embeddings: Sequence[NDArray[np.floating]],
) -> NDArray[np.float32]:
    """One unit vector per class from that class's ``(k, dim)`` prompt embeddings."""
    return np.stack([normalize(normalize(e).mean(axis=0)) for e in prompt_embeddings])


def scores_from_similarities(
    codes: Sequence[str],
    similarities: NDArray[np.floating],
    *,
    temperature: float,
    threshold: float,
) -> list[CategoryScore]:
    """Softmax over cosine similarities, sorted, with the ``unknown`` rule applied."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    probs = softmax(np.asarray(similarities, dtype=np.float64) / temperature)
    order = sorted(range(len(codes)), key=lambda i: (-probs[i], codes[i]))
    scores = [CategoryScore(codes[i], float(probs[i])) for i in order]
    top = scores[0].confidence
    if top < threshold:
        return [CategoryScore(UNKNOWN, 1.0 - top), *scores]
    return scores


def prompt_key(prompts: Mapping[str, Sequence[str]]) -> PromptKey:
    return tuple(sorted((code, tuple(texts)) for code, texts in prompts.items()))


class PromptZeroShotClassifier:
    """``ZeroShotClassifier`` over a ``VisionModel``'s text tower."""

    def __init__(
        self,
        model: VisionModel,
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        threshold: float = DEFAULT_THRESHOLD,
        cache_size: int = 64,
    ) -> None:
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be within [0, 1]")
        self._model = model
        self.temperature = temperature
        self.threshold = threshold
        self._cache: OrderedDict[tuple[str, PromptKey], tuple[list[str], NDArray[np.float32]]]
        self._cache = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model.model_id

    def classify(
        self,
        image_embeddings: NDArray[np.float32],
        prompts: dict[str, list[str]],
    ) -> list[CategoryScore]:
        codes, classes = self.class_matrix(prompts)
        query = pool_images(image_embeddings)
        if query.shape[-1] != classes.shape[1]:
            raise ValueError(
                f"image embeddings have dim {query.shape[-1]}, prompts {classes.shape[1]}"
            )
        return scores_from_similarities(
            codes, classes @ query, temperature=self.temperature, threshold=self.threshold
        )

    def class_matrix(self, prompts: Mapping[str, Sequence[str]]) -> tuple[list[str], NDArray]:
        """Category codes and their ``(k, dim)`` class vectors, embedding prompts on a miss."""
        if not prompts:
            raise ValueError("no categories to classify against")
        for code, texts in prompts.items():
            if code == UNKNOWN:
                raise ValueError(f"{UNKNOWN!r} is reserved for low-confidence results")
            if not texts or not all(t.strip() for t in texts):
                raise ValueError(f"category {code!r} has no usable prompts")
        key = (self._model.model_id, prompt_key(prompts))
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        codes = sorted(prompts)
        flat = [text for code in codes for text in prompts[code]]
        embedded = self._model.embed_texts(flat)
        groups, start = [], 0
        for code in codes:
            groups.append(embedded[start : start + len(prompts[code])])
            start += len(prompts[code])
        entry = (codes, class_vectors(groups))
        with self._lock:
            self._cache[key] = entry
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return entry


def fit_temperature(
    similarities: NDArray[np.floating],
    labels: NDArray[np.integer],
    *,
    low: float = 1e-3,
    high: float = 1.0,
    iterations: int = 80,
) -> float:
    """Temperature minimising the mean negative log-likelihood of ``labels``.

    ``similarities`` is ``(n, k)`` cosine similarities and ``labels`` the
    index of the true class per row. The NLL is unimodal in log T for
    softmax scaling, so a golden-section search over log T is enough.
    """
    sims = np.asarray(similarities, dtype=np.float64)
    idx = np.asarray(labels)
    rows = np.arange(len(idx))

    def nll(log_t: float) -> float:
        logits = sims / np.exp(log_t)
        logits = logits - logits.max(axis=1, keepdims=True)
        log_norm = np.log(np.exp(logits).sum(axis=1))
        return float(np.mean(log_norm - logits[rows, idx]))

    a, b = np.log(low), np.log(high)
    ratio = (np.sqrt(5) - 1) / 2
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = nll(c), nll(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = nll(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = nll(d)
    return float(np.exp((a + b) / 2))


__all__ = [
    "DEFAULT_TEMPERATURE",
    "DEFAULT_THRESHOLD",
    "NOT_CIVIC",
    "UNKNOWN",
    "PromptZeroShotClassifier",
    "class_vectors",
    "fit_temperature",
    "pool_images",
    "scores_from_similarities",
    "softmax",
]
