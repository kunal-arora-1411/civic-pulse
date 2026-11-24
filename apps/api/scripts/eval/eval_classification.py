"""Zero-shot classification on the held-out evaluation set.

    uv run --extra ai python scripts/eval/eval_classification.py
    uv run --extra ai python scripts/eval/eval_classification.py --model-dir <candidate dir>
    uv run --extra ai python scripts/eval/eval_classification.py --tune   # calib split only

Method (so the numbers aren't optimistic):

* The manifest fixes a calib/test split, stratified by label and grouped
  by photographer so that a series of one scene never sits on both sides.
  The temperature and the confidence threshold are fitted on ``calib``
  only, and every headline number is computed on ``test``.
* The temperature minimises log-loss on calib. That is only fair when the
  prompts were not themselves chosen on calib; for searched prompts pass
  ``--tuning`` with the cross-fitted values from ``tune_prompts.py``.
* The threshold is the lowest one whose accepted suggestions (top
  confidence >= threshold; below it the API sets ``needs_manual``) are at
  least ``--target`` accurate on calib. 95% by default: a wrong
  pre-selection costs the citizen a correction and, if missed, becomes a
  wrong label.
* As a variance check the roles are swapped (fit on test, report on
  calib), and test accuracy gets a bootstrap 95% interval.

Each image is classified on its own; mean-pooling several photos of one
report can't be measured with this set.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.prompts import DEFAULT_PROMPTS, NOT_CIVIC
from app.ai.zero_shot import PromptZeroShotClassifier, fit_temperature, softmax
from scripts.eval.common import DEFAULT_MODEL_DIR, embed_items, load_model, table
from scripts.eval.manifest import DEFAULT_CACHE, DEFAULT_MANIFEST, LABELS, read_manifest

THRESHOLDS = [round(t, 2) for t in np.arange(0.20, 0.96, 0.05)]
CLIP_TEMPERATURE = 0.01


def per_class(y_true: NDArray, y_pred: NDArray, k: int) -> list[dict[str, float]]:
    out = []
    for c in range(k):
        tp = int(np.sum((y_pred == c) & (y_true == c)))
        fp = int(np.sum((y_pred == c) & (y_true != c)))
        fn = int(np.sum((y_pred != c) & (y_true == c)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out.append({"precision": precision, "recall": recall, "f1": f1, "support": tp + fn})
    return out


def confusion(y_true: NDArray, y_pred: NDArray, k: int) -> NDArray[np.int64]:
    matrix = np.zeros((k, k), dtype=np.int64)
    for t, p in zip(y_true, y_pred, strict=True):
        matrix[t, p] += 1
    return matrix


def ece(probs: NDArray, y_true: NDArray, bins: int = 10) -> float:
    """Expected calibration error of the top prediction, equal-width bins."""
    conf = probs.max(axis=1)
    correct = probs.argmax(axis=1) == y_true
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in itertools.pairwise(edges):
        mask = (conf > lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(correct[mask].mean() - conf[mask].mean())
    return float(total)


def nll(probs: NDArray, y_true: NDArray) -> float:
    return float(-np.mean(np.log(np.maximum(probs[np.arange(len(y_true)), y_true], 1e-12))))


def sweep(probs: NDArray, y_true: NDArray) -> list[dict[str, float]]:
    conf = probs.max(axis=1)
    correct = probs.argmax(axis=1) == y_true
    rows = []
    for t in THRESHOLDS:
        accepted = conf >= t
        rows.append(
            {
                "threshold": t,
                "coverage": float(accepted.mean()),
                "accuracy_accepted": float(correct[accepted].mean()) if accepted.any() else 0.0,
                "needs_manual": float((~accepted).mean()),
            }
        )
    return rows


def choose_threshold(probs: NDArray, y_true: NDArray, target: float) -> float:
    for row in sweep(probs, y_true):
        if row["accuracy_accepted"] >= target and row["coverage"] > 0:
            return row["threshold"]
    return THRESHOLDS[-1]


def summary(probs: NDArray, y_true: NDArray, threshold: float, k: int) -> dict[str, Any]:
    pred = probs.argmax(axis=1)
    top3 = np.argsort(-probs, axis=1)[:, :3]
    conf = probs.max(axis=1)
    accepted = conf >= threshold
    stats = per_class(y_true, pred, k)
    return {
        "n": len(y_true),
        "accuracy": float((pred == y_true).mean()),
        "macro_f1": float(np.mean([s["f1"] for s in stats])),
        "top3_accuracy": float(np.mean([y in row for y, row in zip(y_true, top3, strict=True)])),
        "nll": nll(probs, y_true),
        "ece": ece(probs, y_true),
        "threshold": threshold,
        "coverage": float(accepted.mean()),
        "accuracy_accepted": float((pred == y_true)[accepted].mean()) if accepted.any() else 0.0,
        "per_class": stats,
        "confusion": confusion(y_true, pred, k).tolist(),
    }


def bootstrap_accuracy(correct: NDArray, rounds: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(correct)
    means = [correct[rng.integers(0, n, n)].mean() for _ in range(rounds)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def evaluate(
    sims: NDArray,
    y: NDArray,
    fit_mask: NDArray,
    eval_mask: NDArray,
    target: float,
    k: int,
    fixed: tuple[float, float] | None = None,
):
    """Fit temperature and threshold on ``fit_mask`` (or use ``fixed``), report on ``eval_mask``."""
    if fixed is None:
        temperature = fit_temperature(sims[fit_mask], y[fit_mask])
        fit_probs = softmax(sims[fit_mask] / temperature)
        threshold = choose_threshold(fit_probs, y[fit_mask], target)
    else:
        temperature, threshold = fixed
        fit_probs = softmax(sims[fit_mask] / temperature)
    eval_probs = softmax(sims[eval_mask] / temperature)
    result = summary(eval_probs, y[eval_mask], threshold, k)
    result["temperature"] = temperature
    result["sweep_fit"] = sweep(fit_probs, y[fit_mask])
    result["sweep_eval"] = sweep(eval_probs, y[eval_mask])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--prompts", type=Path, help="JSON prompt set instead of DEFAULT_PROMPTS")
    parser.add_argument(
        "--target", type=float, default=0.95, help="accuracy of accepted suggestions"
    )
    parser.add_argument("--tune", action="store_true", help="report on calib only (prompt work)")
    parser.add_argument("--json", type=Path, help="write the full results here")
    parser.add_argument(
        "--tuning",
        type=Path,
        help="tune_prompts.py output: use its cross-fitted temperature and threshold",
    )
    args = parser.parse_args(argv)

    items = [i for i in read_manifest(args.manifest) if i.split]
    prompts = (
        json.loads(args.prompts.read_text(encoding="utf-8")) if args.prompts else DEFAULT_PROMPTS
    )
    model = load_model(args.model_dir)
    embeddings = embed_items(model, items, args.manifest.parent, args.cache)
    codes, classes = PromptZeroShotClassifier(model).class_matrix(prompts)
    if set(codes) != set(LABELS):
        raise SystemExit(f"prompt codes {codes} don't match the labels {LABELS}")
    k = len(codes)
    sims = embeddings @ classes.T
    y = np.array([codes.index(i.label) for i in items])
    calib = np.array([i.split == "calib" for i in items])
    test = ~calib

    if args.tune:
        temperature = fit_temperature(sims[calib], y[calib])
        res = summary(softmax(sims[calib] / temperature), y[calib], 0.0, k)
        print(f"calib only, n={res['n']}, T={temperature:.4f}")
        print(
            f"accuracy {res['accuracy']:.3f}  macro-F1 {res['macro_f1']:.3f}  nll {res['nll']:.3f}"
        )
        rows = [
            [c, s["precision"], s["recall"], s["f1"], s["support"]]
            for c, s in zip(codes, res["per_class"], strict=True)
        ]
        print(table(["class", "precision", "recall", "F1", "n"], rows))
        print(
            table(
                ["true \\ predicted", *codes],
                [[c, *r] for c, r in zip(codes, res["confusion"], strict=True)],
            )
        )
        return 0

    fixed = None
    if args.tuning:
        tuning = json.loads(args.tuning.read_text(encoding="utf-8"))
        fixed = (float(tuning["temperature"]), float(tuning["threshold"]))
    main_result = evaluate(sims, y, calib, test, args.target, k, fixed)
    refit = evaluate(sims, y, calib, test, args.target, k)
    swapped = evaluate(sims, y, test, calib, args.target, k)
    correct = (softmax(sims[test] / main_result["temperature"]).argmax(axis=1) == y[test]).astype(
        float
    )
    ci = bootstrap_accuracy(correct)
    clip_default = summary(softmax(sims[test] / CLIP_TEMPERATURE), y[test], 0.45, k)
    contract_default = summary(softmax(sims[test] / main_result["temperature"]), y[test], 0.45, k)
    nc = codes.index(NOT_CIVIC)
    test_pred = softmax(sims[test] / main_result["temperature"]).argmax(axis=1)
    civic = y[test] != nc
    false_not_civic = float((test_pred[civic] == nc).mean())

    r = main_result
    print(f"model {model.model_id}; calib n={int(calib.sum())}, test n={int(test.sum())}")
    source = "cross-fitted on calib" if fixed else "fit on calib"
    print(f"temperature ({source}) {r['temperature']:.4f}; CLIP default {CLIP_TEMPERATURE}")
    print(f"threshold ({source}, target {args.target:.0%} accepted accuracy) {r['threshold']:.2f}")
    print()

    def row(name: str, res: dict[str, Any]) -> list[object]:
        keys = ("accuracy", "macro_f1", "top3_accuracy", "nll", "ece", "threshold", "coverage")
        return [name, *(res[key] for key in keys), res["accuracy_accepted"]]

    headers = ["setting", "accuracy", "macro F1", "top-3", "NLL", "ECE"]
    headers += ["threshold", "coverage", "accepted acc."]
    print(
        table(
            headers,
            [
                row(f"test, T and threshold {source}", r),
                row("test, same T, contract threshold 0.45", contract_default),
                *([row("test, T refit on calib (optimistic)", refit)] if fixed else []),
                row("test, CLIP's own T=0.01, threshold 0.45", clip_default),
                row("swapped: fit on test, report calib", swapped),
            ],
        )
    )
    print(f"\ntest accuracy bootstrap 95% CI: {ci[0]:.3f}-{ci[1]:.3f}")
    print(f"civic test images flagged not_civic: {false_not_civic:.3f}\n")
    rows = [
        [c, s["precision"], s["recall"], s["f1"], s["support"]]
        for c, s in zip(codes, r["per_class"], strict=True)
    ]
    print(table(["class", "precision", "recall", "F1", "n"], rows), "\n")
    print(
        table(
            ["true \\ predicted", *codes],
            [[c, *row] for c, row in zip(codes, r["confusion"], strict=True)],
        ),
        "\n",
    )
    print(
        table(
            [
                "threshold",
                "calib coverage",
                "calib accepted acc.",
                "test coverage",
                "test accepted acc.",
            ],
            [
                [
                    f["threshold"],
                    f["coverage"],
                    f["accuracy_accepted"],
                    e["coverage"],
                    e["accuracy_accepted"],
                ]
                for f, e in zip(r["sweep_fit"], r["sweep_eval"], strict=True)
            ],
        )
    )
    if args.json:
        payload = {
            "model_id": model.model_id,
            "codes": codes,
            "calib_n": int(calib.sum()),
            "test_n": int(test.sum()),
            "test": main_result,
            "test_refit_temperature": refit,
            "swapped": swapped,
            "test_accuracy_ci95": ci,
            "clip_default_test": clip_default,
            "contract_threshold_test": contract_default,
            "civic_flagged_not_civic": false_not_civic,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
