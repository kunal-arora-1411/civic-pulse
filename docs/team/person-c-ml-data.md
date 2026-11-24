# Person C: ML and data engineer

**Mission:** make the AI trustworthy, and turn the data into decisions. You own model quality, matching quality, trust and abuse signals, and the analytics layer, including the analytics assistant. AI assists; it never decides alone (PRD §8.6).

## You own
- `apps/api/app/ai/` (models behind `interfaces.py`), `apps/api/app/domains/ai/`
- `apps/api/app/domains/analytics/` (new in S4)
- `apps/api/scripts/eval/`, `apps/api/scripts/download_models.py`, `models.lock.json`, `docs/eval/`
- `infra/ai-worker/`
- The verification rules engine (S3) and the abuse signals (S6)

**Your backup is A.** A reviews one of your PRs a week, and you review one of A's.

## Before you start
- Read: PRD §8, §12.3, §14, `docs/api/phase-2-contract.md`, `apps/api/app/ai/interfaces.py`.
- The Phase 2 ML branch already has CLIP on ONNX, the perceptual hash, YuNet face blurring, prompts, the real registry and the `ai-worker` image in progress. Finishing and landing it is your first job.
- **Migrations go through A.** Write them on your branch, but A merges them, to keep the chain linear.

---

## Order of implementation

| # | Task | Sprint | Depends on | Unblocks |
|---|---|---|---|---|
| 1 | **C1.1** Finish the real models + `ai-worker` | S1 | — | A1.1 |
| 2 | **C1.2** Evaluation baseline + threshold recommendations | S1 | C1.1 | A1.1, M1 |
| 3 | **C1.3** Merge with A (registry, queues, stand-ins) | S1 | C1.1, C1.2 | B1.1, D1.2 |
| 4 | **C1.4** Close the face-blur gap | S1 | C1.3 | M1 |
| 5 | **C1.5** 50-concurrent matching test + timing | S1 | C1.3 | M1 |
| 6 | **C2.1** Before/after evidence + scene-similarity flag | S2 | A1.3 | B3.1, B3.2 |
| 7 | **C2.2** Re-index tooling for model changes | S2 | C1.3 | C6.3 |
| 8 | **C3.1** Verification rules engine | S3 | A1.3, C2.1 | A3.2, B3.3 |
| 9 | **C3.2** Suspicious verification patterns | S3 | C3.1 | C6.2 |
| 10 | **C4.1** Metric definitions document | S4 | — | C4.2, A5.4, B5.1 |
| 11 | **C4.2** Analytics materialized views + refresh | S4 | C4.1 | C5.1 |
| 12 | **C4.3** Matching quality monitoring | S4 | C1.3 | C5.4 |
| 13 | **C5.1** Analytics API | S5 | C4.2 | B5.1 |
| 14 | **C5.2** Hotspots + period comparison + recurrence | S5 | C4.2 | B5.2 |
| 15 | **C5.5** Public location generalisation | S5 (first) | Precision decision | A5.2, B5.3 |
| 16 | **C5.3** Analytics assistant | S5 | C5.1, LLM decision | B5.5 |
| 17 | **C5.4** AI quality trends API | S5 | C4.3 | B5.1 |
| 18 | **C6.1** Voice transcription | S6 | Speech-provider decision | B6.4 |
| 19 | **C6.2** Abuse signals | S6 | C3.2 | — |
| 20 | **C6.3** Threshold refresh with real corrections | S6 | C2.2, pilot data | Launch |
| 21 | **C7.1** Live AI monitoring | Launch | — | — |

**Why this order:**
1. **Landing the ML branch (C1.\*) is on the critical path for M1,** and B and D are waiting on it to test Phase 2 for real.
2. **C5.5 is first in S5** because both A5.2 and B5.3 wait on it.
3. **Metric definitions (C4.1) come before any view or dashboard.** Otherwise the numbers will disagree between screens, which AN-004 forbids.
4. **The assistant (C5.3) is last in S5,** because it's built on top of the analytics API and needs the hosted-LLM decision.

---

## Sprint 1 · 30 Nov – 11 Dec · *Land the AI layer*

### C1.1 Real models + `ai-worker`
- `ClipOnnxModel` (pinned revision, verified hashes, licence recorded), `PromptZeroShotClassifier`, `perceptual_hash`, `YuNetFaceDetector` + `blur_regions`, and the real `registry.py` (`AI_PROVIDER=onnx|fake`).
- The `ai-worker` image: no torch, no CUDA. Models are baked in or loaded into a named volume. The model registry is populated on startup.
- Report per-image latency and image size.

### C1.2 Evaluation baseline (`docs/eval/phase-2-baseline.md`)
- Openly licensed images (CC0/PD/CC BY/BY-SA), with the manifest committed and the images not.
- A held-out split: fit the temperature and threshold on the calibration split, report on the test split.
- **Classification:** per-class precision, recall and F1, plus the confusion matrix.
- **Matching:** visual-similarity distributions, precision, recall and false-merge rate at the configured thresholds.
- Recommend `classification_threshold`, `visual_min` and `auto`. If they differ from the contract defaults, agree the change with A.

### C1.3 Merge with A
Pair on it: the real registry replaces the stub, `domains/ai/vision.py` uses the real modules, and compose queues are split (`worker` → default, `ai-worker` → ai).

### C1.4 Face-blur gap
Today the unblurred display copy can be visible for a few seconds. Fix it so public copies are published **only after** face detection runs when `AI_FACE_BLUR` is on: either blur inside the variant step on the AI queue, or hold `ready` until blurring finishes. Add a test.

### C1.5 Concurrency at scale
50 simultaneous near-identical reports at one spot → exactly one issue with correct counts, against the real `ai-worker`. Record how long matching takes end to end.

**Done when:** AC-02 to AC-06 pass in CI against the real models (D1.2), and the baseline evaluation is published.

## Sprint 2 · 14 – 25 Dec
- **C2.1 Before/after evidence:**
  - With A, the `work_evidence` purpose with `phase`
  - Compare the `after` photo with the issue's `before` and report photos
  - Produce a `scene_match` score and flag, shown to supervisors as advice only (§8.6)
  - Never block closure on it
- **C2.2 Re-index tooling:** a command that re-embeds every media item for a new `model_id`, resumable and rate-limited, plus a runbook for switching models safely (old and new embeddings side by side, switch matching over, then drop the old ones).

## Sprint 3 · 28 Dec – 8 Jan (~60% capacity)
- **C3.1 Verification rules engine** (FR-073, FR-075):
  - pure functions plus a service
  - eligibility: original reporters and followers with verified accounts
  - the default rule: supervisor approval, **or** ≥2 distinct eligible confirmations with no "unresolved" response
  - one vote per person per issue
  - an "unresolved" response triggers review
  - configurable per tenant
  - A wires the state changes (A3.2)
- **C3.2 Suspicious patterns:** bursts of verifications from new accounts, the same device or IP, or verification seconds after closure. These flag the issue for review and never decide on their own.

## Sprint 4 · 11 – 22 Jan
- **C4.1 Metric definitions** (`docs/metrics.md`, AN-004). Every dashboard metric gets:
  - its exact definition (what's counted, which timestamps, how merged, withdrawn and rejected items are treated, the timezone)
  - its SQL source
  - an example
  Covered metrics include: reports, issues, reports per issue, unique reporters, acknowledgement/assignment/resolution times (mean and median), SLA compliance, duplicate and review rates, reopen rate.
- **C4.2** Materialized views (or rollup tables) for those metrics, refreshed by Celery Beat, with RLS respected. Indexes tuned with D.
- **C4.3 Matching quality monitoring:** weekly rollups of auto-link feedback, review outcomes and correction rates by category. Alert when quality drops.

## Sprint 5 · 25 Jan – 5 Feb
- **C5.5 (do first) Public location generalisation:** snap to coarse h3 cells or a configurable precision for public views; never expose exact points (FR-051, §12.2).
- **C5.1 Analytics API:** overview, breakdowns and trends, filtered by date, ward, zone, category, priority, status and department (AN-001), with every response saying which metric definition it uses.
- **C5.2 Hotspots:** h3 aggregation at 2–3 resolutions, period-over-period comparison (FR-048), recurring locations (repeated creation or reopening, FR-049).
- **C5.3 Analytics assistant** (AI-001–AI-005):
  - an LLM with tool use over ~10 **read-only, parameterised** analytics functions (no generated SQL), run with the asking user's scope
  - every answer states the period, filters and data used, and says when the data is insufficient
  - put it behind a provider interface so it can switch to a self-hosted model if the hosted-LLM decision is no
  - add an evaluation set of 30 questions with expected answers
- **C5.4** AI quality trends API for B's dashboard.

## Sprint 6 · 8 – 19 Feb
- **C6.1 Voice:** Bhashini or faster-whisper behind a provider interface; Hindi plus the regional language; the transcript returned for the citizen to edit.
- **C6.2 Abuse signals:** repeated perceptual hashes from one account, EXIF capture time far from submission time, the verification patterns from C3.2. They feed a moderation queue (§12.3).
- **C6.3 Threshold refresh:** retune with the correction labels collected so far; consider a linear probe on CLIP embeddings if zero-shot accuracy is weak; update `docs/eval/`.

## Launch week
- **C7.1** Daily check of live AI quality: correction rate, review rate, false-merge feedback. Adjust thresholds conservatively, logging each change.

---

## Recurring duties
- **Every model or threshold change** gets an entry in the model registry, an updated evaluation report and an ADR if it's significant.
- **Never let AI output be the only reason** for rejecting, closing or merging (PRD §8.6). Review every PR for this.
- Keep the default test suite fast and offline; tests that need real models are marked and run in their own CI job.
