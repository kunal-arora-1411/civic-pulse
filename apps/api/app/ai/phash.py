"""64-bit DCT perceptual hash (pHash), in numpy only.

The classic recipe: greyscale, shrink to 32x32, take the 2-D DCT, keep the
8x8 block of lowest frequencies and set one bit per coefficient that is
above the block's median. Low frequencies describe the overall layout of
light and dark, so the hash survives recompression, rescaling and small
brightness or contrast changes, while different scenes land far apart.
Two hashes are compared with ``interfaces.perceptual_hash_distance``.

Hashes are unsigned 64-bit integers. Postgres ``bigint`` is signed, so
convert with ``to_signed64`` before storing and ``from_signed64`` after
loading: ``int.bit_count`` on a negative Python int counts the bits of its
absolute value, which would make Hamming distances wrong.
"""

from __future__ import annotations

from functools import cache

import numpy as np
from numpy.typing import NDArray
from PIL import Image

HASH_SIZE = 8
"""Side of the low-frequency block; the hash has ``HASH_SIZE ** 2`` bits."""
_SAMPLE_SIZE = 32
"""Side of the greyscale thumbnail the DCT is taken over."""

_UINT64 = 1 << 64
_INT64_MAX = (1 << 63) - 1


@cache
def _dct_matrix(n: int) -> NDArray[np.float64]:
    """Orthonormal DCT-II basis: ``_dct_matrix(n) @ x`` is ``scipy.fft.dct(x, norm="ortho")``."""
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    basis = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    basis[0, :] = np.sqrt(1.0 / n)
    return basis


def dct2(block: NDArray[np.floating]) -> NDArray[np.float64]:
    """2-D orthonormal DCT-II of a square block."""
    c = _dct_matrix(block.shape[0])
    return c @ block.astype(np.float64) @ c.T


def perceptual_hash(image: Image.Image) -> int:
    """Return the 64-bit pHash of ``image`` as an unsigned int in ``[0, 2**64)``.

    Pass an upright image (EXIF orientation already applied, as it is for
    the processed ``display`` variant); a rotated copy hashes differently.
    """
    grey = image.convert("L").resize((_SAMPLE_SIZE, _SAMPLE_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(grey, dtype=np.float64)
    low = dct2(pixels)[:HASH_SIZE, :HASH_SIZE]
    bits = (low > np.median(low)).ravel()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def to_signed64(value: int) -> int:
    """Map an unsigned 64-bit hash onto Postgres ``bigint`` range (two's complement)."""
    if not 0 <= value < _UINT64:
        raise ValueError("hash must be an unsigned 64-bit integer")
    return value - _UINT64 if value > _INT64_MAX else value


def from_signed64(value: int) -> int:
    """Inverse of ``to_signed64``."""
    if not -(1 << 63) <= value <= _INT64_MAX:
        raise ValueError("value must fit in a signed 64-bit integer")
    return value + _UINT64 if value < 0 else value
