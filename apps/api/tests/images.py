"""Small generated images for media tests."""

from __future__ import annotations

import hashlib
import io
from fractions import Fraction

from PIL import ExifTags, Image, TiffImagePlugin

CAPTURED = "2026:11:20 09:30:00"  # local time, no offset tag
GPS = {"lat": 12.975, "lng": 77.5925}


def _rational(value: float) -> TiffImagePlugin.IFDRational:
    return TiffImagePlugin.IFDRational(Fraction(value).limit_denominator(10_000))


def _dms(decimal: float) -> tuple[TiffImagePlugin.IFDRational, ...]:
    degrees = int(decimal)
    minutes_full = (decimal - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    return (_rational(degrees), _rational(minutes), _rational(round(seconds, 4)))


def exif_bytes(*, orientation: int = 1, with_gps: bool = True) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SyntheticCam"
    exif[0x0110] = "Test Model 1"
    exif[0x0112] = orientation
    exif[ExifTags.IFD.Exif] = {0x9003: CAPTURED}
    if with_gps:
        exif[ExifTags.IFD.GPSInfo] = {
            1: "N",
            2: _dms(GPS["lat"]),
            3: "E",
            4: _dms(GPS["lng"]),
        }
    return exif.tobytes()


def jpeg(
    size: tuple[int, int] = (640, 480),
    *,
    exif: bool = True,
    orientation: int = 1,
    color: tuple[int, int, int] = (200, 80, 40),
) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    if exif:
        image.save(buffer, "JPEG", quality=85, exif=exif_bytes(orientation=orientation))
    else:
        image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def png(size: tuple[int, int] = (320, 240), *, mode: str = "RGBA") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (10, 120, 200, 180) if mode == "RGBA" else 1).save(buffer, "PNG")
    return buffer.getvalue()


def webp(size: tuple[int, int] = (320, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 160, 60)).save(buffer, "WEBP", exif=exif_bytes())
    return buffer.getvalue()


def bomb() -> bytes:
    """A tiny PNG that would decode to 100 megapixels."""
    buffer = io.BytesIO()
    Image.new("1", (10_000, 10_000), 0).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
