"""The deterministic fakes behave the way tests rely on them to."""

from __future__ import annotations

import io
import itertools

import numpy as np
import pytest
from PIL import Image

from app.ai import registry
from app.ai.fake import (
    EMBEDDING_DIM,
    FakeFaceDetector,
    FakeVisionModel,
    FakeZeroShotClassifier,
    fake_perceptual_hash,
    make_scene,
)
from app.ai.interfaces import (
    FaceDetector,
    VisionModel,
    ZeroShotClassifier,
    perceptual_hash_distance,
)

PROMPTS = {code: [f"a photo of {code}"] for code in ("pothole", "waste", "drainage", "not_civic")}


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _embed(*pictures: bytes) -> np.ndarray:
    return FakeVisionModel().embed_images([_open(p) for p in pictures])


def _recompress(data: bytes, *, quality: int = 60, scale: float = 0.5) -> bytes:
    image = _open(data)
    image = image.resize((int(image.width * scale), int(image.height * scale)))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def test_the_fakes_satisfy_the_protocols() -> None:
    assert isinstance(registry.get_vision_model(), VisionModel)
    assert isinstance(registry.get_classifier(), ZeroShotClassifier)
    assert isinstance(registry.get_face_detector(), FaceDetector)
    assert registry.get_vision_model().dim == EMBEDDING_DIM


def test_embeddings_are_deterministic_unit_vectors() -> None:
    first, again = _embed(make_scene(1), make_scene(1))
    assert first.shape == (EMBEDDING_DIM,)
    assert first.dtype == np.float32
    assert np.linalg.norm(first) == pytest.approx(1.0, abs=1e-5)
    assert np.array_equal(first, again)


def test_same_scene_scores_near_one_and_different_scenes_near_zero() -> None:
    base = make_scene(7)
    same = [make_scene(7, variant=1), make_scene(7, variant=2), _recompress(base)]
    for other in same:
        a, b = _embed(base, other)
        assert float(a @ b) > 0.97

    scenes = [make_scene(seed) for seed in range(20, 30)]
    vectors = _embed(*scenes)
    for i, j in itertools.combinations(range(len(scenes)), 2):
        assert float(vectors[i] @ vectors[j]) < 0.45


def test_a_shared_label_does_not_make_different_scenes_look_alike() -> None:
    a, b = _embed(make_scene(40, label="pothole"), make_scene(41, label="pothole"))
    plain_a, plain_b = _embed(make_scene(40), make_scene(41))
    assert float(a @ b) - float(plain_a @ plain_b) < 0.25
    assert float(a @ b) < 0.6


def test_a_label_chooses_the_classification() -> None:
    classifier = FakeZeroShotClassifier()
    scores = classifier.classify(_embed(make_scene(3, label="drainage:0.82")), PROMPTS)
    assert scores[0].code == "drainage"
    assert scores[0].confidence == pytest.approx(0.82, abs=1e-6)
    assert sum(s.confidence for s in scores) == pytest.approx(1.0)
    assert [s.confidence for s in scores] == sorted((s.confidence for s in scores), reverse=True)

    default = classifier.classify(_embed(make_scene(3, label="pothole")), PROMPTS)
    assert (default[0].code, default[0].confidence) == ("pothole", pytest.approx(0.9))

    png = classifier.classify(_embed(make_scene(3, label="not_civic", image_format="PNG")), PROMPTS)
    assert png[0].code == "not_civic"


def test_without_a_label_the_answer_is_unknown() -> None:
    unknown, *scores = FakeZeroShotClassifier().classify(_embed(make_scene(5)), PROMPTS)
    assert (unknown.code, unknown.confidence) == ("unknown", pytest.approx(0.75))
    assert [s.confidence for s in scores] == pytest.approx([0.25] * 4)
    unknown_label = FakeZeroShotClassifier().classify(
        _embed(make_scene(5, label="selfie")), PROMPTS
    )
    assert unknown_label[0].code == "unknown"
    assert [s.confidence for s in unknown_label[1:]] == pytest.approx([0.25] * 4)


def test_several_photos_are_classified_together() -> None:
    vectors = _embed(make_scene(8, label="waste:0.7"), make_scene(9, label="waste:0.7"))
    scores = FakeZeroShotClassifier().classify(vectors, PROMPTS)
    assert (scores[0].code, scores[0].confidence) == ("waste", pytest.approx(0.7, abs=1e-6))


def test_the_face_detector_reports_the_hooked_boxes() -> None:
    picture = _open(make_scene(11, faces=[(10, 20, 30, 40)], image_format="PNG"))
    (box,) = FakeFaceDetector().detect(picture)
    assert (box.x, box.y, box.width, box.height) == (10, 20, 30, 40)
    assert FakeFaceDetector().detect(_open(make_scene(11))) == []


def test_perceptual_hash_survives_recompression_and_separates_scenes() -> None:
    base = fake_perceptual_hash(_open(make_scene(12)))
    assert 0 <= base < 2**64
    for other in (make_scene(12, variant=1), _recompress(make_scene(12))):
        assert perceptual_hash_distance(base, fake_perceptual_hash(_open(other))) <= 6
    far = [fake_perceptual_hash(_open(make_scene(seed))) for seed in range(50, 60)]
    assert min(perceptual_hash_distance(base, h) for h in far) > 10
