"""Looking inside uploaded image bytes: type sniffing, decoding checks and
the EXIF fields we keep.

Nothing here trusts the declared Content-Type or file name. The type comes
from the magic bytes, and Pillow has to agree with it.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from PIL import ExifTags, Image, UnidentifiedImageError

# Pillow format name for each content type we accept.
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

_TAG_ORIENTATION = 0x0112
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_DATETIME = 0x0132
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_OFFSET_TIME_ORIGINAL = 0x9011
_GPS_LAT_REF, _GPS_LAT, _GPS_LNG_REF, _GPS_LNG = 1, 2, 3, 4
_ROTATED_ORIENTATIONS = {5, 6, 7, 8}  # EXIF orientations that swap width and height


class InvalidImage(Exception):
    """The bytes are not an acceptable image. `reason` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def sniff(data: bytes) -> str | None:
    """The content type from the file signature, or None if not one we accept."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True, slots=True)
class ExifData:
    captured_at: datetime | None = None
    private: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width: int  # as displayed, after EXIF orientation
    height: int
    exif: ExifData


def open_image(data: bytes, *, max_pixels: int) -> Image.Image:
    """Open with Pillow, refusing anything it would treat as a decompression bomb."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("image_too_large") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise InvalidImage("not_an_image") from None
    if image.width < 1 or image.height < 1:
        raise InvalidImage("not_an_image")
    if image.width * image.height > max_pixels:
        raise InvalidImage("image_too_large")
    return image


def inspect(data: bytes, *, declared_type: str, max_pixels: int, tz: str) -> ImageInfo:
    """Check that `data` really is an image of `declared_type` and read its EXIF.

    Raises InvalidImage with one of: content_type_mismatch, not_an_image,
    image_too_large.
    """
    sniffed = sniff(data)
    if sniffed is None:
        raise InvalidImage("not_an_image")
    if sniffed != declared_type:
        raise InvalidImage("content_type_mismatch")

    image = open_image(data, max_pixels=max_pixels)
    if image.format != FORMATS[declared_type]:
        raise InvalidImage("content_type_mismatch")
    exif = read_exif(image, tz=tz)
    width, height = image.size
    if exif.private.get("orientation") in _ROTATED_ORIENTATIONS:
        width, height = height, width

    # verify() walks the file structure (chunks, markers, checksums) without
    # decoding pixels. The worker decodes in full and fails the asset if the
    # pixel data turns out to be broken.
    try:
        open_image(data, max_pixels=max_pixels).verify()
    except InvalidImage:
        raise
    except Exception:
        raise InvalidImage("not_an_image") from None
    return ImageInfo(width=width, height=height, exif=exif)


def read_exif(image: Image.Image, *, tz: str) -> ExifData:
    """The metadata we keep privately: capture time, GPS, camera, orientation.

    Anything malformed is skipped rather than failing the upload; EXIF is
    optional and frequently wrong.
    """
    try:
        exif = image.getexif()
    except Exception:
        return ExifData()
    if not exif:
        return ExifData()

    private: dict[str, Any] = {}
    try:
        sub = exif.get_ifd(ExifTags.IFD.Exif)
    except Exception:
        sub = {}
    raw_time = sub.get(_TAG_DATETIME_ORIGINAL) or exif.get(_TAG_DATETIME)
    captured_at = _parse_exif_time(raw_time, sub.get(_TAG_OFFSET_TIME_ORIGINAL), tz)
    if captured_at is not None:
        private["captured_at"] = captured_at.isoformat()

    orientation = exif.get(_TAG_ORIENTATION)
    if isinstance(orientation, int) and 1 <= orientation <= 8:
        private["orientation"] = orientation
    for key, tag in (("make", _TAG_MAKE), ("model", _TAG_MODEL)):
        value = exif.get(tag)
        if isinstance(value, str) and value.strip():
            private[key] = value.strip().strip("\x00")[:100]

    gps = _read_gps(exif)
    if gps is not None:
        private["gps"] = gps
    return ExifData(captured_at=captured_at, private=private)


def _parse_exif_time(raw: Any, offset: Any, tz: str) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        naive = datetime.strptime(raw.strip().strip("\x00"), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007
    except ValueError:
        return None
    zone: Any = ZoneInfo(tz)
    if isinstance(offset, str):
        try:
            sign = -1 if offset.startswith("-") else 1
            hours, minutes = offset.lstrip("+-").split(":")
            zone = timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
        except ValueError:
            pass
    value = naive.replace(tzinfo=zone)
    # Unset camera clocks produce 1970 or far-future dates; keep only plausible ones.
    if value.year < 2000 or value > datetime.now(UTC) + timedelta(days=1):
        return None
    return value


def _read_gps(exif: Image.Exif) -> dict[str, float] | None:
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        lat = _dms(gps[_GPS_LAT], gps.get(_GPS_LAT_REF, "N"), "S")
        lng = _dms(gps[_GPS_LNG], gps.get(_GPS_LNG_REF, "E"), "W")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {"lat": round(lat, 7), "lng": round(lng, 7)}


def _dms(values: Any, ref: Any, negative_ref: str) -> float:
    degrees, minutes, seconds = (float(v) for v in values)
    decimal = degrees + minutes / 60 + seconds / 3600
    return -decimal if str(ref).upper().startswith(negative_ref) else decimal
