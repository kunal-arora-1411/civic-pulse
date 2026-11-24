"""CPU latency of the AI worker's steps.

    uv run --extra ai python scripts/eval/bench_latency.py

Times image embedding at several batch sizes and thread counts, prompt
embedding for the default prompt set, face detection on a 1600 px display
copy and the perceptual hash. Synthetic images are fine here: ViT cost
doesn't depend on content, and YuNet's barely does.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.clip import ClipOnnxModel
from app.ai.faces import YuNetFaceDetector
from app.ai.phash import perceptual_hash
from app.ai.prompts import DEFAULT_PROMPTS
from scripts.eval.common import DEFAULT_MODEL_DIR, table


def photo(seed: int, size: tuple[int, int] = (1600, 1200)) -> Image.Image:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (size[1] // 16, size[0] // 16, 3), dtype=np.uint8)
    return Image.fromarray(small).resize(size, Image.Resampling.BICUBIC)


def timed(fn: Callable[[], object], repeat: int) -> float:
    fn()  # warm-up
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args(argv)
    print(f"{platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs")
    images = [photo(seed) for seed in range(16)]
    rows = []
    for threads in (1, 2, 4):
        model = ClipOnnxModel.from_model_dir(args.model_dir, threads=threads)
        for batch in (1, 4, 16):
            seconds = timed(lambda m=model, b=batch: m.embed_images(images[:b]), args.repeat)
            rows.append([threads, batch, round(seconds * 1000 / batch, 1)])
    print(table(["threads", "batch", "ms per image (incl. preprocessing)"], rows), "\n")

    model = ClipOnnxModel.from_model_dir(args.model_dir)
    prompts = [p for texts in DEFAULT_PROMPTS.values() for p in texts]
    text_ms = timed(lambda: model.embed_texts(prompts), args.repeat) * 1000
    detector = YuNetFaceDetector.from_model_dir(args.model_dir)
    face_ms = timed(lambda: detector.detect(images[0]), args.repeat) * 1000
    hash_ms = timed(lambda: perceptual_hash(images[0]), args.repeat) * 1000
    print(
        table(
            ["step (default threads)", "ms"],
            [
                [
                    f"embed all {len(prompts)} default prompts (once per prompt set)",
                    round(text_ms, 1),
                ],
                ["face detection, 1600x1200 (two passes)", round(face_ms, 1)],
                ["perceptual hash, 1600x1200", round(hash_ms, 1)],
            ],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
