from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from app.ai.faces import YuNetFaceDetector, blur_regions, merge_boxes, scale_boxes
from app.ai.interfaces import Box, FaceDetector
from tests.ai.conftest import fetch_image
from tests.ai.synthetic import scene


def detail(pixels: NDArray[np.floating]) -> float:
    """Variance of a 4-neighbour Laplacian: how much fine detail a region has."""
    grey = pixels.mean(axis=2) if pixels.ndim == 3 else pixels
    lap = (
        -4 * grey[1:-1, 1:-1] + grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:]
    )
    return float(lap.var())


def noisy(size: tuple[int, int] = (400, 300), seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8))


def test_no_boxes_returns_an_identical_copy() -> None:
    image = scene(0)
    out = blur_regions(image, [])
    assert out is not image
    assert np.array_equal(np.asarray(out), np.asarray(image))


def test_only_the_padded_box_changes() -> None:
    image = noisy()
    box = Box(100, 80, 60, 70, 0.9)
    out = np.asarray(blur_regions(image, [box], padding=0.25)).astype(int)
    before = np.asarray(image).astype(int)
    pad_x, pad_y = 15, round(70 * 0.25)
    mask = np.zeros(before.shape[:2], dtype=bool)
    mask[80 - pad_y : 80 + 70 + pad_y, 100 - pad_x : 100 + 60 + pad_x] = True
    assert np.array_equal(out[~mask], before[~mask])
    assert np.abs(out[mask] - before[mask]).mean() > 30


def test_face_detail_is_destroyed() -> None:
    image = noisy()
    box = Box(120, 90, 80, 100, 0.9)
    out = np.asarray(blur_regions(image, [box]), dtype=np.float64)
    region = (slice(90, 190), slice(120, 200))
    original = np.asarray(image, dtype=np.float64)[region]
    blurred = out[region]
    assert detail(blurred) < 0.01 * detail(original)
    # Nothing of the original pixel pattern survives: the residual detail is
    # uncorrelated with what was there.
    orig_hp = original - original.mean()
    blur_hp = blurred - blurred.mean()
    corr = float((orig_hp * blur_hp).sum() / np.sqrt((orig_hp**2).sum() * (blur_hp**2).sum()))
    assert abs(corr) < 0.1


def test_tiny_faces_still_get_a_margin_and_a_blur() -> None:
    image = noisy((200, 200), seed=3)
    box = Box(50, 50, 6, 7, 0.7)
    out = np.asarray(blur_regions(image, [box]), dtype=np.float64)
    before = np.asarray(image, dtype=np.float64)
    # min_padding=4 on every side, even though 25% of 6 px is 2 px.
    assert not np.array_equal(out[46:61, 46:60], before[46:61, 46:60])
    assert np.array_equal(out[:45], before[:45])
    assert detail(out[47:60, 47:59]) < 0.1 * detail(before[47:60, 47:59])


def test_boxes_touching_the_border_are_clamped() -> None:
    image = noisy((120, 90))
    out = blur_regions(image, [Box(-10, -5, 40, 40, 0.9), Box(100, 70, 50, 50, 0.8)])
    assert out.size == image.size


def test_merge_boxes_keeps_the_best_of_overlapping_detections() -> None:
    boxes = [
        Box(10, 10, 50, 50, 0.7),
        Box(12, 11, 50, 50, 0.95),  # same face from the other pass
        Box(200, 10, 40, 40, 0.8),
    ]
    merged = merge_boxes(boxes)
    assert [b.score for b in merged] == [0.95, 0.8]


def test_scale_boxes_maps_between_renditions_conservatively() -> None:
    (scaled,) = scale_boxes([Box(101, 51, 33, 21, 0.9)], (1600, 1200), (400, 300))
    assert (scaled.x, scaled.y) == (25, 12)  # floored
    assert (scaled.width, scaled.height) == (9, 6)  # ceiled
    assert scaled.score == 0.9


# --- with the real detector --------------------------------------------------

# Openly licensed photos of people from Wikimedia Commons, fetched at test
# time (the tests skip when offline):
# - a school class photo from Kerala: 45 people, faces 25-32 px wide at
#   960 px. "GVHSS Kalpakanchery 10th B Class Batch 2006-2007 Group Photo"
#   by Spworld2, CC0.
# - a group selfie: 9 people, faces 40-60 px, partly turned and overlapping.
#   "Wikimania 2014 volunteers take a selfie" by Sebastiaan ter Burg,
#   CC BY 2.0 (https://creativecommons.org/licenses/by/2.0/).
CLASS_PHOTO = (
    "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8a/"
    "GVHSS_Kalpakanchery_10th_B_Class_Batch_2006-2007_Group_Photo.jpg/"
    "960px-GVHSS_Kalpakanchery_10th_B_Class_Batch_2006-2007_Group_Photo.jpg"
)
GROUP_SELFIE = (
    "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/00/"
    "Wikimania_2014_volunteers_take_a_selfie.jpg/"
    "960px-Wikimania_2014_volunteers_take_a_selfie.jpg"
)


@pytest.fixture(scope="module")
def detector(model_dir: Path) -> YuNetFaceDetector:
    return YuNetFaceDetector.from_model_dir(model_dir)


@pytest.mark.models
def test_detector_satisfies_the_interface(detector: YuNetFaceDetector) -> None:
    assert isinstance(detector, FaceDetector)


@pytest.mark.models
def test_no_faces_in_scenes_without_people(detector: YuNetFaceDetector) -> None:
    assert detector.detect(scene(5)) == []
    assert detector.detect(Image.new("RGB", (64, 48), (90, 90, 90))) == []


@pytest.mark.models
@pytest.mark.parametrize(("url", "expected"), [(CLASS_PHOTO, 45), (GROUP_SELFIE, 9)])
def test_finds_the_faces_and_blur_removes_their_detail(
    detector: YuNetFaceDetector, url: str, expected: int
) -> None:
    photo = fetch_image(url)
    boxes = detector.detect(photo)
    # Allow a miss or two; a model or OpenCV upgrade shouldn't need a new number.
    assert expected - 2 <= len(boxes) <= expected + 1
    for box in boxes:
        assert box.x >= 0
        assert box.y >= 0
        assert box.x + box.width <= photo.width
        assert box.y + box.height <= photo.height
        assert box.score >= 0.6
    before = np.asarray(photo, dtype=np.float64)
    after = np.asarray(blur_regions(photo, boxes), dtype=np.float64)
    for box in boxes:
        region = (slice(box.y, box.y + box.height), slice(box.x, box.x + box.width))
        # Eyes, mouth and outline edges are what identify a face; less than
        # 5% of the fine detail may remain. (YuNet will still call some of
        # the blurred blobs faces: it detects head-shaped skin-coloured
        # regions, which says nothing about who they are.)
        assert detail(after[region]) < 0.05 * detail(before[region]), box


@pytest.mark.models
def test_small_faces_in_a_large_frame_are_found_by_the_fine_pass(
    detector: YuNetFaceDetector,
) -> None:
    photo = fetch_image(GROUP_SELFIE)
    # The selfie in the middle of a 3200 px frame: at the coarse 640 px scale
    # the faces shrink to 8-12 px, below what YuNet was trained on.
    canvas = Image.new("RGB", (3200, 2400), (120, 120, 120))
    canvas.paste(photo, (1100, 900))
    found = detector.detect(canvas)
    assert len(found) >= 7
    for box in found:
        assert 1100 <= box.x < 1100 + photo.width
        assert 900 <= box.y < 900 + photo.height
