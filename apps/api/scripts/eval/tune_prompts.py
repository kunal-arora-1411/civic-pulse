"""Try to improve DEFAULT_PROMPTS by searching on the calib split, honestly.

    uv run --extra ai python scripts/eval/tune_prompts.py --json .eval-cache/results/tuning.json

A greedy search picks, for each category in turn, the 3-6 prompt subset of
a candidate pool with the lowest log-loss, two rounds over all categories.
That is a lot of freedom for ~90 images, so the search's own score on calib
says little. Instead calib is cut in two by photographer, the search runs
on one half and is scored on the other, and the out-of-fold scores are
pooled. That estimates how searched prompts do on photos they weren't
chosen on, and it is compared with the current DEFAULT_PROMPTS, which were
written by hand and never fitted to calib, scored on all of calib.

Decision rule (calib only; the test split is never touched here): adopt
the searched prompts only if their out-of-fold accuracy beats the
hand-written ones. On the baseline data it did not (85% against 91%), so
the hand-written prompts ship. The out-of-fold run also shows why a
temperature must never be fitted on the images prompts were chosen on:
that gives T = 0.0027, far sharper than the cross-fitted 0.0086.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.prompts import DEFAULT_PROMPTS
from app.ai.zero_shot import PromptZeroShotClassifier, fit_temperature, normalize, softmax
from scripts.eval.common import DEFAULT_MODEL_DIR, embed_items, load_model
from scripts.eval.eval_classification import choose_threshold
from scripts.eval.manifest import DEFAULT_CACHE, DEFAULT_MANIFEST, photographer, read_manifest

POOL: dict[str, list[str]] = {
    "pothole": [
        "a photo of a pothole in the road",
        "a damaged road with potholes",
        "a broken asphalt road surface with a large hole",
        "a pothole filled with rainwater on a street",
        "a road full of potholes",
        "a close-up of a pothole in asphalt",
        "a crumbling road with holes and cracks",
        "a muddy road with water-filled potholes",
    ],
    "waste": [
        "a photo of garbage dumped on the street",
        "a pile of rubbish and plastic waste by the roadside",
        "an overflowing garbage dump in a city",
        "litter and trash scattered on the ground",
        "a heap of garbage in an Indian street",
        "fly-tipped rubbish on a pavement",
        "an overflowing dustbin with garbage around it",
        "animals eating from a garbage pile",
    ],
    "waterlogging": [
        "a photo of a flooded street after heavy rain",
        "a waterlogged road with vehicles driving through water",
        "people walking through a flooded road during the monsoon",
        "a street submerged under rainwater",
        "a flooded city street",
        "cars driving through deep water on a road",
        "a large puddle of standing water on a road",
    ],
    "streetlight": [
        "a photo of a street light pole",
        "a street lamp on a road",
        "a broken street light",
        "a lamp post beside a road at night",
        "a street lamp post",
        "a glowing street light at night",
        "a fallen street light pole",
        "an old-fashioned street lamp",
    ],
    "drainage": [
        "a photo of an open drain beside a road",
        "a clogged drain full of sewage and garbage",
        "a dirty open sewer channel in a city",
        "an overflowing drain with dirty water",
        "a manhole cover in the road",
        "a storm drain grate at the roadside",
        "a blocked drain grate full of leaves and debris",
        "an open manhole in the road",
        "a roadside gutter channel",
    ],
    "not_civic": [
        "a selfie of a person",
        "a photo of food on a plate",
        "a screenshot of a phone or computer screen",
        "a photo of a document or a page of text",
        "a photo of a room indoors",
        "a portrait photo of people",
        "a photo of a pet dog",
        "a photo of an office desk with a computer",
        "a handwritten letter",
    ],
}
# The contract names these kinds of not-civic photo; the evaluation set has
# too few of them for the search to keep the prompts on merit.
ALWAYS: dict[str, list[str]] = {
    "not_civic": ["a screenshot of a phone or computer screen", "a photo of a room indoors"],
}

Selection = dict[str, list[str]]


class Scorer:
    def __init__(self, text: dict[str, dict[str, NDArray]], codes: list[str]) -> None:
        self.text = text
        self.codes = codes

    def classes(self, sel: Selection) -> NDArray:
        return np.stack(
            [
                normalize(normalize(np.stack([self.text[c][p] for p in sel[c]])).mean(axis=0))
                for c in self.codes
            ]
        )

    def nll(self, sel: Selection, emb: NDArray, y: NDArray) -> float:
        sims = emb @ self.classes(sel).T
        t = fit_temperature(sims, y)
        p = softmax(sims / t)
        return float(-np.mean(np.log(np.maximum(p[np.arange(len(y)), y], 1e-12))))


def search(scorer: Scorer, emb: NDArray, y: NDArray, rounds: int = 2) -> Selection:
    sel: Selection = {c: POOL[c][:4] for c in scorer.codes}
    for _ in range(rounds):
        for code in scorer.codes:
            best_nll, best = scorer.nll(sel, emb, y), sel[code]
            for k in range(3, 7):
                for combo in itertools.combinations(POOL[code], k):
                    trial = {**sel, code: list(combo)}
                    value = scorer.nll(trial, emb, y)
                    if value < best_nll - 1e-4:
                        best_nll, best = value, list(combo)
            sel[code] = best
    for code, extra in ALWAYS.items():
        sel[code] = sel[code] + [p for p in extra if p not in sel[code]]
    return sel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--target", type=float, default=0.95)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    items = [i for i in read_manifest(args.manifest) if i.split == "calib"]
    model = load_model(args.model_dir)
    emb = embed_items(model, items, args.manifest.parent, args.cache)
    codes = sorted(POOL)
    y = np.array([codes.index(i.label) for i in items])
    text = {c: dict(zip(POOL[c], model.embed_texts(POOL[c]), strict=True)) for c in codes}
    scorer = Scorer(text, codes)

    # Two folds by photographer, so a series never sits on both sides.
    fold = np.array(
        [
            int(hashlib.sha1(photographer(i).encode(), usedforsecurity=False).hexdigest(), 16) % 2
            for i in items
        ]
    )
    oof = np.zeros((len(items), len(codes)))
    for k in (0, 1):
        sel = search(scorer, emb[fold != k], y[fold != k])
        oof[fold == k] = emb[fold == k] @ scorer.classes(sel).T
        print(f"fold {k}: searched on {int((fold != k).sum())}, scored {int((fold == k).sum())}")
    temperature = fit_temperature(oof, y)
    oof_probs = softmax(oof / temperature)
    threshold = choose_threshold(oof_probs, y, args.target)
    oof_acc = float((oof_probs.argmax(axis=1) == y).mean())

    final = search(scorer, emb, y)
    in_sample_t = fit_temperature(emb @ scorer.classes(final).T, y)

    hand_codes, hand_classes = PromptZeroShotClassifier(model).class_matrix(DEFAULT_PROMPTS)
    hand_sims = emb @ hand_classes.T
    hand_y = np.array([hand_codes.index(i.label) for i in items])
    hand_t = fit_temperature(hand_sims, hand_y)
    hand_acc = float((hand_sims.argmax(axis=1) == hand_y).mean())

    print(f"searched prompts, out of fold: accuracy {oof_acc:.3f}, T {temperature:.4f}")
    print(f"  (T fitted on the images the prompts were chosen on: {in_sample_t:.4f})")
    print(f"hand-written DEFAULT_PROMPTS on calib: accuracy {hand_acc:.3f}, T {hand_t:.4f}")
    verdict = "adopt the searched prompts" if oof_acc > hand_acc else "keep DEFAULT_PROMPTS"
    print(f"decision: {verdict}")
    print(json.dumps(final, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "model_id": model.model_id,
                    "searched_prompts": final,
                    "temperature": temperature,
                    "threshold": threshold,
                    "out_of_fold_accuracy": oof_acc,
                    "in_sample_temperature": in_sample_t,
                    "hand_written_calib_accuracy": hand_acc,
                    "hand_written_temperature": hand_t,
                    "decision": verdict,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
