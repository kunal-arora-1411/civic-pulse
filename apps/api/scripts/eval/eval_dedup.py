"""Visual duplicate signal: how well embeddings and pHash separate same-scene pairs.

    uv run --extra ai python scripts/eval/eval_dedup.py

Pairs, built from the civic classes of the manifest (not_civic is left out):

* **positive**: two independently augmented views of the same photo
  (crop to 75-95% per side, rotate within +-15 degrees, brightness and
  contrast 0.7-1.3, rescale to 40-100%, JPEG quality 30-90). A stand-in for
  two citizens photographing the same spot; real re-shoots differ more
  (angle, time of day, weather), so treat recall here as an upper bound.
* **re-upload**: the photo against a recompressed, rescaled copy only, to
  check the pHash same-photo boost.
* **negative**: every pair of different photos of the same category. These
  are the hard case for the matcher: two different potholes. Commons photos
  come from different places, while real nearby candidates may share a
  street, so the false-merge rate here is a lower bound.

The visual floor is chosen on the calib split (lowest cosine whose
false-merge rate is at most ``--max-fmr``) and reported on test. The
contract's auto-link rule also needs score >= 0.85; the report shows what
visual similarity that implies for a given distance and age.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.interfaces import perceptual_hash_distance
from app.ai.phash import perceptual_hash
from scripts.eval.common import DEFAULT_MODEL_DIR, load_model, table
from scripts.eval.manifest import (
    DEFAULT_CACHE,
    DEFAULT_MANIFEST,
    Item,
    load_image,
    read_manifest,
)

CIVIC = ("pothole", "waste", "waterlogging", "streetlight", "drainage")
FLOORS = [round(t, 2) for t in np.arange(0.60, 0.99, 0.02)]
CONTRACT_FLOOR = 0.80
SAME_PHOTO_MAX = 6
WEIGHTS = {"geo": 0.40, "visual": 0.40, "category": 0.10, "time": 0.10}
AUTO_SCORE = 0.85


def jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def augment(image: Image.Image, rng: np.random.Generator) -> Image.Image:
    w, h = image.size
    fill = tuple(int(c) for c in np.asarray(image).reshape(-1, 3).mean(axis=0))
    out = image.rotate(
        float(rng.uniform(-15, 15)), resample=Image.Resampling.BICUBIC, fillcolor=fill
    )
    cw, ch = int(w * rng.uniform(0.75, 0.95)), int(h * rng.uniform(0.75, 0.95))
    x0, y0 = int(rng.integers(0, w - cw + 1)), int(rng.integers(0, h - ch + 1))
    out = out.crop((x0, y0, x0 + cw, y0 + ch))
    out = ImageEnhance.Brightness(out).enhance(float(rng.uniform(0.7, 1.3)))
    out = ImageEnhance.Contrast(out).enhance(float(rng.uniform(0.7, 1.3)))
    scale = float(rng.uniform(0.4, 1.0))
    out = out.resize(
        (max(32, int(cw * scale)), max(32, int(ch * scale))), Image.Resampling.BILINEAR
    )
    return jpeg(out, int(rng.integers(30, 91)))


def reupload(image: Image.Image, rng: np.random.Generator) -> Image.Image:
    scale = float(rng.uniform(0.5, 1.0))
    out = image.resize(
        (int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS
    )
    return jpeg(out, int(rng.integers(50, 91)))


def roc_auc(pos: NDArray, neg: NDArray) -> float:
    """Probability a random positive outranks a random negative (ties count half)."""
    scores = np.concatenate([pos, neg])
    ranks = scores.argsort().argsort().astype(float) + 1
    # average ranks for ties
    for value in np.unique(scores):
        mask = scores == value
        if mask.sum() > 1:
            ranks[mask] = ranks[mask].mean()
    r_pos = ranks[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def average_precision(pos: NDArray, neg: NDArray) -> float:
    scores = np.concatenate([pos, neg])
    labels = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    order = np.argsort(-scores, kind="stable")
    labels = labels[order]
    hits = np.cumsum(labels)
    precision = hits / np.arange(1, len(labels) + 1)
    return float((precision * labels).sum() / labels.sum())


def at_floor(pos: NDArray, neg: NDArray, floor: float) -> dict[str, float]:
    tp, fp = int((pos >= floor).sum()), int((neg >= floor).sum())
    return {
        "floor": floor,
        "recall": tp / len(pos),
        "false_merge_rate": fp / len(neg),
        "precision": tp / (tp + fp) if tp + fp else 1.0,
    }


def choose_floor(pos: NDArray, neg: NDArray, max_fmr: float) -> float:
    for floor in FLOORS:
        if at_floor(pos, neg, floor)["false_merge_rate"] <= max_fmr:
            return floor
    return FLOORS[-1]


def required_visual(distance_frac: float, age_frac: float) -> float:
    """Visual similarity needed for score >= AUTO_SCORE, same category."""
    geo = float(np.exp(-distance_frac))
    time = float(np.exp(-age_frac))
    rest = WEIGHTS["geo"] * geo + WEIGHTS["category"] * 1.0 + WEIGHTS["time"] * time
    return (AUTO_SCORE - rest) / WEIGHTS["visual"]


def build_pairs(
    model, items: list[Item], manifest_dir: Path, cache: Path, seed: int
) -> dict[str, Any]:
    images = [load_image(i, manifest_dir, cache) for i in items]
    rng = np.random.default_rng(seed)
    view_a = [augment(im, rng) for im in images]
    view_b = [augment(im, rng) for im in images]
    copies = [reupload(im, rng) for im in images]
    emb = {
        name: model.embed_images(views)
        for name, views in (("orig", images), ("a", view_a), ("b", view_b), ("copy", copies))
    }
    hashes = {
        name: [perceptual_hash(v) for v in views]
        for name, views in (("orig", images), ("a", view_a), ("b", view_b), ("copy", copies))
    }
    pos_cos = np.einsum("ij,ij->i", emb["a"], emb["b"]).clip(0, 1)
    copy_cos = np.einsum("ij,ij->i", emb["orig"], emb["copy"]).clip(0, 1)
    pos_ham = np.array(
        [perceptual_hash_distance(x, y) for x, y in zip(hashes["a"], hashes["b"], strict=True)]
    )
    copy_ham = np.array(
        [
            perceptual_hash_distance(x, y)
            for x, y in zip(hashes["orig"], hashes["copy"], strict=True)
        ]
    )
    neg_cos, neg_ham = [], []
    for label in CIVIC:
        idx = [n for n, item in enumerate(items) if item.label == label]
        for i, j in itertools.combinations(idx, 2):
            neg_cos.append(float(emb["orig"][i] @ emb["orig"][j]))
            neg_ham.append(perceptual_hash_distance(hashes["orig"][i], hashes["orig"][j]))
    return {
        "pos_cos": pos_cos,
        "copy_cos": copy_cos,
        "neg_cos": np.clip(np.array(neg_cos), 0, 1),
        "pos_ham": pos_ham,
        "copy_ham": copy_ham,
        "neg_ham": np.array(neg_ham),
    }


def describe(values: NDArray) -> list[float]:
    return [float(np.percentile(values, p)) for p in (1, 5, 25, 50, 75, 95, 99)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--max-fmr", type=float, default=0.01, help="false merges allowed (calib)")
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    items = [i for i in read_manifest(args.manifest) if i.label in CIVIC and i.split]
    model = load_model(args.model_dir)
    results: dict[str, Any] = {"model_id": model.model_id}
    pairs = {}
    for split in ("calib", "test"):
        subset = [i for i in items if i.split == split]
        pairs[split] = build_pairs(model, subset, args.manifest.parent, args.cache, args.seed)
    floor = choose_floor(pairs["calib"]["pos_cos"], pairs["calib"]["neg_cos"], args.max_fmr)
    t = pairs["test"]
    results.update(
        {
            "chosen_floor": floor,
            "max_fmr": args.max_fmr,
            "test_pairs": {"positive": len(t["pos_cos"]), "negative": len(t["neg_cos"])},
            "calib_pairs": {
                "positive": len(pairs["calib"]["pos_cos"]),
                "negative": len(pairs["calib"]["neg_cos"]),
            },
            "test_roc_auc": roc_auc(t["pos_cos"], t["neg_cos"]),
            "test_average_precision": average_precision(t["pos_cos"], t["neg_cos"]),
            "test_at_contract_floor": at_floor(t["pos_cos"], t["neg_cos"], CONTRACT_FLOOR),
            "test_at_chosen_floor": at_floor(t["pos_cos"], t["neg_cos"], floor),
            "calib_at_chosen_floor": at_floor(
                pairs["calib"]["pos_cos"], pairs["calib"]["neg_cos"], floor
            ),
            "test_cosine_percentiles": {
                "positive": describe(t["pos_cos"]),
                "re_upload": describe(t["copy_cos"]),
                "negative": describe(t["neg_cos"]),
            },
            "test_phash": {
                "re_upload_boost_rate": float((t["copy_ham"] <= SAME_PHOTO_MAX).mean()),
                "augmented_boost_rate": float((t["pos_ham"] <= SAME_PHOTO_MAX).mean()),
                "negative_boost_rate": float((t["neg_ham"] <= SAME_PHOTO_MAX).mean()),
                "negative_min_distance": int(t["neg_ham"].min()),
            },
            "sweep": [
                {
                    "calib": at_floor(pairs["calib"]["pos_cos"], pairs["calib"]["neg_cos"], f),
                    "test": at_floor(t["pos_cos"], t["neg_cos"], f),
                }
                for f in FLOORS
            ],
        }
    )

    print(f"model {model.model_id}")
    print(
        f"test pairs: {len(t['pos_cos'])} positive, {len(t['neg_cos'])} negative; "
        f"calib: {results['calib_pairs']['positive']} / {results['calib_pairs']['negative']}"
    )
    print(
        f"ROC AUC {results['test_roc_auc']:.3f}, "
        f"average precision {results['test_average_precision']:.3f}"
    )
    print(f"visual floor chosen on calib (false merges <= {args.max_fmr:.1%}): {floor:.2f}\n")
    pct = results["test_cosine_percentiles"]
    print(
        table(
            ["cosine (test)", "p1", "p5", "p25", "p50", "p75", "p95", "p99"],
            [[name, *vals] for name, vals in pct.items()],
        ),
        "\n",
    )
    print(
        table(
            [
                "visual floor",
                "calib recall",
                "calib false-merge",
                "test recall",
                "test false-merge",
                "test precision",
            ],
            [
                [
                    s["test"]["floor"],
                    s["calib"]["recall"],
                    s["calib"]["false_merge_rate"],
                    s["test"]["recall"],
                    s["test"]["false_merge_rate"],
                    s["test"]["precision"],
                ]
                for s in results["sweep"]
            ],
        ),
        "\n",
    )
    ph = results["test_phash"]
    print(
        f"pHash <= {SAME_PHOTO_MAX}: re-uploads {ph['re_upload_boost_rate']:.3f}, "
        f"augmented views {ph['augmented_boost_rate']:.3f}, "
        f"different photos {ph['negative_boost_rate']:.4f} "
        f"(closest different pair: {ph['negative_min_distance']} bits)\n"
    )
    rows = []
    for distance_frac in (0.0, 0.25, 0.5, 1.0):
        row: list[object] = [f"{distance_frac:.2f} x radius"]
        for age_frac in (0.0, 0.1, 0.5):
            need = required_visual(distance_frac, age_frac)
            if need > 1:
                row.append("never")
            else:
                need = max(need, floor)
                recall = at_floor(t["pos_cos"], t["neg_cos"], need)["recall"]
                row.append(f"{need:.2f} (recall {recall:.2f})")
        rows.append(row)
    print(
        "visual similarity needed for auto-link (score >= 0.85 and visual >= floor), same category:"
    )
    print(table(["distance", "age 0", "age 0.1 x window", "age 0.5 x window"], rows))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
