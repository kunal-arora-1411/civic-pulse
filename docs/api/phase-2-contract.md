# Phase 2 contract: the AI layer

This builds on the Phase 0 and Phase 1 contracts. All their conventions still apply: tenancy, the error envelope, pagination, idempotency, `[lng, lat]` order, UTC timestamps and `_i18n` objects. If any side needs to change this file, change it in the same commit and say so. `apps/api/openapi.json` is the exact shape of every endpoint below.

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
| `fake.py`: `FakeVisionModel`, `FakeZeroShotClassifier`, `FakeFaceDetector` | **Backend** | Deterministic and dependency-free (numpy + Pillow only). The fake model derives a stable unit vector from the image's downscaled pixels, so identical or near-identical images get cosine ≈ 1 and unrelated ones a low score. The fake classifier reads a `CP_TEST_LABEL` value (a PNG text chunk or a JPEG comment, e.g. `pothole` or `pothole:0.40`) so tests can control the outcome. |
| `phash.py`: `perceptual_hash(image) -> int` | **ML** | 64-bit DCT pHash using numpy only (no scipy). Robust to recompression and resizing. Unsigned in Python, stored signed in Postgres (`bigint`), converted at the boundary. |
| `clip.py`: `ClipOnnxModel` | **ML** | Real `VisionModel` on ONNX Runtime, CPU only: CLIP ViT-B/32 (`Xenova/clip-vit-base-patch32`, MIT), vision and text encoders plus the tokenizer. **No torch at runtime.** Repo, revision, file hashes and licence are pinned in `apps/api/models.lock.json`. |
| `zero_shot.py`: `PromptZeroShotClassifier` | **ML** | Softmax over category prompt embeddings, with a temperature calibrated on the evaluation set. Returns the reserved `unknown` code (confidence = 1 − top score) when the top score is below the configured threshold. |
| `faces.py`: `YuNetFaceDetector` + `blur_regions(image, boxes) -> Image` | **ML** | OpenCV YuNet ONNX (MIT, pinned in the lock). Strong blur with padding around each box. |
| `registry.py`: `get_vision_model()`, `get_classifier()`, `get_face_detector()` | **ML** (real), **Backend** (fake) | Chosen by settings: `AI_PROVIDER=onnx|fake` (default `fake`: tests and the API container; `onnx` in the AI worker) and `AI_MODEL_DIR` (default `/models`). Model instances are cached per process. |
| `prompts.py`: `DEFAULT_PROMPTS: dict[str, list[str]]` | **ML** | 3–6 English prompts each for `pothole`, `waste`, `waterlogging`, `streetlight`, `drainage`, plus `not_civic` (selfies, food, screenshots, documents, indoor scenes…). A category may override its prompts with `ai_prompts` (B.1). |

`AI_FACE_BLUR=true|false` (default true in the compose stack). Every service must agree on it: with blurring on, a photo stays `processing`, with no public copies, until the AI worker's face check renders the copies with faces blurred and marks it ready. An unblurred public copy never exists.

## B. Data model (Backend owns the migrations)

### B.1 Category additions
- `ai_prompts: list[str] | null`, overriding `DEFAULT_PROMPTS[code]`.
- `severity_rules`: see section E. Rules may only name the category's own fields.
- `parent_id` (already present) feeds category compatibility (D.2).
- Categories accept and return both new fields.

### B.2 New tables (tenant-scoped with RLS unless noted)
- `model_registry`: `model_id`, `task` (`embedding|classification|face_detection`), `name`, `version`, `source` (repo + revision), `license`, `deployed_at`, `intended_use`, `metrics` (JSON). Global rows: the table holds no tenant data, so it skips RLS (the migration says why). The AI worker registers its models on start-up.
- `media_embeddings`: `media_id`, `model_id`, `embedding vector(512)`, `phash bigint`, `created_at`. HNSW index (cosine) on `embedding`. Unique on (`media_id`, `model_id`). A model with another dimension needs a new migration (new column or table) and a re-index ([runbook](../runbooks/switch-vision-model.md)).
- `classifications`: `id`, `requested_by`, `media_ids[]`, `model_id`, `status` (`pending|done|failed`), `scores` (JSON list of `{code, confidence}`), `top_code`, `top_confidence`, `error`, timestamps.
- `reports` gets `classification_id` (nullable), `category_source` (`citizen|ai_accepted|ai_corrected|operator`) and `matching_status` (`pending|linked|review|new_issue`). `issue_id` is null exactly while `matching_status` is `pending` or `review` (a check constraint). Phase 1 reports became `new_issue`.
- `match_decisions`: `id`, `report_id`, `candidate_issue_id`, `rank`, `score`, `signals` (JSON, D.3), `decision` (`auto_linked|sent_to_review|rejected_candidate|chosen_by_reviewer|not_chosen`), `model_id`, `decided_by` (null = system), `created_at`, `decided_at`, `feedback` (`correct|incorrect|null`), `feedback_by`, `feedback_at`, `feedback_note`.
- `review_tasks`: `id`, `report_id` (unique while open), `status` (`open|resolved`), `resolution` (`linked|new_issue`), `resolved_issue_id`, `resolved_by`, `resolved_at`, `created_at`.
- `issue_relations`: `issue_id`, `related_issue_id`, `note`, `created_by`, `created_at`. One row per unordered pair.
- `civic_issues` gets:
  - `merged_into_id` (nullable self-reference)
  - `severity` (enum `low|medium|high|critical`), `severity_source` (`rule|override`), `severity_reason`
  - `priority_score` (0–100 numeric), `priority_band` (computed), `priority_override_band`, `priority_override_reason`, `priority_factors` (JSON), `priority_computed_at`
  - These replace the Phase 1 string `severity`/`priority` columns. Phase 1 values that named a level were kept as overrides; anything else was dropped.
- `places_of_interest`: `id`, `kind` (`school|hospital|bus_stop|market|other`), `name`, `geom point`. Seeded synthetically; admin CRUD comes later.
- `tenant_configs`: one row per tenant and key (`matching_config`, `priority_config`), with RLS (not `tenants.settings`, which has none). A tenant without a row gets the defaults.

## C. Category suggestion during reporting (FR-020 to FR-022)

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/ai/classifications` | `report:create` | Body `{ media_ids: [uuid] }`. The media must be the caller's and completed. The API queues an AI task and **waits up to 4 s** for it. Returns `200` with the classification if done, otherwise `202` with `status: "pending"`. If the AI is unavailable, returns `200` with `status: "failed"`, `error: "ai_unavailable"`; the client then just asks for manual selection. |
| GET | `/api/v1/ai/classifications/{id}` | owner | Poll every 1–2 s, giving up after ~15 s. A classification still pending after 30 s reads as `failed` / `ai_unavailable`, and the watchdog (D.1) records it so. |

```json
{
  "id": "uuid", "status": "done", "model_id": "clip-vit-b32@onnx-1",
  "suggestions": [ { "category_id": "uuid", "code": "pothole", "confidence": 0.82 },
                   { "category_id": "uuid", "code": "drainage", "confidence": 0.09 } ],
  "not_civic": false, "needs_manual": false, "error": null, "created_at": "..."
}
```
- `suggestions` covers active tenant categories only, up to 3.
- `not_civic` is true when that reserved code wins. The client shows a soft warning but never blocks the citizen (PRD §8.6).
- `needs_manual` is true when the top category confidence is below `matching_config.classification_threshold` (default 0.45), when the result is `unknown`, and while the classification is pending or failed.

**Report creation additions:** `POST /reports` accepts an optional `classification_id`. The web app sends it only when the citizen was shown that classification's suggestion (pre-selected on the category step). It leaves it out after a failure, a timeout, `needs_manual` or `not_civic`, so a choice is never recorded as accepting or correcting a suggestion the citizen didn't see. A `classification_id` that isn't the caller's is `422 validation_error` at `["body", "classification_id"]`. The server sets `category_source`, which the staff report view shows:
- `ai_accepted`: the chosen category equals the top suggestion
- `ai_corrected`: it differs (this becomes a correction label, FR-021)
- `citizen`: no classification

**Operator correction:** `PATCH /api/v1/issues/{id}/category { category_id, reason, version }` (`issue:update`). This sets `category_source = operator` on the issue's reports, recomputes severity and priority, and is audited. Like the status change it returns `200` with the updated issue detail; a blank reason is `422 reason_required`.

## D. Duplicate matching (FR-024 to FR-037)

### D.1 Pipeline
1. **`POST /reports`** still validates and saves everything in one transaction, but **no longer creates an issue**. The report is stored with `issue_id = null` and `matching_status = pending`, and a `match_report` task is queued after commit. The response returns at once with `matching_status: "pending"` and `issue: null`.
2. **`analyze_media`** (AI queue) runs as soon as a photo is processed. It computes the embedding and pHash and stores them in `media_embeddings`, reusing them if they already exist for this model (the classification step may have computed them). When `AI_FACE_BLUR` is on, it also renders the `display` and `thumb` copies with faces blurred and publishes the photo. Originals are never altered.
3. **`match_report`** (AI queue) embeds any photo still missing an embedding itself, then runs D.2 and applies the decision **inside one transaction holding an advisory lock** per (tenant, root of the category's parent chain), so every compatible pair of categories shares one lock. Candidates are re-read under the lock. This is the FR-036 guarantee: concurrent duplicates never create two issues.
4. **Fallback when the AI is unavailable.** While the model is unavailable, `match_report` retries about every 15 s. Once the report is older than 2 minutes (`MATCHING_FALLBACK_AFTER_SECONDS`), it is matched without the visual signal and never linked automatically: if any candidate scores ≥ `fallback_review_threshold` (0.40) on the remaining signals a review task opens, otherwise a new issue. `signals.visual` is `null` and `reason` is `"ai_unavailable"`. A Beat watchdog on the default queue runs every minute: it re-queues reports pending for over a minute and applies the fallback itself to reports past the deadline, so it works with the AI worker down. It also fails classifications pending past 30 s and computes priorities never computed.
5. After a decision: link or create the issue, keep counts correct (`report_count`, and `unique_reporter_count`, which a reporter already on the issue doesn't increase), write timeline and audit events, and recompute priority.

Merge, split, review resolution and category correction take the same family locks: family locks first, then issue rows in id order.

### D.2 Candidates and score
- **Candidates:** issues not merged away, in the same tenant, within `category.dedup.radius_m` (PostGIS geography distance), with a compatible category, and either open or closed/resolved within `category.dedup.window_days`. At most 10, ordered by distance.
- **Signals**, each in [0, 1]:
  - `geo = exp(-distance_m / radius_m)`
  - `visual` = the highest cosine similarity across all (new photo × candidate photo) pairs for the active model, clamped to [0, 1], or `null` when there are no embeddings. Same-photo boost: a pHash Hamming distance ≤ 6 sets `visual = 1` and `same_photo = true`.
  - `category`: 1.0 for the same category; 0.5 for its parent, its children and its siblings; otherwise not a candidate.
  - `time = exp(-age_days / window_days)`, where age is measured from the candidate's last report.
- **Score:** `w_geo·geo + w_visual·visual + w_category·category + w_time·time`. Default weights 0.40 / 0.40 / 0.10 / 0.10. If `visual` is null, re-normalise over the remaining weights.
- **Decision** (configurable thresholds, defaults shown):
  - **Auto-link:** score ≥ 0.85 **and** visual ≥ `visual_min` **and** distance ≤ radius **and** `matching_config.auto_link_enabled` (default true). Never on distance alone (AC-05).
  - **Review:** best score ≥ 0.60, or any score ≥ 0.85 that failed the auto-link checks above.
  - **New issue:** anything else.
- `visual_min` belongs to the model. When the tenant leaves it `null` (the default), the active vision model's own floor applies (`model_registry.metrics.matching.visual_min`: 0.92 for the shipped CLIP model, from the [evaluation](../eval/phase-2-baseline.md)). A number overrides it.
- Every candidate considered gets a `match_decisions` row, so the decision can always be explained (FR-037).

### D.3 Signals JSON
```json
{ "distance_m": 18.4, "radius_m": 30, "geo": 0.54, "visual": 0.91, "same_photo": false,
  "category": 1.0, "time": 0.93, "age_days": 2.1, "weights": { "geo": 0.4, "visual": 0.4, "category": 0.1, "time": 0.1 },
  "thresholds": { "auto": 0.85, "review": 0.6, "visual_min": 0.92 }, "reason": null }
```
`reason` is `null`, `ai_unavailable` (fallback), `no_photos` (the new report has none) or `candidate_no_photos`. In fallback, `thresholds` also has `fallback_review`.

### D.4 Endpoints
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/review-tasks` | `issue:triage` | `?status=open` (default) or `resolved`. Jurisdiction-scoped, in the standard page envelope; the web app reads `total` for the open count in the nav. Open tasks oldest first, resolved ones most recently resolved first. |
| GET | `/api/v1/review-tasks/{id}` | `issue:triage` | Same shape as a list item |
| POST | `/api/v1/review-tasks/{id}/resolve` | `issue:triage` | `{ action: "link", issue_id }` or `{ action: "new_issue" }`. `link` must name one of the task's candidates (`422` otherwise); if that issue was merged since, the report goes to the survivor. Applies D.1 step 5 under the same lock. The chosen decision is marked `chosen_by_reviewer`, the others `not_chosen` (FR-035 feedback). Returns the resolved task. A task that's already resolved returns `409 conflict`. |
| POST | `/api/v1/match-decisions/{id}/feedback` | `issue:triage` | `{ correct: bool, note? }`. Mainly used on auto-links, from the issue detail page. Returns the decision; new feedback replaces earlier feedback. |
| GET | `/api/v1/reports/{id}` | (as before) | See "Report views" below. |
| GET | `/api/v1/users/me/reports` | (as before) | Items add `matching_status`, and their `issue` is `null` until the report is placed. |

**Review task items:** `{ id, created_at, status, resolution, resolved_issue_id, resolved_by, resolved_at, report: <staff report view>, candidates: [ { match_decision_id, score, signals, decision, issue: <issue list item> } ] }`, best candidate first. Candidates outside the caller's scope are left out.

**Report views.** Every report view has `matching_status`. `issue` is `null` while it is `pending` or `review`, and the citizen sees "Checking for similar reports". The owner view's `issue` also carries `report_count` and `unique_reporter_count`, so the confirmation can say how many people reported the problem. The staff view adds:
- `match`: the deciding decision (the link made, else the best-ranked candidate) as `{ match_decision_id, decision, score, signals } | null`
- `match_decisions`: every candidate considered, best-ranked first, each `{ id, report_id, candidate_issue_id, candidate_issue: { id, reference }, rank, score, signals, decision, model_id, decided_by: { id, display_name } | null, decided_at, feedback, feedback_note, feedback_at }`

The issue detail shows the same `match_decisions` on each of its reports. The web app uses them to show how each report got onto the issue and to collect feedback on auto-links.

### D.5 Merge, split and related issues (FR-033, FR-034, FR-060)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/issues/{id}/merge` | `issue:merge` | `{ source_issue_ids: [uuid], reason, version }`. `{id}` is the surviving issue. Source issues get `merged_into_id = id`, keep their reference and history, and drop out of lists and the map. Their reports move to the survivor, and counts are recomputed from the actual reports. The survivor keeps its own status. Issues already merged into a source are re-pointed to the survivor, so `merged_into` is always one hop. Timeline entries go on both sides, plus an audit event, and priority is recomputed. Returns `200` with the survivor's detail. |
| POST | `/api/v1/issues/{id}/split` | `issue:merge` | `{ report_ids: [uuid], target: { "new_issue": true } \| { "issue_id": uuid }, reason, version }`. A new issue copies the category and takes its location, address and ward from the **oldest** moved report, starting at status `reported`. Reports not on the issue are `422 validation_error` with `details.report_ids`. Returns `{ source: <issue detail>, target: <issue detail> }`. |
| GET | `/api/v1/issues/{id}` | | A merged issue returns `200` with `merged_into: { id, reference }`, so the client can redirect. Detail also adds `related: [ { issue: <list item>, note } ]`. |
| POST | `/api/v1/issues/{id}/related` | `issue:update` | `{ issue_id, note? }`, audited. Returns `201 { issue, note }`; an existing pair is `409 conflict`. |
| DELETE | `/api/v1/issues/{id}/related/{other_id}` | `issue:update` | `204`, audited |

A merged issue has no allowed status transitions and scores 0. Acting on one (split source or target, overrides, category, related) is `422 issue_merged`. Every action here that takes a reason returns `422 reason_required` for a blank one, and `409 version_conflict` for a stale `version`.

Citizens whose reports moved see the new issue in their report detail. The public timeline says "Combined with another report of the same problem", without staff names.

**Timeline event types added in Phase 2.** Staff see all of them; citizens only the public ones. Where the action took a reason, it's in the event's `reason`. Staff timeline events also add `related_issue: { id, reference } | null` and `data` (moved report ids, old and new values).

| `type` | Visibility | Written when |
|---|---|---|
| `report_linked` | internal | A report joins the issue, automatically or through a review task |
| `merged` | public | Other issues were merged into this one ("Combined with another report of the same problem") |
| `merged_into` | internal | This issue was merged into another |
| `split` | internal | Reports were moved out of, or into, this issue |
| `category_changed` | internal | An operator corrected the category |
| `severity_changed` | internal | A severity override was set or cleared |
| `priority_changed` | internal | A priority override was set or cleared |

Adding or removing a related-issue link is audited (`issue.related_added`, `issue.related_removed`) but writes no timeline event.

**New error codes**
| Code | Status | When |
|---|---|---|
| `invalid_merge` | 422 | Merging into itself or into a merged issue, or merging an already merged one (`details.reason`) |
| `cannot_empty_issue` | 422 | A split would move every report |
| `issue_merged` | 422 | Changing a merged issue |
| `reason_required` | 422 | Also for merge, split, overrides and category correction |

## E. Severity (FR-038)
- `category.severity_rules`:
  ```json
  { "base": "medium",
    "field_rules": [ { "field": "size", "equals": "large", "set": "high" } ],
    "near_places": [ { "kinds": ["school","hospital"], "within_m": 150, "raise_by": 1 } ],
    "report_count_raise": [ { "unique_reporters_gte": 5, "raise_by": 1 } ] }
  ```
  Levels run `low < medium < high < critical`. When several field rules match, the highest wins. Within `near_places`, and within `report_count_raise`, rules are tiers: only the largest matching raise counts. The two groups add up, capped at `critical`.
- Computed whenever an issue's reports or category change. A `severity_source = override` value stays until it's cleared.
- `severity` is `{ level, source, reason }` on lists and detail; `reason` carries the override's reason while there is one.
- `PATCH /api/v1/issues/{id}/severity { severity: level | null, reason, version }` (`issue:update`). `null` clears the override. A reason is required when setting one. Audited, with a timeline event. Returns `200` with the updated issue detail.

## F. Priority (FR-039 to FR-044, PRD §8.4)
- Rules only, no ML. Tenant `priority_config` (defaults shown):
  ```json
  { "weights": { "severity": 40, "reporters": 20, "age": 15, "recurrence": 15, "near_places": 10 },
    "severity_points": { "low": 0.1, "medium": 0.4, "high": 0.75, "critical": 1.0 },
    "reporters_saturation": 10, "age_saturation_days": 30,
    "recurrence": { "radius_m": 50, "lookback_days": 180, "saturation": 3 },
    "bands": { "critical": 80, "high": 60, "medium": 35 } }
  ```
- Each factor is normalised to [0, 1] and multiplied by its weight. `score` is the sum (0–100), and the band comes from the thresholds (below `medium` means `low`). A `rejected` or `closed` issue, or a merged one, scores 0; `resolved` issues still score.
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
- **Recomputed** on report link/unlink, merge/split, severity or category change, status change, and nightly for ageing (Celery Beat). Changing the priority config, or a category's severity rules, recomputes the affected issues in the background. Recomputing never changes `version` or `updated_at`; overrides do.
- **Override:** `PATCH /api/v1/issues/{id}/priority { band: "critical|high|medium|low" | null, reason, version }` (`issue:set_priority`). The effective band is the override when present. Audited, with a timeline event. Returns `200` with the updated issue detail.

**Issue list item and detail change to:**
```json
"severity": { "level": "high", "source": "rule", "reason": null },
"priority": { "score": 67.5, "band": "high", "computed_band": "high", "overridden": false, "override_reason": null, "factors": [ ... ] }
```
- `priority` is `null` only until an issue is first computed (within a minute of a migration, by the watchdog).
- `factors` appear on the detail only.
- The issue list adds `sort=-priority` (the new default for staff), which orders by the effective band, then the score, uncomputed last. It also adds the filters `severity` and `priority_band` (both repeatable).
- `GET /issues/geojson` takes the same two filters, and each feature's properties add `severity` and `priority_band` (the effective band, or `null` while unscored), so the staff map can shape its markers by band.

## G. Configuration and governance
| Method | Path | Permission |
|---|---|---|
| GET / PUT | `/api/v1/admin/matching-config` | `config:read` / `config:manage` |
| GET / PUT | `/api/v1/admin/priority-config` | `config:read` / `config:manage` |
| GET | `/api/v1/admin/ai/models` | `config:read` |
| GET | `/api/v1/admin/ai/quality` | `config:read` |

- `matching_config` JSON: `{ auto_link_enabled, weights, thresholds: { auto, review, visual_min }, classification_threshold, fallback_review_threshold }`. Validated, with sane bounds. PUT replaces the whole document: a field left out goes back to its default. Every PUT is audited.
- `GET /admin/ai/models`: `{ items: [ { model_id, task, name, version, source, license, deployed_at, intended_use, metrics, active } ] }`, newest first. `active` is true for the most recently deployed model of its task.
- `GET /admin/ai/quality?from&to` (whole days in Asia/Kolkata, default the last 30): `{ from, to, classifications: { done, failed, accepted_by_category: { code: n }, corrected_by_category: { code: n } }, matching: { auto_linked, sent_to_review, new_issue }, reviews: { linked, new_issue }, auto_link_feedback: { correct, incorrect } }`. It feeds a simple table now; fuller dashboards come in Phase 5.

## H. AI worker and evaluation (ML engineer)
- **`ai-worker` compose service:** image built from `infra/ai-worker/Dockerfile`, which installs `apps/api` with the `ai` extra and bakes in the weights pinned by `models.lock.json` at build time (never fetched at request time). It is the only consumer of Celery queue `ai`, so every embedding in the database comes from one model. It records the models' source and licence in `model_registry` on start-up.
- The normal `worker` keeps queue `default`. Task routing sends `analyze_media`, `classify` and `match_report` to `ai`.
- `infra/docker-compose.fake-ai.yml` runs the `ai` queue with the fake models instead (no weights), for quick local work.
- **`apps/api/scripts/eval/`:**
  - A labelled-image manifest (`manifest.csv`: path or URL, label, source, licence, attribution, licence URL, sha256, split).
  - Fetch scripts for **openly licensed images** (Wikimedia Commons, and Flickr through Openverse; CC BY, CC BY-SA, CC0 and public domain only), recording attribution. Images are **not** committed; the manifest is.
  - `eval_classification.py`: per-class precision/recall/F1, confusion matrix, threshold sweep and temperature fit.
  - `eval_dedup.py`: positive pairs by augmenting the same image (crop, rotate ±15°, brightness/contrast, JPEG quality, scale), negative pairs from different images of the same category. Reports the visual-similarity distribution, ROC/PR, and precision/recall/false-merge rate at the configured thresholds.
  - Results go to [`docs/eval/phase-2-baseline.md`](../eval/phase-2-baseline.md), with the date, model ID and dataset size. **These are baseline numbers on a small open dataset, not real-world performance** (PRD §3.2).

## I. Frontend
- **Report flow:**
  - Request a classification once photos are uploaded. Pre-select the top suggestion on the category step, with a "Suggested" badge and plain-language confidence. Show a soft `not_civic` notice. Fall back silently to a manual choice when pending, failed or `needs_manual`. Send `classification_id` only as described in C.
- **Confirmation and report detail:**
  - "Checking for similar reports" while matching is pending or in review (poll).
  - Then either "Added to issue CP-… (N reports)" or "Created issue CP-…".
- **Staff:**
  - Review queue `/admin/review`: side-by-side comparison with the signal breakdown and the actions link / create new issue, with keyboard shortcuts. The open count shows in the nav.
  - Issue detail:
    - priority card with factors and an override dialog
    - severity and an override dialog
    - category correction
    - merge dialog (search issues)
    - split dialog (select reports)
    - related issues
    - per-report match info with correct/incorrect feedback
    - redirect from merged issues
  - Queue: priority badge and default sort, severity and band filters. Staff map markers by band.
  - Admin pages: matching config, priority config, AI models and quality (read-only tables).

## J. Seed additions (Backend)
- Synthetic places of interest: a few schools and hospitals inside the wards.
- Default `matching_config` and `priority_config`.
- Category `severity_rules`.
- Severity and priority computed for the seeded issues.
- Two more synthetic citizens, `+919000000006` and `+919000000007`, so the duplicate clusters have distinct reporters.
- Seeded **duplicate clusters** at nearly the same spot with near-identical placeholder images: five cluster reports linked by the real matcher (one cluster has the same citizen twice), and two that wait in the review queue.
- The seed runs in the `ai-worker` container, so seeded photos are embedded with the same model as everything else. Without the real AI worker, the model registry shows the fake model.
