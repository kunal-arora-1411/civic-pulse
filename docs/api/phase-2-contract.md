# Phase 2 contract: the AI layer

This builds on the Phase 0 and Phase 1 contracts. All their conventions still apply: tenancy, the error envelope, pagination, idempotency, `[lng, lat]` order, UTC timestamps and `_i18n` objects. If any side needs to change this file, change it in the same commit and say so.

**Phase 2 goal (plan §5, PRD §7.3–7.5, §8):**
- The AI suggests a category while the citizen is reporting.
- New reports are matched against existing issues: linked automatically, sent to a human review queue, or turned into a new issue.
- Staff can merge and split issues.
- Every issue gets an explainable severity and priority.

All of it is auditable and overridable, and all of it keeps working when the AI is down.

Three engineers work in parallel:
- **ML engineer:** owns `apps/api/app/ai/` (except `interfaces.py`, which is fixed), the AI worker image, model download, face blurring and the evaluation harness.
- **Backend engineer:** owns the schema, domain logic, Celery pipeline wiring, endpoints and seed.
- **Frontend engineer:** owns `apps/web`.

---

## A. Python interface between the domain and the models

`apps/api/app/ai/interfaces.py` is committed and fixed: `VisionModel`, `ZeroShotClassifier`, `FaceDetector`, `CategoryScore`, `Box`, `perceptual_hash_distance`. On top of it:

| Symbol (in `app/ai/`) | Owner | Behaviour |
|---|---|---|
| `fake.py`: `FakeVisionModel`, `FakeZeroShotClassifier`, `FakeFaceDetector` | **Backend** | Deterministic and dependency-free (numpy + Pillow only). The fake model derives a stable unit vector from the image's downscaled pixels, so identical or near-identical images get cosine ≈ 1 and unrelated ones a low score. The fake classifier reads an optional test hook (e.g. the image's dominant colour or a `CP_TEST_LABEL` PNG text chunk) so tests can control the outcome. |
| `phash.py`: `perceptual_hash(image) -> int` | **ML** | 64-bit DCT pHash using numpy only (no scipy). Robust to recompression and resizing. |
| `clip.py`: `ClipOnnxModel` | **ML** | Real `VisionModel` on ONNX Runtime, CPU only. Default weights: a pre-exported CLIP ViT-B/32 ONNX (vision + text encoders and tokenizer) from the Hugging Face Hub, or an evaluated SigLIP equivalent. **No torch at runtime.** Record the exact repo, revision, file hashes and licence. |
| `zero_shot.py`: `PromptZeroShotClassifier` | **ML** | Softmax over category prompt embeddings, with a temperature calibrated on the evaluation set. Returns the reserved `unknown` code (confidence = 1 − top score) when the top score is below the configured threshold. |
| `faces.py`: `YuNetFaceDetector` + `blur_regions(image, boxes) -> Image` | **ML** | OpenCV YuNet ONNX (record the licence). Strong Gaussian or pixelate blur with padding around each box. |
| `registry.py`: `get_vision_model()`, `get_classifier()`, `get_face_detector()` | **ML** writes the real branch; **Backend** may add the fake branch first if needed | Chosen by settings: `AI_PROVIDER=onnx|fake` (default `fake` in tests and in the API container, `onnx` in the AI worker), `AI_MODEL_DIR` (default `/models`). Model instances are cached per process. |
| `prompts.py`: `DEFAULT_PROMPTS: dict[str, list[str]]` | **ML** | 3–6 English prompts each for `pothole`, `waste`, `waterlogging`, `streetlight`, `drainage`, plus `not_civic` (selfies, food, screenshots, documents, indoor scenes…). Tuned on the evaluation set. A category may override its prompts via its config (B.1). |

`AI_FACE_BLUR=true|false` (default true where `AI_PROVIDER=onnx`).

## B. Data model (Backend owns the migrations)

### B.1 Category additions
- `ai_prompts: list[str] | null`, overriding `DEFAULT_PROMPTS[code]`.
- `severity_rules`: see section E.
- `parent_id` (already present) feeds category compatibility.

### B.2 New tables (all tenant-scoped with RLS)
- `model_registry`: `model_id` (PK per tenant or global), `task` (`embedding|classification|face_detection`), `name`, `version`, `source` (repo + revision), `license`, `deployed_at`, `intended_use`, `metrics` (JSON). Global rows are fine here: this table has no tenant data, so it may skip RLS with a comment explaining why.
- `media_embeddings`: `media_id`, `model_id`, `embedding vector(D)`, `phash bigint`, `created_at`. HNSW index (cosine) on `embedding`. Unique on (`media_id`, `model_id`). `D` comes from the model; 512 for ViT-B/32. If the model changes dimension, a new migration adds a new column or table; document that.
- `classifications`: `id`, `requested_by`, `media_ids[]`, `model_id`, `status` (`pending|done|failed`), `scores` (JSON list of `{code, confidence}`), `top_code`, `top_confidence`, `error`, timestamps.
- `reports` gets: `classification_id` (nullable), `category_source` (`citizen|ai_accepted|ai_corrected|operator`), `matching_status` (`pending|linked|review|new_issue`), and `issue_id` **becomes nullable** while matching is pending.
- `match_decisions`: `id`, `report_id`, `candidate_issue_id`, `rank`, `score`, `signals` (JSON, see D.3), `decision` (`auto_linked|sent_to_review|rejected_candidate|chosen_by_reviewer|not_chosen`), `model_id`, `decided_by` (null = system), `created_at`, `decided_at`, `feedback` (`correct|incorrect|null`), `feedback_by`, `feedback_at`, `feedback_note`.
- `review_tasks`: `id`, `report_id` (unique while open), `status` (`open|resolved`), `resolution` (`linked|new_issue`), `resolved_issue_id`, `resolved_by`, `resolved_at`, `created_at`.
- `issue_relations`: `issue_id`, `related_issue_id`, `note`, `created_by`, `created_at`. Stored as one row per unordered pair.
- `civic_issues` gets:
  - `merged_into_id` (nullable self-reference)
  - `severity` (enum `low|medium|high|critical`), `severity_source` (`rule|override`), `severity_reason`
  - `priority_score` (0–100 numeric), `priority_band` (computed), `priority_override_band`, `priority_override_reason`, `priority_factors` (JSON), `priority_computed_at`
  - Replace the Phase 1 string `severity`/`priority` columns.
- `places_of_interest`: `id`, `kind` (`school|hospital|bus_stop|market|other`), `name`, `geom point`. Seeded synthetically. Admin CRUD comes later.
- Tenant config tables, or JSON columns on `tenants.config`, for `matching_config` and `priority_config` (sections D.2 and F).

## C. Category suggestion during reporting (FR-020 to FR-022)

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/ai/classifications` | `report:create` | Body `{ media_ids: [uuid] }`. The media must be the caller's and completed. The API queues an AI task and **waits up to 4 s** for it. Returns `200` with the classification if done, otherwise `202` with `status: "pending"`. If the AI is unavailable, returns `200` with `status: "failed"`, `error: "ai_unavailable"`; the client then just asks for manual selection. |
| GET | `/api/v1/ai/classifications/{id}` | owner | Poll every 1–2 s, giving up after ~15 s. |

```json
{
  "id": "uuid", "status": "done", "model_id": "clip-vit-b32@onnx-1",
  "suggestions": [ { "category_id": "uuid", "code": "pothole", "confidence": 0.82 },
                   { "category_id": "uuid", "code": "drainage", "confidence": 0.09 } ],
  "not_civic": false, "needs_manual": false
}
```
- `suggestions` covers active tenant categories only, up to 3.
- `not_civic` is true when that reserved code wins. The client shows a soft warning but never blocks the citizen (PRD §8.6).
- `needs_manual` is true when the top category confidence is below `matching_config.classification_threshold` (default 0.45), or the result is `unknown`.

**Report creation additions:** `POST /reports` accepts an optional `classification_id`. The web app sends it only when the citizen was shown that classification's suggestion (pre-selected on the category step). It leaves it out after a failure, a timeout, `needs_manual` or `not_civic`, so a choice is never recorded as accepting or correcting a suggestion the citizen didn't see. The server sets `category_source`:
- `ai_accepted`: the chosen category equals the top suggestion
- `ai_corrected`: it differs (this becomes a correction label, FR-021)
- `citizen`: no classification

**Operator correction:** `PATCH /api/v1/issues/{id}/category { category_id, reason, version }` (`issue:update`). This sets `category_source = operator` on the issue's reports, recomputes severity and priority, and is audited. Like the status change it returns `200` with the updated issue detail, and a blank reason is `422 reason_required`.

## D. Duplicate matching (FR-024 to FR-037)

### D.1 Pipeline
1. **`POST /reports`** still validates and saves everything in one transaction, but **no longer creates an issue**. The report is stored with `issue_id = null` and `matching_status = pending`, and a `match_report` task is queued after commit. The response returns at once with `matching_status: "pending"` and `issue: null`.
2. **`analyze_media`** (AI queue), once per media: compute the embedding and pHash and store them in `media_embeddings`. Reuse them if they already exist for this model (the classification step may have computed them). When `AI_FACE_BLUR` is on, also re-render the `display` and `thumb` copies with faces blurred. Originals are never altered.
3. **`match_report`** (AI queue, after the report's media are analysed, or right away if there are no photos): run D.2 and apply the decision **inside one transaction holding an advisory lock** scoped to (tenant, category family). Then re-check candidates under the lock. This is the FR-036 guarantee: concurrent duplicates never create two issues.
4. **Fallback when the AI is unavailable** (no embeddings within 2 minutes, or the AI provider is down): match without the visual signal. Never link automatically. If any candidate scores ≥ 0.40 on the remaining signals, open a review task; otherwise create a new issue. Record `signals.visual = null` and `reason: "ai_unavailable"`.
5. After a decision: link or create the issue, keep counts correct (`report_count`, and `unique_reporter_count`, which a reporter already on the issue doesn't increase), write timeline and audit events, and recompute priority.

### D.2 Candidates and score
- **Candidates:** issues not merged away, in the same tenant, within `category.dedup.radius_m` (PostGIS geography distance), with a compatible category, and either open or closed/resolved within `category.dedup.window_days`. At most 10, ordered by distance.
- **Signals**, each in [0, 1]:
  - `geo = exp(-distance_m / radius_m)`
  - `visual` = the highest cosine similarity across all (new photo × candidate photo) pairs, clamped to [0, 1], or `null` when there are no embeddings. Same-photo boost: a pHash Hamming distance ≤ 6 sets `visual = 1` and `same_photo = true`.
  - `category`: 1.0 for the same category, 0.5 for the same parent; otherwise not a candidate.
  - `time = exp(-age_days / window_days)`, where age is measured from the candidate's last report.
- **Score:** `w_geo·geo + w_visual·visual + w_category·category + w_time·time`. Default weights 0.40 / 0.40 / 0.10 / 0.10. If `visual` is null, re-normalise over the remaining weights.
- **Decision** (configurable thresholds, defaults shown):
  - **Auto-link:** score ≥ 0.85 **and** visual ≥ 0.80 **and** distance ≤ radius **and** `matching_config.auto_link_enabled` (default true). Never on distance alone (AC-05).
  - **Review:** best score ≥ 0.60, or any score ≥ 0.85 that failed the auto-link checks above.
  - **New issue:** anything else.
- Every candidate considered gets a `match_decisions` row, so the decision can always be explained (FR-037).

### D.3 Signals JSON
```json
{ "distance_m": 18.4, "radius_m": 30, "geo": 0.54, "visual": 0.91, "same_photo": false,
  "category": 1.0, "time": 0.93, "age_days": 2.1, "weights": { "geo": 0.4, "visual": 0.4, "category": 0.1, "time": 0.1 },
  "thresholds": { "auto": 0.85, "review": 0.6, "visual_min": 0.8 }, "reason": null }
```

### D.4 Endpoints
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/review-tasks` | `issue:triage` | `?status=open` (default). Jurisdiction-scoped, in the standard page envelope; the web app reads `total` for the open count in the nav. Items: `{ id, created_at, report: <staff report view>, candidates: [ { match_decision_id, score, signals, issue: <issue list item> } ] }`, best candidate first. |
| GET | `/api/v1/review-tasks/{id}` | `issue:triage` | Same shape as a list item |
| POST | `/api/v1/review-tasks/{id}/resolve` | `issue:triage` | `{ action: "link", issue_id }` or `{ action: "new_issue" }`. Applies D.1 step 5 under the same lock. The chosen decision is marked `chosen_by_reviewer`, the others `not_chosen` (FR-035 feedback). A task that's already resolved returns `409 conflict`. |
| POST | `/api/v1/match-decisions/{id}/feedback` | `issue:triage` | `{ correct: bool, note? }`. Mainly used on auto-links, from the issue detail page. |
| GET | `/api/v1/reports/{id}` | (as before) | Report views add `matching_status` and, for staff, `match: { decision, score, signals, match_decision_id } \| null`. The owner view shows `issue` once linked; while `matching_status` is `pending` or `review`, `issue` is `null` and the citizen sees "Checking for similar reports". The owner view's `issue` also carries `report_count` and `unique_reporter_count`, so the confirmation can say how many people reported the problem. |
| GET | `/api/v1/users/me/reports` | (as before) | Items add `matching_status`, and their `issue` is `null` until the report is placed. |

Issue detail adds `match_decisions` per report (staff only): every candidate considered for that report, best first, as `[ { id, candidate_issue: { id, reference }, rank, score, signals, decision, decided_by: { id, display_name } | null, decided_at, feedback: "correct" | "incorrect" | null } ]`. The web app uses it to show how each report got onto the issue and to collect feedback on auto-links.

### D.5 Merge, split and related issues (FR-033, FR-034, FR-060)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/issues/{id}/merge` | `issue:merge` | `{ source_issue_ids: [uuid], reason, version }`. `{id}` is the surviving issue. Source issues get `merged_into_id = id`, keep their reference and history, and drop out of lists and the map. Their reports move to the survivor, and counts are recomputed from the actual reports. The survivor keeps its own status. Timeline entries go on both sides, plus an audit event, and priority is recomputed. Merging into an issue that's itself merged, or into itself, returns `422 invalid_merge`. |
| POST | `/api/v1/issues/{id}/split` | `issue:merge` | `{ report_ids: [uuid], target: { "new_issue": true } \| { "issue_id": uuid }, reason, version }`. Moving every report out returns `422 cannot_empty_issue`. A new issue copies the category and takes its location from the first moved report, starting at status `reported`. Returns `{ source: <issue detail>, target: <issue detail> }`. |
| GET | `/api/v1/issues/{id}` | | A merged issue returns `200` with `merged_into: { id, reference }`, so the client can redirect. Detail also adds `related: [ { issue: <list item>, note } ]`. |
| POST | `/api/v1/issues/{id}/related` | `issue:update` | `{ issue_id, note? }`, audited |
| DELETE | `/api/v1/issues/{id}/related/{other_id}` | `issue:update` | `204` |

Citizens whose reports moved see the new issue in their report detail. The public timeline says "Combined with another report of the same problem", without staff names.

**Timeline event types added in Phase 2.** Staff see all of them; citizens only the public ones. Where the action took a reason, it's in the event's `reason`.

| `type` | Visibility | Written when |
|---|---|---|
| `report_linked` | internal | A report joins the issue, automatically or through a review task |
| `merged` | public | Other issues were merged into this one ("Combined with another report of the same problem") |
| `merged_into` | internal | This issue was merged into another |
| `split` | internal | Reports were moved out of, or into, this issue |
| `category_changed` | internal | An operator corrected the category |
| `severity_changed` | internal | A severity override was set or cleared |
| `priority_changed` | internal | A priority override was set or cleared |
| `related_added`, `related_removed` | internal | A related-issue link was added or removed |

## E. Severity (FR-038)
- `category.severity_rules`:
  ```json
  { "base": "medium",
    "field_rules": [ { "field": "size", "equals": "large", "set": "high" } ],
    "near_places": [ { "kinds": ["school","hospital"], "within_m": 150, "raise_by": 1 } ],
    "report_count_raise": [ { "unique_reporters_gte": 5, "raise_by": 1 } ] }
  ```
  Levels run `low < medium < high < critical`. Raises are capped at `critical`, and when several field rules match, the highest wins.
- Computed whenever an issue's reports or category change. A `severity_source = override` value stays until it's cleared.
- `PATCH /api/v1/issues/{id}/severity { severity: level | null, reason, version }` (`issue:update`). `null` clears the override. A reason is required when setting one. Audited, with a timeline event. Returns `200` with the updated issue detail, whose `severity` carries the override's `reason` while there is one.

## F. Priority (FR-039 to FR-044, PRD §8.4)
- Rules only, no ML. Tenant `priority_config` (defaults shown):
  ```json
  { "weights": { "severity": 40, "reporters": 20, "age": 15, "recurrence": 15, "near_places": 10 },
    "severity_points": { "low": 0.1, "medium": 0.4, "high": 0.75, "critical": 1.0 },
    "reporters_saturation": 10, "age_saturation_days": 30,
    "recurrence": { "radius_m": 50, "lookback_days": 180, "saturation": 3 },
    "bands": { "critical": 80, "high": 60, "medium": 35 } }
  ```
- Each factor is normalised to [0, 1] and multiplied by its weight. `score` is the sum (0–100), and the band comes from the thresholds (below `medium` means `low`). Status `rejected`, `closed` or merged gives a score of 0.
- **Factor scaling:**
  - `reporters = min(1, log(1+u) / log(1+saturation))`, where `u` is the number of unique reporters. Report volume alone can't push the score up (PRD §12.3).
  - `age = min(1, days / saturation)`
  - `recurrence`: issues with the same category within `radius_m` created in the lookback window, excluding this one, divided by the saturation and capped at 1.
  - `near_places`: 1 if any place of interest is within 150 m, else 0.
- `priority_factors`, sorted by points descending:
  ```json
  [ { "factor": "severity", "value": "high", "normalized": 0.75, "points": 30.0, "explanation_key": "priority.severity" }, ... ]
  ```
  The client localises each `explanation_key`.
- **Recomputed** on report link/unlink, merge/split, severity or category change, status change, and nightly for ageing (Celery Beat).
- **Override:** `PATCH /api/v1/issues/{id}/priority { band: "critical|high|medium|low" | null, reason, version }` (`issue:set_priority`). The effective band is the override when present. Audited, with a timeline event. Returns `200` with the updated issue detail. Merge (D.5) returns the survivor's detail the same way.

**Issue list item and detail change to:**
```json
"severity": { "level": "high", "source": "rule" },
"priority": { "score": 67.5, "band": "high", "computed_band": "high", "overridden": false, "override_reason": null, "factors": [ ... ] }
```
`factors` appear on the detail only. The issue list adds `sort=-priority` (the new default for staff) and filters `severity` and `priority_band` (both repeatable). `GET /issues/geojson` takes the same two filters, and each feature's properties add `priority_band` (the effective band, or `null` while unscored) so the staff map can shape its markers by band.

## G. Configuration and governance
| Method | Path | Permission |
|---|---|---|
| GET / PUT | `/api/v1/admin/matching-config` | `config:read` / `config:manage` |
| GET / PUT | `/api/v1/admin/priority-config` | `config:read` / `config:manage` |
| GET | `/api/v1/admin/ai/models` | `config:read`: model registry rows, plus which model is active per task: `{ items: [ { model_id, task, name, version, source, license, deployed_at, intended_use, metrics } ], active: { embedding, classification, face_detection } }`, where each `active` value is a `model_id` or `null` |
| GET | `/api/v1/admin/ai/quality` | `config:read`: counts over a `from`/`to` window: classifications done/failed, accepted vs corrected by category, auto-link / review / new-issue counts, review outcomes, auto-link feedback marked correct/incorrect. Feeds a simple table now; fuller dashboards come in Phase 5. Shape: `{ from, to, classifications: { done, failed }, category_choices: [ { category_id, code, accepted, corrected } ], matching: { auto_linked, sent_to_review, new_issue }, reviews: { linked, new_issue }, auto_link_feedback: { correct, incorrect } }` |

`matching_config` JSON: `{ auto_link_enabled, weights, thresholds: { auto, review, visual_min }, classification_threshold, fallback_review_threshold }`. Validated, with sane bounds, and every PUT is audited.

## H. AI worker and evaluation (ML engineer)
- **`ai-worker` compose service:** image built from `infra/ai-worker/Dockerfile`, which installs `apps/api` with the `ai` extra. It consumes Celery queue `ai`. Models are fetched at build time, or by an init step into a named volume, never at request time, and the source and licence are recorded in `model_registry` on startup.
- The normal `worker` keeps queue `default`. Task routing sends `analyze_media`, `classify` and `match_report` to `ai`.
- **`apps/api/scripts/eval/`:**
  - A labelled-image manifest format (CSV: `path_or_url, label, source, license, attribution`).
  - A fetch script that downloads a small evaluation set of **openly licensed images (Wikimedia Commons, CC BY/BY-SA/CC0/PD only)** for the five categories plus `not_civic`, recording attribution. Images are **not** committed; the manifest is.
  - `eval_classification.py`: per-class precision/recall/F1, confusion matrix, threshold sweep and temperature fit.
  - `eval_dedup.py`: builds positive pairs by augmenting the same image (crop, rotate ±15°, brightness/contrast, JPEG quality, scale) and negative pairs from different images of the same category. Reports the visual-similarity distribution, ROC/PR, and precision/recall/false-merge rate at the configured thresholds.
  - Writes results to `docs/eval/phase-2-baseline.md`, with the date, model ID and dataset size. **These are baseline numbers on a small open dataset, not real-world performance** (PRD §3.2).

## I. Frontend (high level; details in the frontend brief)
- **Report flow:**
  - Request a classification once photos are uploaded. Pre-select the top suggestion on the category step, with a "Suggested" badge and plain-language confidence. Show a soft `not_civic` notice. Fall back silently when pending or failed. Send `classification_id`.
- **Confirmation and report detail:**
  - "Checking for similar reports" while matching is pending (poll).
  - Then either "Added to issue CP-… (N reports)" or "Created issue CP-…".
- **Staff:**
  - Review queue `/admin/review`: side-by-side comparison with the signal breakdown and the actions link / create new issue.
  - Issue detail:
    - priority card with factors and an override dialog
    - severity and an override dialog
    - category correction
    - merge dialog (search issues)
    - split dialog (select reports)
    - related issues
    - per-report match info with correct/incorrect feedback
    - redirect from merged issues
  - Queue: priority badge and default sort, severity and band filters.
  - Admin pages: matching config, priority config, AI models and quality (read-only tables).

## J. Seed additions (Backend)
- Synthetic places of interest: a few schools and hospitals inside the wards.
- Default `matching_config` and `priority_config`.
- Category `severity_rules`.
- Recompute severity and priority for the seeded issues.
- Create a handful of seeded **duplicate clusters**: two or three reports at nearly the same spot with near-identical placeholder images, linked to one issue. Also add two open review tasks, so the review queue has something to show.
- Mark the model registry with the fake model in development unless the AI worker has registered the real one.

## K. Details settled by the backend implementation
Everything above is implemented as written, except where this section is more specific. `apps/api/openapi.json` is the exact shape.

**Schema and pipeline**
- Tenant configs live in a `tenant_configs` table (RLS, one row per tenant and key), not in `tenants.settings`, which has no RLS. A tenant without a row gets the defaults. PUT replaces the whole document: a field left out goes back to its default.
- `issue_id` on a report is null exactly while `matching_status` is `pending` or `review` (a check constraint). Phase 1 reports became `new_issue`; Phase 1 severity/priority strings that named a level were kept as overrides, anything else was dropped.
- Category compatibility: same category 1.0; its parent, its children and its siblings 0.5. The matching advisory lock is per (tenant, root of the category's parent chain), so every compatible pair shares one lock. Merge, split, review resolution and category correction take the same locks, family locks first and then rows in id order.
- `analyze_media` runs as soon as a photo is processed. `match_report` embeds any photo still missing an embedding itself, retries every ~15 s while the model is unavailable, and matches without the visual signal once the report is older than 2 minutes. A Beat watchdog (every minute) re-queues reports pending for over a minute, applies that fallback to reports past the deadline, fails classifications pending past 30 s and computes priorities never computed.
- Signals JSON `reason`: `null`, `ai_unavailable` (fallback), `no_photos` (the new report has none) or `candidate_no_photos`. In fallback, `thresholds` also has `fallback_review`.
- Until `app/ai/phash.py`, `faces.py` and `prompts.py` exist, a 64-bit difference hash, a Gaussian blur and a generic "a photo of …" prompt stand in for them (`app/domains/ai/vision.py`).

**Classification (C)**
- The response also has `error` and `created_at`. `needs_manual` is also true while pending or failed. A classification still pending after 30 s reads as `failed` / `ai_unavailable`.
- A `classification_id` that isn't the caller's is `422 validation_error` at `["body", "classification_id"]`. The staff report view has `category_source`.

**Reports and review (D.4)**
- Every report view and `/users/me/reports` item has `matching_status`; `issue` is null while pending or in review. The owner's `issue` adds `report_count` and `unique_reporter_count`.
- The staff report view adds `match` (the deciding decision: the link made, else the best-ranked candidate) and `match_decisions` (every candidate, best-ranked first), each `{ id, report_id, candidate_issue_id, candidate_issue: { id, reference }, rank, score, signals, decision, model_id, decided_by, decided_at, feedback, feedback_note, feedback_at }`. The issue detail shows them on each report.
- Review task items: `{ id, created_at, status, resolution, resolved_issue_id, resolved_by, resolved_at, report, candidates: [{ match_decision_id, score, signals, decision, issue }] }`, in the standard page envelope; open tasks oldest first, resolved ones most recently resolved first. Candidates outside the caller's scope are left out. `link` must name one of the task's candidates (`422` otherwise); if that issue was merged since, the report goes to the survivor. Resolve returns the task. Feedback returns the decision and replaces earlier feedback.

**Timeline**
- New event types: `report_linked`, `merged`, `merged_into`, `split`, `category_changed`, `severity_changed`, `priority_changed`. Only `merged` is public (on the survivor, rendered as "Combined with another report of the same problem"); the rest are internal. Staff timeline events add `related_issue: { id, reference } | null` and `data` (moved report ids, old and new values).

**Merge, split, related (D.5)**
- Merge, split, severity, priority and category changes return the updated issue detail (split: `{ source, target }`). A blank reason is `422 reason_required`; a stale version `409 version_conflict`.
- Merging an issue whose own merged issues exist re-points those to the survivor, so `merged_into` is always one hop. A merged issue has no allowed transitions and scores 0.
- A split's new issue takes its location, address and ward from the **oldest** moved report. Reports not on the issue: `422 validation_error` with `details.report_ids`.
- Acting on a merged issue (split source or target, overrides, category, related) is `422 issue_merged`.
- `POST /issues/{id}/related` returns `201 { issue, note }`; an existing pair is `409 conflict`.

**Severity and priority (E, F)**
- Within `near_places`, and within `report_count_raise`, rules are tiers: only the largest matching raise counts; the two groups add up, capped at `critical`. `severity` is `{ level, source, reason }` on lists and detail. Categories accept and return `ai_prompts` and `severity_rules` (rules may only name the category's fields).
- `priority` is null only until an issue is first computed (within a minute of a migration). Recomputing never changes `version` or `updated_at`; overrides do. `resolved` issues still score; only rejected, closed and merged issues score 0.
- `sort=-priority` orders by the effective band, then the score, uncomputed last. GeoJSON feature properties add `severity` and `priority_band` (effective); both filters work on the map too. Changing the priority config, or a category's severity rules, recomputes the affected issues in the background.

**Governance (G)**
- `GET /admin/ai/models`: `{ items: [{ model_id, task, name, version, source, license, deployed_at, intended_use, metrics, active }] }`, newest first; `active` is the most recently deployed model of its task.
- `GET /admin/ai/quality?from&to` (whole days in Asia/Kolkata, default the last 30): `{ from, to, classifications: { done, failed, accepted_by_category: { code: n }, corrected_by_category: { code: n } }, matching: { auto_linked, sent_to_review, new_issue }, reviews: { linked, new_issue }, auto_link_feedback: { correct, incorrect } }`.

**New error codes**
| Code | Status | When |
|---|---|---|
| `invalid_merge` | 422 | Merging into itself or into a merged issue, or merging an already merged one (`details.reason`) |
| `cannot_empty_issue` | 422 | A split would move every report |
| `issue_merged` | 422 | Changing a merged issue |
| `reason_required` | 422 | Also for merge, split, overrides and category correction |

**Seed (J)**: two more synthetic citizens, `+919000000006` and `+919000000007`, so the duplicate clusters have distinct reporters. Five cluster reports are linked by the real matcher (one cluster has the same citizen twice), two wait in review.
