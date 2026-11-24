# Phase 2 baseline: vision model evaluation

**Date:** 2026-11-24 · **Model:** `clip-vit-b32@onnx-1` (OpenAI CLIP ViT-B/32, fp32 ONNX export `Xenova/clip-vit-base-patch32@6b7c5237`, MIT) · **Dataset:** 187 openly licensed images (92 calib, 95 test)

> **These are baseline numbers on a small open dataset, not real-world performance** (PRD §3.2). The photos come from Wikimedia Commons and Flickr, not from citizens using the app; a test half of 95 images gives confidence intervals around ±4 points. Use the numbers to choose defaults and to compare models, not to promise accuracy.

Raw results: [`phase-2-baseline-classification.json`](phase-2-baseline-classification.json), [`phase-2-baseline-dedup.json`](phase-2-baseline-dedup.json). Everything here can be rerun with the scripts in `apps/api/scripts/eval/` (commands at the end).

## Summary and recommended defaults

| Setting | Contract default | Recommendation | Why |
|---|---|---|---|
| Classifier temperature | — | **0.0084** | Fitted on calib; test log-loss 0.21, calibration error 0.036 |
| `matching_config.classification_threshold` | 0.45 | **keep 0.45** | Where accepted suggestions pass 95% accuracy on calib; on test 99% of photos get a suggestion, 94.7% of them right |
| `thresholds.visual_min` (auto-link visual floor) | 0.80 | **raise to 0.92** | At 0.80, 11% of pairs of *different* photos of the same category pass the floor. 0.92 is the lowest floor with ≤ 1% false merges on calib (0.8% on test) |
| `thresholds.auto` (auto-link score) | 0.85 | keep 0.85, but note the consequence | With the default weights it already rules out auto-linking beyond about half the radius, whatever the photos look like |
| pHash same-photo rule | ≤ 6 bits | keep | Fires on every re-upload, never on augmented views or different photos (closest different pair: 20 bits) |

The visual floor is the one change I'd ask for: **the contract's 0.80 is too permissive for this model.** It doesn't change the contract by itself; `visual_min` is tenant configuration, so the seeded default is where it would go.

## Dataset

| Label | Images | Calib | Test |
|---|---:|---:|---:|
| pothole | 30 | 15 | 15 |
| waste | 34 | 17 | 17 |
| waterlogging | 36 | 18 | 18 |
| streetlight | 31 | 15 | 16 |
| drainage | 28 | 13 | 15 |
| not_civic | 28 | 14 | 14 |
| **total** | **187** | **92** | **95** |

**Sources and licences.** 39 images from Wikimedia Commons and 148 from Flickr (found through Openverse); CC BY 90, CC BY-SA 81, public domain 12, CC0 4. Each row in `apps/api/scripts/eval/manifest.csv` records the source page, author, licence, licence URL and the sha256 of the bytes fetched. The images are not committed.

**How it was built.** Commons was searched with curated queries per class, Indian street scenes first (`fetch_commons.py`). Commons then rate-limited media downloads that miss its caches: after about a hundred files it answered 429 for hours. So the thin classes were topped up from Flickr through Openverse with the same licence rule (`fetch_openverse.py`). Of 812 candidates, about 500 were downloaded and every one was looked at on contact sheets; 314 were dropped or relabelled, each with a reason in `rejected.csv` (scenery, people posing, collages, newspaper clippings, toy street lamps, sewer-tunnel exploration, near-identical frames…). Decorative manhole covers were capped so that "drainage" doesn't become "pretty manhole art". Finalising also drops pHash near-duplicates.

**Split.** Stratified by label and **grouped by photographer** (Flickr account or credited author), so a series of one scene never sits on both sides. Before grouping, eight near-identical pairs (CLIP cosine above 0.92) straddled the split; afterwards two remain across it, and both are genuinely different manhole covers.

**What it is not.** Indian scenes are well represented in pothole and waste, much less in waterlogging, streetlight and drainage (the Commons candidates for those were the ones the rate limit blocked). Streetlights are mostly intact lamps, often heritage designs, rather than the broken or unlit lights citizens would report. There are no screenshots and few bare interiors in `not_civic`. Several waterlogging photos are historical black-and-white.

## Classification (zero-shot, `PromptZeroShotClassifier`)

**Method.** Prompts are the hand-written `DEFAULT_PROMPTS`. The temperature is fitted on calib by minimising log-loss; the threshold is the lowest whose accepted suggestions are ≥ 95% accurate on calib. All numbers below are on test unless marked. Each image is classified alone; mean-pooling several photos of one report can't be measured with this set.

| Setting (test, n = 95) | Accuracy | Macro F1 | Top-3 | Log-loss | ECE | Threshold | Coverage | Accepted acc. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Shipped: T = 0.0084, threshold 0.45** | **0.947** | **0.946** | 1.000 | 0.208 | 0.036 | 0.45 | 0.989 | 0.947 |
| CLIP's own T = 0.01, threshold 0.45 | 0.947 | 0.946 | 1.000 | 0.212 | 0.042 | 0.45 | 0.989 | 0.947 |
| Swapped: fit on test, report on calib | 0.913 | 0.907 | 0.967 | 0.233 | 0.057 | 0.60 | 0.924 | 0.976 |

Test accuracy bootstrap 95% interval: **0.905–0.989**. No civic test image was classified `not_civic`, and every `not_civic` image was.

| Class | Precision | Recall | F1 | n |
|---|---:|---:|---:|---:|
| drainage | 0.812 | 0.867 | 0.839 | 15 |
| not_civic | 1.000 | 1.000 | 1.000 | 14 |
| pothole | 0.867 | 0.867 | 0.867 | 15 |
| streetlight | 1.000 | 1.000 | 1.000 | 16 |
| waste | 1.000 | 0.941 | 0.970 | 17 |
| waterlogging | 1.000 | 1.000 | 1.000 | 18 |

| True \ predicted | drainage | not_civic | pothole | streetlight | waste | waterlogging |
|---|---:|---:|---:|---:|---:|---:|
| drainage | 13 | 0 | 2 | 0 | 0 | 0 |
| not_civic | 0 | 14 | 0 | 0 | 0 | 0 |
| pothole | 2 | 0 | 13 | 0 | 0 | 0 |
| streetlight | 0 | 0 | 0 | 16 | 0 | 0 |
| waste | 1 | 0 | 0 | 0 | 16 | 0 |
| waterlogging | 0 | 0 | 0 | 0 | 0 | 18 |

The errors are where you'd expect: potholes and drains are both holes in the road surface, and a drain full of rubbish is also a waste photo. Category compatibility in the matcher and the citizen's own choice cover this.

**Threshold sweep** (accepted = top confidence ≥ threshold; the rest get `needs_manual`):

| Threshold | Calib coverage | Calib accepted acc. | Test coverage | Test accepted acc. |
|---:|---:|---:|---:|---:|
| 0.35 | 1.000 | 0.913 | 1.000 | 0.947 |
| 0.40 | 0.978 | 0.933 | 1.000 | 0.947 |
| **0.45** | **0.946** | **0.966** | **0.989** | **0.947** |
| 0.55 | 0.935 | 0.965 | 0.979 | 0.946 |
| 0.65 | 0.913 | 0.988 | 0.937 | 0.955 |
| 0.75 | 0.880 | 1.000 | 0.905 | 0.953 |
| 0.85 | 0.837 | 1.000 | 0.832 | 0.975 |

Raising the threshold buys little accuracy on test for a lot of manual selection; 0.45 is a sensible knee.

**Temperature.** The fitted 0.0084 is close to CLIP's built-in 0.01 and the two calibrate about equally well on test. The calibration plot isn't worth drawing at this size; ECE of 0.036 on 95 images is within noise of zero. Refit whenever the prompts or the model change.

### Prompt search: tried and rejected

`tune_prompts.py` ran a greedy search over a pool of 7–9 candidate prompts per class (every 3–6 prompt subset, two rounds), judged by cross-fitting within calib: search on one half (split by photographer), score the other. Searched prompts reached **0.848** out of fold against **0.913** for the hand-written prompts on calib, so by a calib-only rule the hand-written ones stay. The same run showed the trap it avoids: a temperature fitted on the images the prompts were chosen on comes out at 0.0027, three times too sharp, against 0.0086 cross-fitted.

In the interest of full disclosure: before setting that rule I had also scored the searched prompts on test (0.916, against 0.947 for the hand-written ones). The calib-only comparison points the same way, but the test estimate above is not perfectly untouched by that look.

## Duplicate detection (visual signal)

**Method** (`eval_dedup.py`, civic classes only). Positives: two independent random augmentations of the same photo (crop to 75–95% per side, rotate ±15°, brightness and contrast 0.7–1.3, rescale to 40–100%, JPEG quality 30–90). Negatives: every pair of different photos in the same category, the matcher's hard case, because candidates are already filtered to compatible categories nearby. Re-uploads: the photo against a recompressed, rescaled copy. Floor chosen on calib (lowest cosine with ≤ 1% false merges), reported on test: 81 positive and 619 negative pairs.

ROC AUC **0.989**, average precision **0.888**.

| Cosine (test) | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| same photo, augmented | 0.841 | 0.859 | 0.886 | 0.924 | 0.945 | 0.966 | 0.974 |
| re-upload | 0.894 | 0.924 | 0.960 | 0.979 | 0.988 | 0.999 | 1.000 |
| different photos, same category | 0.417 | 0.480 | 0.584 | 0.663 | 0.740 | 0.837 | 0.904 |

| Visual floor | Calib recall | Calib false-merge | Test recall | Test false-merge | Test precision |
|---:|---:|---:|---:|---:|---:|
| 0.80 (contract) | 0.987 | 0.135 | 1.000 | 0.110 | 0.544 |
| 0.84 | 0.962 | 0.064 | 0.988 | 0.045 | 0.741 |
| 0.86 | 0.923 | 0.047 | 0.938 | 0.029 | 0.809 |
| 0.88 | 0.859 | 0.017 | 0.802 | 0.019 | 0.844 |
| 0.90 | 0.679 | 0.010 | 0.704 | 0.011 | 0.891 |
| **0.92 (recommended)** | 0.449 | 0.007 | 0.543 | 0.008 | 0.898 |
| 0.94 | 0.218 | 0.002 | 0.333 | 0.008 | 0.844 |

"False-merge rate" is the share of different-photo pairs that pass the floor; "precision" depends on this set's 1:8 positive-to-negative ratio and shouldn't be read as a production figure.

**Reading it.** A wrongly auto-linked report hides a real problem, while a missed link only costs a reviewer a click, so the floor should sit where false merges are rare. At 0.92 half of the augmented same-photo pairs still auto-link and the rest go to review (any score ≥ 0.85 that fails the visual check goes to review under D.2). Real re-shoots differ more than augmentations (angle, light, weather), so expect fewer auto-links than this in practice; that's the safe direction. 0.90 is a defensible alternative if review load turns out too high.

**pHash rule.** A distance ≤ 6 caught 100% of re-uploads, 0% of augmented views (crops and rotations change the hash, as they should) and 0% of different photos; the closest pair of different photos was 20 bits apart.

**What the auto-link score already implies.** With weights 0.40/0.40/0.10/0.10, a same-category candidate scores `0.4·geo + 0.4·visual + 0.1 + 0.1·time`. Even with `visual = 1` and age 0, reaching 0.85 needs `geo ≥ 0.625`, i.e. a distance of at most 0.47 × radius. Visual similarity needed for auto-link (score ≥ 0.85 and visual ≥ 0.92), with the share of test positives that clear it:

| Distance | age 0 | age 0.1 × window | age 0.5 × window |
|---|---|---|---|
| 0 | 0.92 (54%) | 0.92 (54%) | 0.92 (54%) |
| 0.25 × radius | 0.92 (54%) | 0.92 (54%) | 0.94 (27%) |
| 0.5 × radius | never | never | never |
| 1 × radius | never | never | never |

That is reasonable behaviour (auto-link only very close, very similar reports), but it's a property of the weights rather than an explicit rule, so whoever tunes `matching_config` should know it.

## Models compared

All three on the same split and the same hand-written prompts, temperature and threshold fitted on calib.

| Model | Weights on disk | ms/image (batch 1 / 16, 4 threads) | Test accuracy (95% CI) | Log-loss | ECE | Dedup AUC | False merges at 0.80 |
|---|---:|---:|---|---:|---:|---:|---:|
| **OpenAI ViT-B/32 fp32** (Xenova export, MIT) — shipped | 606 MB | 41–55 / 35–38 | **0.947** (0.905–0.989) | **0.208** | **0.036** | 0.989 | 11.0% |
| Same, int8 dynamic quantisation (Xenova) | 153 MB | 33 / 29 | 0.895 (0.832–0.947) | 0.334 | 0.095 | 0.992 | 7.9% |
| OpenCLIP ViT-B/32 LAION-2B fp32 (Immich export) | 606 MB | fixed batch of 1 | 0.905 (0.842–0.958) | 0.226 | 0.049 | 0.989 | 2.3% |

The intervals overlap, so none of these differences is decisive at this size, but the shipped model is best or tied on every classification measure. int8 is attractive for size and speed, but its classification is worse and its confidences are badly calibrated, and its embeddings drift from fp32 (cosine 0.97 on the same image), so it would also need its own model id and a re-index. LAION's export has a fixed batch of one and no licence tag on the export repo (upstream weights are MIT). Note that LAION's similarity scale differs: its 0.80 is not OpenAI's 0.80, which is one more reason `visual_min` belongs to the model, not just the tenant.

## Latency and footprint

Measured on a 16-thread Intel desktop CPU (family 6 model 191), ONNX Runtime 1.32, 4 intra-op threads (the default cap), median of 5 runs, synthetic 1600×1200 inputs (ViT cost doesn't depend on content):

| Step | Time |
|---|---:|
| Image embedding, batch 1 | 41 ms (55 ms in a noisier run) |
| Image embedding, batch 16 | 35 ms per image |
| Image embedding, 1 thread, batch 1 / 16 | 122 / 96 ms per image |
| All 26 default prompts (once per prompt set, then cached) | 70 ms |
| Face detection, 1600×1200, both passes | 70 ms |
| Perceptual hash | 3 ms |

The AI worker image (`infra/ai-worker/Dockerfile`) is about 1.4 GB uncompressed and 645 MB compressed: Python slim ~125 MB, dependencies ~630 MB (the API's own plus onnxruntime, tokenizers and headless OpenCV; no torch, no CUDA), weights 608 MB.

## Caveats

- **Small data.** 95 test images, 13–18 per class. A single image moves per-class recall by about 7 points.
- **Not citizen photos.** Commons and Flickr pictures are composed by people who meant to photograph the subject. Citizen photos will be more cluttered, darker, blurrier and often taken from a moving vehicle.
- **Skewed sources.** Most of the set is from Flickr, and Indian scenes are a minority in three classes (see Dataset).
- **Augmentations are not re-shoots.** The duplicate positives are synthetic; real pairs of reports differ more. Recall is an upper bound and needs revisiting once review decisions accumulate (FR-035 feedback).
- **Negatives are from different places.** Real candidates within 30 m may share a street and look more alike, so the real false-merge rate at a given floor is likely higher than measured.
- **Single-image classification only.** Mean-pooling of several photos per report is implemented but not measured.
- **One look at test** during prompt selection (disclosed above).

## Reproduce

```sh
cd apps/api
uv sync --extra ai
uv run python scripts/download_models.py --model-dir .models
uv run python scripts/eval/fetch_commons.py download            # images listed in manifest.csv
AI_MODEL_DIR=.models uv run python scripts/eval/eval_classification.py --json out/classification.json
AI_MODEL_DIR=.models uv run python scripts/eval/eval_dedup.py --json out/dedup.json
AI_MODEL_DIR=.models uv run python scripts/eval/tune_prompts.py
AI_MODEL_DIR=.models uv run python scripts/eval/bench_latency.py
# alternatives: download_models.py --candidate clip-int8 | clip-laion2b --model-dir <dir>, then --model-dir <dir>
```

Commons downloads are throttled hard (one file every 20 seconds by default); expect the first fetch of the Commons rows to take a while.
