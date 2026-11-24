"""Face detection (YuNet) and blurring for the public copies of citizen photos.

YuNet (OpenCV Zoo, MIT licence) is a 230 kB ONNX model run through
``cv2.FaceDetectorYN``. It was trained on faces of roughly 10 to 300 pixels,
so one pass at a single scale misses either the close-up selfie or the
distant crowd. ``YuNetFaceDetector`` therefore runs a coarse pass with the
image shrunk to 640 px (big faces) and, for larger images, a second pass
at up to 1920 px (small faces), then merges the two with non-maximum
suppression.

Blurring errs on the side of hiding too much: each box is padded, then
pixelated to a handful of blocks across the face and smoothed, which
leaves no recoverable detail (a plain Gaussian blur of a small face can
be partly undone). Only the padded boxes change; the rest of the image is
left byte-for-byte as it was. Originals are never altered by callers
(Phase 2 contract, D.1 step 2); only ``display`` and ``thumb`` are.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageFilter

from app.ai.interfaces import Box
from app.ai.models_lock import model_path, verify_model_dir

if TYPE_CHECKING:
    import cv2

COARSE_SIDE = 640
FINE_SIDE = 1920
DEFAULT_SCORE_THRESHOLD = 0.6
DEFAULT_NMS_THRESHOLD = 0.3


def _iou(a: Box, b: Box) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2 = min(a.x + a.width, b.x + b.width)
    y2 = min(a.y + a.height, b.y + b.height)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def merge_boxes(boxes: Sequence[Box], iou_threshold: float = DEFAULT_NMS_THRESHOLD) -> list[Box]:
    """Greedy non-maximum suppression, highest score first."""
    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: -b.score):
        if all(_iou(box, other) <= iou_threshold for other in kept):
            kept.append(box)
    return kept


def scale_boxes(
    boxes: Sequence[Box], from_size: tuple[int, int], to_size: tuple[int, int]
) -> list[Box]:
    """Map boxes found on one rendition of an image onto another (e.g. display -> thumb)."""
    sx = to_size[0] / from_size[0]
    sy = to_size[1] / from_size[1]
    return [
        Box(
            x=math.floor(b.x * sx),
            y=math.floor(b.y * sy),
            width=math.ceil(b.width * sx),
            height=math.ceil(b.height * sy),
            score=b.score,
        )
        for b in boxes
    ]


class YuNetFaceDetector:
    """``FaceDetector`` backed by OpenCV's YuNet."""

    def __init__(
        self,
        model_file: Path,
        *,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    ) -> None:
        if not model_file.is_file():
            raise FileNotFoundError(f"model file not found: {model_file}")
        self._model_file = model_file
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        # cv2.FaceDetectorYN keeps per-input-size state, so each thread gets its own.
        self._local = threading.local()

    @classmethod
    def from_model_dir(
        cls, model_dir: Path, key: str = "yunet", **kwargs: Any
    ) -> YuNetFaceDetector:
        lock = verify_model_dir(model_dir, [key], check_hashes=False)
        return cls(model_path(model_dir, lock.get(key), "detector"), **kwargs)

    def _detector(self) -> cv2.FaceDetectorYN:
        detector = getattr(self._local, "detector", None)
        if detector is None:
            import cv2

            detector = cv2.FaceDetectorYN.create(
                str(self._model_file),
                "",
                (320, 320),
                self._score_threshold,
                self._nms_threshold,
                5000,
            )
            self._local.detector = detector
        return detector

    def _detect_at(self, rgb: Image.Image, longest: int) -> list[Box]:
        scale = min(1.0, longest / max(rgb.size))
        work = rgb
        if scale < 1.0:
            work = rgb.resize(
                (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                Image.Resampling.BILINEAR,
            )
        bgr = np.ascontiguousarray(np.asarray(work)[:, :, ::-1])
        detector = self._detector()
        detector.setInputSize((work.width, work.height))
        _, faces = detector.detect(bgr)
        if faces is None:
            return []
        boxes = []
        for face in faces:
            x, y, w, h = (float(v) / scale for v in face[:4])
            x0, y0 = max(0, math.floor(x)), max(0, math.floor(y))
            x1 = min(rgb.width, math.ceil(x + w))
            y1 = min(rgb.height, math.ceil(y + h))
            if x1 > x0 and y1 > y0:
                boxes.append(Box(x0, y0, x1 - x0, y1 - y0, float(face[-1])))
        return boxes

    def detect(self, image: Image.Image) -> list[Box]:
        rgb = image.convert("RGB")
        boxes = self._detect_at(rgb, COARSE_SIDE)
        if max(rgb.size) > COARSE_SIDE * 1.5:
            boxes += self._detect_at(rgb, FINE_SIDE)
        return merge_boxes(boxes, self._nms_threshold)


def _padded(box: Box, size: tuple[int, int], padding: float, min_padding: int) -> tuple[int, ...]:
    pad_x = max(min_padding, round(box.width * padding))
    pad_y = max(min_padding, round(box.height * padding))
    x0 = max(0, box.x - pad_x)
    y0 = max(0, box.y - pad_y)
    x1 = min(size[0], box.x + box.width + pad_x)
    y1 = min(size[1], box.y + box.height + pad_y)
    return x0, y0, x1, y1


def blur_regions(
    image: Image.Image,
    boxes: Sequence[Box],
    *,
    padding: float = 0.25,
    min_padding: int = 4,
    blocks: int = 5,
) -> Image.Image:
    """Return a copy of ``image`` with every box (plus padding) made unrecognisable.

    Each padded region is pixelated so the face spans about ``blocks``
    cells (never cells smaller than 3 px), then Gaussian-smoothed with a
    radius of one cell so no blocky edges hint at features. Tiny faces
    still get at least a 3 px cell and ``min_padding`` pixels of margin.
    """
    # Palette and other exotic modes can't be box-resampled; display copies are RGB anyway.
    out = image.copy() if image.mode in ("RGB", "RGBA", "L") else image.convert("RGB")
    if not boxes:
        return out
    for box in boxes:
        x0, y0, x1, y1 = _padded(box, out.size, padding, min_padding)
        if x1 <= x0 or y1 <= y0:
            continue
        region = out.crop((x0, y0, x1, y1))
        cell = max(3, math.ceil(max(box.width, box.height) / blocks))
        small = region.resize(
            (max(1, math.ceil(region.width / cell)), max(1, math.ceil(region.height / cell))),
            Image.Resampling.BOX,
        )
        mosaic = small.resize(region.size, Image.Resampling.NEAREST)
        out.paste(mosaic.filter(ImageFilter.GaussianBlur(cell)), (x0, y0))
    return out
