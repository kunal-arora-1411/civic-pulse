from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.ai.clip import CLIP_MEAN, CLIP_STD, ClipConfig, ClipOnnxModel, l2_normalize, preprocess
from app.ai.interfaces import VisionModel
from tests.ai.conftest import fetch_image
from tests.ai.synthetic import scene


def pattern(width: int, height: int) -> Image.Image:
    """High-frequency test card, so resampling differences would show."""
    ys, xs = np.mgrid[0:height, 0:width]
    r = (xs * 7 + ys * 3) % 256
    g = (xs * ys // 5) % 256
    b = ((xs - ys) * 11) % 256
    return Image.fromarray(np.stack([r, g, b], axis=-1).astype(np.uint8))


# Produced by transformers 5.24 CLIPImageProcessor (PIL backend) loaded from
# the pinned Xenova/clip-vit-base-patch32 preprocessor_config.json, on the
# pattern above. Our preprocess() matched it bit for bit on these and on
# real photos when this was written; the fingerprints keep it that way
# without needing transformers in the test environment.
REFERENCE = {
    (333, 500): (
        [0.068773, 0.143694, 0.332638],
        [0.645675, 0.739192, 0.254628, 1.71136, 0.604123, 0.908751],
    ),
    (1001, 300): (
        [0.070221, 0.146688, 0.333482],
        [0.339108, 0.288959, -1.352239, -0.901758, -0.986701, 1.619755],
    ),
    (150, 100): (
        [0.062871, 0.08717, 0.32639],
        [0.733265, -0.326359, -1.181598, 0.295313, 0.213921, -0.214634],
    ),
    (224, 224): (
        [0.066504, 0.093523, 0.331823],
        [-1.792263, 0.409022, -1.323799, 0.864651, -1.241833, -0.996737],
    ),
}
SAMPLE_POSITIONS = [(0, 0, 0), (1, 10, 200), (2, 111, 112), (0, 223, 223), (1, 57, 3), (2, 180, 90)]
REFERENCE_IDS = [
    [49406, 320, 1125, 539, 320, 628, 31029, 525, 550, 3606, 1759, 49407],
    [49406, 13760, 23768, 525, 518, 2012, 256, 49407, 49407, 49407, 49407, 49407],
]


@pytest.mark.parametrize("size", list(REFERENCE))
def test_preprocess_matches_the_reference_processor(size: tuple[int, int]) -> None:
    batch = preprocess([pattern(*size)], ClipConfig())
    assert batch.shape == (1, 3, 224, 224)
    assert batch.dtype == np.float32
    means, samples = REFERENCE[size]
    np.testing.assert_allclose([batch[0, c].mean() for c in range(3)], means, atol=1e-5)
    got = [batch[0, c, y, x] for c, y, x in SAMPLE_POSITIONS]
    np.testing.assert_allclose(got, samples, atol=1e-5)


def test_preprocess_normalises_with_the_clip_constants() -> None:
    grey = Image.new("RGB", (300, 200), (128, 128, 128))
    batch = preprocess([grey, grey.convert("L"), grey.convert("RGBA")], ClipConfig())
    expected = (128 / 255 - np.asarray(CLIP_MEAN)) / np.asarray(CLIP_STD)
    for item in batch:
        np.testing.assert_allclose(item.reshape(3, -1).mean(axis=1), expected, atol=1e-6)


def test_preprocess_squash_mode_keeps_the_whole_frame() -> None:
    # Left half black, right half white: a centre crop of a wide image would
    # still be split, but squashing must keep the exact halves.
    image = Image.new("RGB", (800, 200), (0, 0, 0))
    image.paste((255, 255, 255), (400, 0, 800, 200))
    batch = preprocess([image], ClipConfig(resize="squash", mean=(0, 0, 0), std=(1, 1, 1)))
    assert batch.shape == (1, 3, 224, 224)
    assert batch[0, :, :, :100].max() < 0.01
    assert batch[0, :, :, 124:].min() > 0.99


def test_l2_normalize_handles_zero_vectors() -> None:
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.testing.assert_allclose(out, [[0.6, 0.8], [0.0, 0.0]])
    assert out.dtype == np.float32


def test_missing_files_fail_at_construction(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ClipOnnxModel(
            model_id="x",
            vision_path=tmp_path / "v.onnx",
            text_path=tmp_path / "t.onnx",
            tokenizer_path=tmp_path / "tok.json",
        )


# --- with the real weights -------------------------------------------------


@pytest.fixture(scope="module")
def clip(model_dir: Path) -> ClipOnnxModel:
    return ClipOnnxModel.from_model_dir(model_dir)


@pytest.mark.models
def test_model_satisfies_the_interface(clip: ClipOnnxModel) -> None:
    assert isinstance(clip, VisionModel)
    assert clip.model_id == "clip-vit-b32@onnx-1"
    assert clip.dim == 512


@pytest.mark.models
def test_tokenizer_matches_the_reference(clip: ClipOnnxModel) -> None:
    texts = ["a photo of a pothole on an Indian road", "Garbage   dumped  on the STREET!"]
    ids = clip.tokenize(texts)
    assert ids.tolist() == REFERENCE_IDS


@pytest.mark.models
def test_long_prompts_are_truncated_but_keep_the_end_token(clip: ClipOnnxModel) -> None:
    ids = clip.tokenize(["pothole " * 200])
    assert ids.shape == (1, 77)
    assert ids[0, 0] == 49406
    assert ids[0, -1] == 49407


@pytest.mark.models
def test_embeddings_are_unit_vectors_and_batch_independent(clip: ClipOnnxModel) -> None:
    images = [scene(seed) for seed in range(5)]
    together = clip.embed_images(images)
    assert together.shape == (5, 512)
    assert together.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(together, axis=1), 1.0, atol=1e-5)
    alone = np.concatenate([clip.embed_images([image]) for image in images])
    np.testing.assert_allclose(together, alone, atol=1e-4)
    texts = clip.embed_texts(["a pothole", "a pile of garbage", "a street light"])
    assert texts.shape == (3, 512)
    np.testing.assert_allclose(np.linalg.norm(texts, axis=1), 1.0, atol=1e-5)
    assert clip.embed_images([]).shape == (0, 512)
    assert clip.embed_texts([]).shape == (0, 512)


@pytest.mark.models
def test_zero_shot_matches_the_model_card_example(clip: ClipOnnxModel) -> None:
    """The transformers.js example on the Xenova model card.

    The card reports tiger 0.99939, horse 0.00035, dog 0.00026, computed
    with the combined graph in the browser runtime (its default quantised
    weights). The fp32 towers here give 0.99975 / 0.00010 / 0.00014; the
    int8 towers 0.99887 / 0.00068 / 0.00045. The same ranking and
    magnitude is what we can fairly assert.
    """
    tiger = fetch_image(
        "https://huggingface.co/datasets/Xenova/transformers.js-docs/resolve/main/tiger.jpg"
    )
    labels = ["tiger", "horse", "dog"]
    texts = clip.embed_texts([f"This is a photo of {label}" for label in labels])
    logits = clip.config.logit_scale * (clip.embed_images([tiger]) @ texts.T)[0]
    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    assert probs[0] > 0.999
    assert probs[1] < 0.001
    assert probs[2] < 0.001


@pytest.mark.models
def test_near_duplicates_score_higher_than_unrelated_images(clip: ClipOnnxModel) -> None:
    base = scene(3)
    shifted = base.crop((30, 20, base.width - 10, base.height - 30)).rotate(8)
    other = scene(11)
    a, b, c = clip.embed_images([base, shifted, other])
    assert float(a @ b) > float(a @ c)


@pytest.mark.models
def test_latency_is_reasonable_on_cpu(clip: ClipOnnxModel) -> None:
    clip.warm_up()
    images = [scene(seed) for seed in range(8)]
    start = time.perf_counter()
    clip.embed_images(images)
    per_image = (time.perf_counter() - start) / len(images)
    # Generous bound: catches an accidental fp64 path or a thread misconfiguration.
    assert per_image < 1.0, f"{per_image * 1000:.0f} ms per image"
