from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from app.ai.interfaces import ZeroShotClassifier
from app.ai.prompts import DEFAULT_PROMPTS, NOT_CIVIC, UNKNOWN
from app.ai.zero_shot import (
    PromptZeroShotClassifier,
    class_vectors,
    fit_temperature,
    pool_images,
    scores_from_similarities,
    softmax,
)

# Three-dimensional "embeddings": each axis is one concept.
AXES = {"hole": [1, 0, 0], "trash": [0, 1, 0], "selfie": [0, 0, 1]}


class TinyModel:
    """A VisionModel whose text embedding is the sum of the concept words it contains."""

    model_id = "tiny@1"
    dim = 3

    def __init__(self) -> None:
        self.text_calls: list[list[str]] = []

    def embed_images(self, images: list[Image.Image]) -> NDArray[np.float32]:
        raise NotImplementedError

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        self.text_calls.append(list(texts))
        out = np.zeros((len(texts), 3), dtype=np.float32)
        for row, text in enumerate(texts):
            for word, axis in AXES.items():
                if word in text:
                    out[row] += axis
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return (out / np.maximum(norms, 1e-12)).astype(np.float32)


PROMPTS = {
    "pothole": ["a hole", "a big hole"],
    "waste": ["trash", "more trash"],
    NOT_CIVIC: ["a selfie"],
}


def unit(*values: float) -> NDArray[np.float32]:
    v = np.asarray(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_softmax_is_stable_and_sums_to_one() -> None:
    probs = softmax(np.array([1000.0, 1001.0, 999.0]))
    assert probs.sum() == pytest.approx(1.0)
    assert probs.argmax() == 1
    np.testing.assert_allclose(softmax(np.zeros(4)), 0.25)


def test_pool_images_averages_then_renormalises() -> None:
    pooled = pool_images(np.stack([unit(1, 0, 0), unit(0, 1, 0)]))
    np.testing.assert_allclose(pooled, unit(1, 1, 0), atol=1e-6)
    np.testing.assert_allclose(pool_images(unit(0, 0, 2)), [0, 0, 1])  # 1-D input is one photo
    with pytest.raises(ValueError, match="n >= 1"):
        pool_images(np.empty((0, 3), dtype=np.float32))


def test_class_vectors_ensemble_prompts() -> None:
    out = class_vectors([np.stack([unit(1, 0, 0), unit(1, 1, 0)]), unit(0, 0, 1)[None, :]])
    assert out.shape == (2, 3)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-6)
    assert out[0, 0] > out[0, 1] > 0


def test_temperature_sharpens_or_flattens_the_distribution() -> None:
    sims = np.array([0.30, 0.25, 0.20])
    sharp = scores_from_similarities(["a", "b", "c"], sims, temperature=0.01, threshold=0)
    flat = scores_from_similarities(["a", "b", "c"], sims, temperature=1.0, threshold=0)
    assert sharp[0].confidence > 0.99
    assert flat[0].confidence < 0.4
    for scores in (sharp, flat):
        assert sum(s.confidence for s in scores) == pytest.approx(1.0)
        assert [s.code for s in scores] == ["a", "b", "c"]


def test_below_threshold_returns_unknown_first_with_the_full_distribution_after() -> None:
    sims = np.array([0.30, 0.29, 0.28])
    scores = scores_from_similarities(["a", "b", "c"], sims, temperature=0.05, threshold=0.45)
    top = scores[1].confidence
    assert top < 0.45
    assert scores[0].code == UNKNOWN
    assert scores[0].confidence == pytest.approx(1 - top)
    assert [s.code for s in scores[1:]] == ["a", "b", "c"]
    assert sum(s.confidence for s in scores[1:]) == pytest.approx(1.0)


def test_at_or_above_threshold_has_no_unknown() -> None:
    scores = scores_from_similarities(
        ["a", "b"], np.array([0.5, 0.0]), temperature=0.1, threshold=0.45
    )
    assert scores[0].code == "a"
    assert all(s.code != UNKNOWN for s in scores)


def test_ties_are_broken_by_code_for_determinism() -> None:
    scores = scores_from_similarities(
        ["b", "a"], np.array([0.2, 0.2]), temperature=0.1, threshold=0
    )
    assert [s.code for s in scores] == ["a", "b"]


def test_classifier_picks_the_matching_category() -> None:
    clf = PromptZeroShotClassifier(TinyModel(), temperature=0.1, threshold=0.45)
    assert isinstance(clf, ZeroShotClassifier)
    scores = clf.classify(unit(1, 0.1, 0)[None, :], PROMPTS)
    assert scores[0].code == "pothole"
    assert scores[0].confidence > 0.9
    selfie = clf.classify(unit(0, 0, 1)[None, :], PROMPTS)
    assert selfie[0].code == NOT_CIVIC


def test_several_photos_vote_together() -> None:
    clf = PromptZeroShotClassifier(TinyModel(), temperature=0.1, threshold=0)
    photos = np.stack([unit(1, 0.2, 0), unit(1, 0, 0.1), unit(0.1, 1, 0)])
    assert clf.classify(photos, PROMPTS)[0].code == "pothole"


def test_ambiguous_photo_is_unknown() -> None:
    clf = PromptZeroShotClassifier(TinyModel(), temperature=0.5, threshold=0.45)
    scores = clf.classify(unit(1, 1, 1)[None, :], PROMPTS)
    assert scores[0].code == UNKNOWN
    assert {s.code for s in scores[1:]} == set(PROMPTS)


def test_prompt_embeddings_are_cached_per_prompt_set() -> None:
    model = TinyModel()
    clf = PromptZeroShotClassifier(model, cache_size=2)
    query = unit(1, 0, 0)[None, :]
    clf.classify(query, PROMPTS)
    clf.classify(query, {code: list(texts) for code, texts in reversed(PROMPTS.items())})
    assert len(model.text_calls) == 1  # same set, different dict order
    other = {**PROMPTS, "pothole": ["a hole in the road"]}
    clf.classify(query, other)
    assert len(model.text_calls) == 2
    clf.classify(query, {"waste": ["trash"], NOT_CIVIC: ["a selfie"]})  # evicts PROMPTS
    clf.classify(query, PROMPTS)
    assert len(model.text_calls) == 4


def test_classification_is_deterministic() -> None:
    clf = PromptZeroShotClassifier(TinyModel(), temperature=0.07)
    query = np.stack([unit(0.4, 0.5, 0.1), unit(0.6, 0.2, 0.3)])
    assert clf.classify(query, PROMPTS) == clf.classify(query.copy(), PROMPTS)


@pytest.mark.parametrize(
    ("prompts", "message"),
    [
        ({}, "no categories"),
        ({"pothole": []}, "no usable prompts"),
        ({"pothole": ["  "]}, "no usable prompts"),
        ({UNKNOWN: ["anything"]}, "reserved"),
    ],
)
def test_bad_prompt_sets_are_rejected(prompts: dict[str, list[str]], message: str) -> None:
    clf = PromptZeroShotClassifier(TinyModel())
    with pytest.raises(ValueError, match=message):
        clf.classify(unit(1, 0, 0)[None, :], prompts)


def test_dimension_mismatch_is_an_error() -> None:
    clf = PromptZeroShotClassifier(TinyModel())
    with pytest.raises(ValueError, match="dim"):
        clf.classify(np.ones((1, 5), dtype=np.float32), PROMPTS)


def test_invalid_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="temperature"):
        PromptZeroShotClassifier(TinyModel(), temperature=0)
    with pytest.raises(ValueError, match="threshold"):
        PromptZeroShotClassifier(TinyModel(), threshold=1.5)


def test_fit_temperature_recovers_the_generating_temperature() -> None:
    rng = np.random.default_rng(7)
    true_t = 0.04
    sims = rng.normal(0.22, 0.03, size=(4000, 6))
    probs = softmax(sims / true_t)
    labels = np.array([rng.choice(6, p=p) for p in probs])
    assert fit_temperature(sims, labels) == pytest.approx(true_t, rel=0.1)


def test_default_prompts_cover_the_seeded_categories() -> None:
    assert set(DEFAULT_PROMPTS) == {
        "pothole",
        "waste",
        "waterlogging",
        "streetlight",
        "drainage",
        NOT_CIVIC,
    }
    for code, texts in DEFAULT_PROMPTS.items():
        assert 3 <= len(texts) <= 6, code
        assert len(set(texts)) == len(texts), code
