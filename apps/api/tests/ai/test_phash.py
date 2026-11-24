from __future__ import annotations

import itertools

import numpy as np
import pytest
from PIL import Image, ImageEnhance

from app.ai.interfaces import perceptual_hash_distance
from app.ai.phash import dct2, from_signed64, perceptual_hash, to_signed64
from tests.ai.synthetic import recompress, scene

# The contract's same-photo boost fires at a Hamming distance of 6 or less.
SAME_PHOTO_MAX = 6


def test_dct_matches_the_textbook_definition() -> None:
    rng = np.random.default_rng(0)
    block = rng.normal(size=(8, 8))
    n = 8
    expected = np.zeros((n, n))
    for u, v in itertools.product(range(n), range(n)):
        cu = np.sqrt(1 / n) if u == 0 else np.sqrt(2 / n)
        cv = np.sqrt(1 / n) if v == 0 else np.sqrt(2 / n)
        total = 0.0
        for x, y in itertools.product(range(n), range(n)):
            total += (
                block[x, y]
                * np.cos((2 * x + 1) * u * np.pi / (2 * n))
                * np.cos((2 * y + 1) * v * np.pi / (2 * n))
            )
        expected[u, v] = cu * cv * total
    np.testing.assert_allclose(dct2(block), expected, atol=1e-10)


def test_dct_of_a_flat_block_is_all_dc() -> None:
    out = dct2(np.full((32, 32), 7.0))
    assert out[0, 0] == pytest.approx(7.0 * 32)
    out[0, 0] = 0
    np.testing.assert_allclose(out, 0, atol=1e-9)


def test_hash_is_a_deterministic_unsigned_64_bit_int() -> None:
    image = scene(1)
    value = perceptual_hash(image)
    assert 0 <= value < 2**64
    assert perceptual_hash(image.copy()) == value
    # About half the bits are set, by construction (median split).
    assert 24 <= value.bit_count() <= 40


@pytest.mark.parametrize("quality", [85, 60, 35])
def test_robust_to_jpeg_recompression(quality: int) -> None:
    for seed in range(5):
        image = scene(seed)
        distance = perceptual_hash_distance(
            perceptual_hash(image), perceptual_hash(recompress(image, quality))
        )
        assert distance <= SAME_PHOTO_MAX, (seed, distance)


@pytest.mark.parametrize("scale", [0.25, 0.5, 1.5])
def test_robust_to_resizing(scale: float) -> None:
    for seed in range(5):
        image = scene(seed)
        resized = image.resize(
            (round(image.width * scale), round(image.height * scale)), Image.Resampling.BILINEAR
        )
        distance = perceptual_hash_distance(perceptual_hash(image), perceptual_hash(resized))
        assert distance <= SAME_PHOTO_MAX, (seed, distance)


@pytest.mark.parametrize("factor", [0.85, 1.15])
def test_robust_to_mild_brightness_and_contrast_changes(factor: float) -> None:
    for seed in range(5):
        image = scene(seed)
        brighter = ImageEnhance.Brightness(image).enhance(factor)
        contrast = ImageEnhance.Contrast(image).enhance(factor)
        for variant in (brighter, contrast):
            distance = perceptual_hash_distance(perceptual_hash(image), perceptual_hash(variant))
            assert distance <= SAME_PHOTO_MAX, (seed, distance)


def test_different_images_are_far_apart() -> None:
    hashes = [perceptual_hash(scene(seed)) for seed in range(12)]
    distances = [perceptual_hash_distance(a, b) for a, b in itertools.combinations(hashes, 2)]
    # Independent images sit around 32 bits apart; none should look like a re-upload.
    assert min(distances) > 3 * SAME_PHOTO_MAX
    assert 24 <= float(np.mean(distances)) <= 40


@pytest.mark.parametrize("value", [0, 1, 2**63 - 1, 2**63, 2**64 - 1, 0xDEADBEEFCAFEF00D])
def test_signed_round_trip_fits_bigint(value: int) -> None:
    signed = to_signed64(value)
    assert -(2**63) <= signed < 2**63
    assert from_signed64(signed) == value


def test_signed_conversion_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="unsigned"):
        to_signed64(-1)
    with pytest.raises(ValueError, match="unsigned"):
        to_signed64(2**64)
    with pytest.raises(ValueError, match="signed"):
        from_signed64(2**63)
