# Phase 1 API contract: core reporting loop

This builds on [`phase-0-contract.md`](phase-0-contract.md). All its conventions still apply: tenant resolution, the error envelope, pagination, `X-Request-ID`, `Idempotency-Key` and phone formats. It describes what `apps/api` implements and `apps/web` uses; [`apps/api/openapi.json`](../../apps/api/openapi.json) is the precise, generated form. If either side needs to change it, change this file in the same commit and say so.

**Phase 1 goal:** a citizen submits a report with photos and location. Each report creates its own civic issue (duplicate matching arrives in Phase 2). Staff see issues in a queue and on a map, and move them through the lifecycle.

## Conventions added in Phase 1

### Permissions in use
Already defined in Phase 0: `report:create`, `report:read_own`, `report:read`, `issue:read`, `issue:triage`, `issue:update`, `config:read`, `config:manage`. Staff access to issues and reports is limited by the principal's jurisdiction scope (see [Scope](#scope)).

### Localised text
Fields ending in `_i18n` are objects keyed by locale, for example `{ "en": "Pothole", "hi": "गड्ढा" }`. The API returns the full object. The client picks the user's locale and falls back to `en`.

### Timestamps and coordinates
- Every timestamp is returned in UTC (`2026-11-24T02:42:00Z`), including a photo's `captured_at`. Clients show them in the user's time zone (IST for Phase 1). Where a date is an input (`from`/`to` filters), it's a whole day in Asia/Kolkata.
- Coordinates in GeoJSON and map settings are `[lng, lat]`, following GeoJSON order. Request and response bodies that name them use `lat` and `lng` fields.

### Scope
Staff see the issues and reports in the jurisdiction subtree of their grants: a role scoped to a zone covers its wards, and a role with no jurisdiction covers the whole tenant. Issues with no ward are visible only to tenant-wide staff.

A grant can also carry a department (PRD FR-006: tenant, department and geography). A department grant covers the issues whose category's default department is that department (a subcategory with none inherits its parent's); an issue with no category is visible only to grants without a department. This applies to every role, but in practice only supervisors are given departments: operators triage across categories and municipal admins are tenant-wide, so both are granted without one. Each grant is its own rule (its jurisdiction AND its department) and a caller sees the union of their grants. The issue list, the map, issue detail and every issue action use the same rule; report visibility is still by jurisdiction only.

Anything outside a caller's scope answers `404 not_found`, exactly like something that doesn't exist, so nothing about its existence leaks.

### New error codes
| Code | Status | When |
|---|---|---|
| `unsupported_media_type` | 422 | Upload content type isn't JPEG, PNG or WebP |
| `file_too_large` | 422 | Upload is over the size limit |
| `rate_limited` | 429 | `POST /reports`: the citizen has filed too many reports, by default 10 an hour or 30 a day (settings `REPORT_MAX_PER_HOUR`, `REPORT_MAX_PER_DAY`, overridable per tenant — see [Report limits](#report-limits)). `Retry-After` and `details.retry_after` give the seconds to wait. Idempotent replays don't count, and if the limiter's store is down submissions are allowed rather than refused. |
| `too_many_uploads` | 429 | The caller already holds 20 unexpired, incomplete uploads (`details.limit`; no `Retry-After`) |
| `upload_verification_failed` | 422 | The uploaded object doesn't match what was declared (`details.reason`) |
| `out_of_jurisdiction` | 422 | The report's point is outside the city |
| `evidence_required` | 422 | Wrong number of photos for the category, or no photo and too short a description |
| `invalid_media` | 422 | A `media_ids` entry can't be attached (`details.media`) |
| `version_conflict` | 409 | The issue changed since the caller read it (`details.version`) |
| `invalid_transition` | 422 | The status move isn't allowed for this caller (`details.allowed_transitions`) |
| `reason_required` | 422 | The status move needs a reason (`details.to_status`) |

Field-level problems are `422 validation_error` with `details.errors`, each with a `loc` such as `["body", "details", "size"]`.

### Report limits
| Method | Path | Permission |
|---|---|---|
| GET / PUT | `/api/v1/admin/report-limits-config` | `config:read` / `config:manage` |

`{ max_per_hour, max_per_day }`, both whole numbers of at least 1. A tenant with no document uses `REPORT_MAX_PER_HOUR`/`REPORT_MAX_PER_DAY` (10 and 30 by default); PUT replaces the whole document, a field left out goes back to its own schema default (10/30, not necessarily the settings value), and every PUT is audited as `config.report_limits_updated`.

### Audit actions
`category.created`, `category.updated`, `report.created`, `issue.created`, `issue.status_changed`, `config.report_limits_updated`, each written in the same transaction as the change.

---

## 1. Tenant (extended)
`GET /api/v1/tenants/current` adds the city's map view:
```json
{ "...": "...", "map": { "center": [77.59, 12.97], "zoom": 12, "bounds": [77.55, 12.93, 77.63, 13.01] } }
```
- `bounds` is the bounding box of the tenant's city jurisdiction (`[minLng, minLat, maxLng, maxLat]`).
- `center` is the city's centroid when that lies inside the city, otherwise a point that does. `zoom` is derived from the bounds (12 for the seeded city).
- `map` is `null` for a tenant without boundary geometry. The web maps then start over all of India at zoom 5 and say why.

## 2. Categories
```json
{
  "id": "uuid", "code": "pothole", "parent_id": null,
  "name_i18n": { "en": "Pothole / road damage", "hi": "गड्ढा / सड़क क्षति" },
  "description_i18n": { "en": "...", "hi": "..." },
  "icon": "construction",
  "evidence": { "min_photos": 1, "max_photos": 5 },
  "fields": [
    { "key": "road_name", "type": "text", "required": false, "label_i18n": {...}, "options": null },
    { "key": "size", "type": "select", "required": false, "label_i18n": {...},
      "options": [{ "value": "small", "label_i18n": {...} }, { "value": "large", "label_i18n": {...} }] }
  ],
  "default_department_id": "uuid|null",
  "dedup": { "radius_m": 30, "window_days": 30 },
  "sort_order": 10, "is_active": true
}
```
- `icon` is a lucide icon name. `dedup` is stored now and used from Phase 2 onward.
- Field `type` is one of `text`, `number`, `select`, `boolean`. Keys match `^[a-z][a-z0-9_]{0,39}$` and are unique; `label_i18n.en` is required; at most 20 fields. `options` is required (with unique values) for `select` and `null` for every other type.
- `evidence.max_photos` is at most 10.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/categories` | `X-Tenant` or bearer | Active categories only, ordered by `sort_order`, as a **plain JSON array** (no page envelope): the report form needs the whole list. |
| GET | `/api/v1/admin/categories` | `config:read` | Includes inactive categories. Standard page envelope. Filter `is_active`; `sort`: `sort_order` (default), `code`, `created_at`. |
| POST | `/api/v1/admin/categories` | `config:manage` | Create, `201`. A duplicate `code` is `409 conflict`. Audited. |
| PATCH | `/api/v1/admin/categories/{id}` | `config:manage` | Partial update, including `is_active` and `fields`. Only `parent_id` and `default_department_id` accept `null`. Re-parenting into a cycle is `422`. Audited. |

The web app treats `code` as permanent once a category exists, because stored reports refer to it.

## 3. Media upload
Uploads go directly to object storage with pre-signed URLs. The API never streams image bytes on upload.

**Step 1: create an upload.** `POST /api/v1/media/uploads` (requires `report:create` or `evidence:upload`)
```json
{ "purpose": "report_evidence", "content_type": "image/jpeg", "size_bytes": 482113, "checksum_sha256": "hex" }
```
Returns `201`:
```json
{ "upload_id": "uuid", "method": "PUT", "url": "http://localhost:9000/...signed...", "headers": { "Content-Type": "image/jpeg" }, "expires_in": 600, "max_size_bytes": 10485760 }
```
- Allowed types: `image/jpeg`, `image/png`, `image/webp`; otherwise `422 unsupported_media_type`. Maximum 10 MB (configurable); otherwise `422 file_too_large`.
- Each user may hold at most 20 incomplete uploads whose URL hasn't expired; the next is `429 too_many_uploads`.

**Step 2: upload the bytes.** The client `PUT`s the file to `url` with exactly the returned `headers`. The signature covers `Content-Type` **and `Content-Length`**, so the body must be exactly `size_bytes` long; storage answers `403` to anything else, including an expired URL. Browsers set `Content-Length` themselves. The URL is signed for the public storage host, and storage allows the web origins with CORS.

**Step 3: complete the upload.** `POST /api/v1/media/uploads/{upload_id}/complete`, with no body. The server checks that the object exists, that its size and checksum match, and that the bytes really are an image of the declared type (not trusting the header).
- On success, `200` with a media asset:
  ```json
  { "id": "uuid", "status": "processing", "content_type": "image/jpeg", "width": 3024, "height": 4032,
    "variants": { "thumb": null, "display": null }, "captured_at": "2026-11-24T02:42:00Z" }
  ```
  The asset's `id` is what a report lists in `media_ids`. `captured_at` comes from EXIF when present. `width`/`height` are as displayed (EXIF orientation applied).
- On failure, `422 upload_verification_failed` with `details.reason`: `object_missing`, `size_mismatch`, `checksum_mismatch`, `content_type_mismatch`, `not_an_image` `image_too_large` (over 50 megapixels) or `malware_detected` (the ClamAV scan, when one is configured, found a signature). The object is deleted and the upload stays failed: the client starts a new one.
- When a scanner is configured but can't be reached, `503 service_unavailable`. The upload stays `pending` and completing it again later works.
- Completing an already verified upload is safe and returns it again.

**Processing.** A background job reads the EXIF capture time and GPS (stored privately) and makes `display` (max 1600 px, WebP) and `thumb` (max 400 px, WebP) copies with **all metadata removed**. The asset becomes `ready`, or `failed` with the reason recorded. The original keeps its metadata and is visible to staff only. Processing usually finishes within seconds; an asset stuck in `processing` for 15 minutes is queued again by housekeeping.

**Reading media.** Media appears embedded in report and issue responses as:
```json
{ "id": "uuid", "status": "ready", "width": 1200, "height": 1600,
  "thumb_url": "signed GET url|null", "display_url": "signed GET url|null", "original_url": "signed GET url|null",
  "captured_at": "...|null" }
```
- `thumb_url` and `display_url` are `null` until the asset is `ready`. Pages that show photos refetch every few seconds while any are still `processing`.
- `original_url` is filled only for staff with `report:read`.
- `width`/`height` are the display variant's once `ready`.
- Signed URLs expire after 10 minutes and use the **public** storage endpoint (`S3_PUBLIC_ENDPOINT`, `http://localhost:9000` in development), never the internal Docker hostname.

## 4. Geocoding and jurisdiction lookup
`GET /api/v1/geo/reverse?lat=12.97&lng=77.59` (`X-Tenant` or bearer)
```json
{ "address_text": "MG Road, Shivajinagar, Bengaluru", "in_jurisdiction": true,
  "ward": { "id": "uuid", "name": "Synthetic Ward 2 (North-East)", "code": "SYN-W02" }, "zone": { "id": "uuid", "name": "..." } }
```
- `in_jurisdiction`, `ward` and `zone` come from PostGIS and our own boundaries, so the report form keeps working when the geocoder is off or down. Inside the city, `ward` and `zone` are always present. A point on a shared edge gets exactly one ward (the smallest one covering it). Outside the city, `in_jurisdiction` is `false` and `ward`/`zone` are `null`.
- `address_text` comes from the geocoder behind a provider interface (`GEOCODER=nominatim|none`). It's `null` when the geocoder is off or fails, and the call still returns `200`. It's looked up outside the city too.
- Addresses are cached in Redis by coordinates rounded to four decimals (about 11 m); failures are cached for a minute.
- The Nominatim provider sends a generic User-Agent and stays within one request per second across all API processes. A caller waits at most 2.5 s for its turn and otherwise gets `address_text: null`.

## 5. Reports

**Create:** `POST /api/v1/reports` (`report:create`). The **`Idempotency-Key` header is required**, because a dropped response on a phone network is the normal way to submit twice. Without it the API returns `422 validation_error` with `loc: ["header", "Idempotency-Key"]`.
```json
{
  "category_id": "uuid",
  "description": "Large pothole near the bus stop",
  "location": { "lat": 12.9716, "lng": 77.5946, "accuracy_m": 12.5, "source": "gps" },
  "address_text": "optional, as confirmed by the citizen",
  "details": { "road_name": "MG Road", "size": "large" },
  "media_ids": ["uuid"],
  "client_created_at": "2026-11-24T08:15:00+05:30"
}
```
- `location.source` is `gps`, `pin` or `manual`; provenance is kept (PRD §10.2). The web app sends `gps` with the fix's accuracy, and `pin` with no accuracy once the citizen moves the pin.
- `description` is 0–2000 characters and `address_text` is optional; both are trimmed, and blank is stored as `null`.
- `media_ids` are media asset ids, unique, at most 10.
- `client_created_at` must include an offset. It's when the citizen first pressed Send: a retry with the same key must repeat it, along with the rest of the body (see [Retries](#retries)).

**Validation** runs in this order, and nothing is written until all of it passes:
1. Unknown or inactive category: `422 validation_error`, `loc: ["body", "category_id"]`.
2. Point outside the city: `422 out_of_jurisdiction`.
3. Photo count outside the category's range: `422 evidence_required`, `details: { min_photos, max_photos, received }`.
4. Media that can't be attached: `422 invalid_media`, `details.media: [{ id, reason }]`, reason one of `not_found` (also someone else's upload), `wrong_purpose`, `not_completed`, `failed`, `already_attached`.
5. `details` that don't match the category's fields: `422 validation_error`. Unknown keys, wrong types, values outside a select's options and missing required answers are all reported at once in `details.errors`, `loc: ["body", "details", "<key>"]`. Text answers are trimmed (max 500 characters) and blank counts as missing; numbers can't be booleans.
6. The Phase 1 deployment policy, "at least one photo **or** a description of 10+ characters": `422 evidence_required` with `details.min_description_length: 10`.

**In one transaction**, the server then stores the report, assigns `ward_id` (the smallest ward containing the point), creates the civic issue (temporary Phase 1 rule: one issue per report) with `report_count = 1` and `unique_reporter_count = 1`, attaches the photos, and writes the issue's `created` timeline event and the audit events. It returns `201` with the owner view of the report.

<a id="retries"></a>**Retries.** Repeating the request with the same key and the same body (compared after parsing, so key order and whitespace don't matter) returns `201` with `Idempotent-Replayed: true` and the same report, **re-rendered** (fresh signed URLs, current status) rather than the stored bytes. The same key with a different body is `422 idempotency_key_reused`. A failed request stores nothing, so it can be retried with its key. The web app keeps the key and the first attempt's `client_created_at` in the saved draft, so "Try again" after a lost response replays instead of creating a second report; "Send as a new report" takes a new key.

**References** are human-friendly and sequential per tenant, kind and year: reports `R-26-000123`, issues `CP-26-000123` (`26` is the year in Asia/Kolkata). They come from a counter row in the submitting transaction, so they're unique and never reused; a failed submission gives its number back.

**Report object, owner view** (`POST /reports`, and `GET /reports/{id}` for the reporter):
```json
{
  "id": "uuid", "reference": "R-26-000123", "created_at": "...", "view": "owner",
  "category": { "id": "uuid", "code": "pothole", "name_i18n": {...}, "icon": "construction" },
  "description": "...", "details": {...},
  "location": { "lat": 12.9716, "lng": 77.5946, "accuracy_m": 12.5, "source": "gps" },
  "address_text": "...", "ward": { "id": "uuid", "name": "..." },
  "media": [ /* media objects */ ],
  "status": "accepted",
  "issue": {
    "id": "uuid", "reference": "CP-26-000123", "status": "reported",
    "timeline": [ { "at": "...", "type": "created", "from_status": null, "to_status": "reported", "public_note": null } ]
  }
}
```
- `status` is the report's own state: `accepted` or `withdrawn` in Phase 1. The status citizens follow is `issue.status`.
- `issue.timeline` has **public events only**, oldest first, and never a `reason` or the actor: the shape has no field for them, and internal events never leave the database for a citizen. The first event has `type: "created"`; staff status changes are `status_changed`, with the `public_note` staff chose to share.

**Staff view** (`GET /reports/{id}` for staff, and inside issue details): the same fields with `"view": "staff"`, plus `reporter: { id, display_name }`, `client_created_at`, and `issue: { id, reference, status }` without a timeline (the issue detail has the full one). `reporter.phone` and `reporter.email` are present only for callers with `user:manage`. `original_url` is filled on media.

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/reports` | `report:create` | See above |
| GET | `/api/v1/users/me/reports` | `report:read_own` | The caller's reports, newest first, in the standard page envelope. Items: `{ id, reference, created_at, category, thumb_url, address_text, issue: { reference, status } }`; `thumb_url` is the cover photo's once processed. Filter `status` (repeatable) by the **issue's** status, the one the list shows. |
| GET | `/api/v1/reports/{id}` | owner, or `report:read` within scope | Owner view for the reporter, staff view for staff whose scope covers the report's ward. Anyone else gets `404`: other citizens, staff out of scope or without `report:read`, other tenants. |

## 6. Civic issues (staff)

**Statuses:** `reported`, `under_review`, `verified`, `assigned`, `in_progress`, `pending_verification`, `resolved`, `rejected`, `closed`, `reopened` (PRD FR-052, defined in the state table there).

**Issue list item:**
```json
{
  "id": "uuid", "reference": "CP-26-000123", "status": "reported",
  "category": { "id": "uuid", "code": "pothole", "name_i18n": {...}, "icon": "construction" },
  "location": { "lat": 12.97, "lng": 77.59 }, "address_text": "...",
  "ward": { "id": "uuid", "name": "..." },
  "report_count": 1, "unique_reporter_count": 1,
  "severity": null, "priority": null,
  "thumb_url": "signed|null",
  "created_at": "...", "updated_at": "...", "version": 3
}
```
`severity` and `priority` stay `null` until Phase 2.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/issues` | `issue:read` | Standard page envelope. Filters below. `sort`: `-created_at` (default), `created_at`, `-updated_at`, `updated_at`, `-report_count`, `report_count`; anything else is `422`. |
| GET | `/api/v1/issues/geojson` | `issue:read` | Same filters, plus a required `bbox`. A GeoJSON `FeatureCollection` of points, newest first, each with the issue id as the feature `id` and properties `{ id, reference, status, category_code, report_count }`. At most 5000 features, with `"truncated": true` when capped. Used for the map. |
| GET | `/api/v1/issues/{id}` | `issue:read` within scope | Issue detail, below |
| PATCH | `/api/v1/issues/{id}/status` | per the transition rules | `{ to_status, reason?, public_note?, version }`. Returns `200` with the updated issue detail. Errors below. |

**Filters** (all optional, combined with AND):
- `status`, `category_id`, `ward_id`: each repeatable.
- `from` / `to`: creation date, inclusive whole days in Asia/Kolkata. `from` after `to` is `422`.
- `q`: search over the issue reference, report references, address and report descriptions. Every word matches by **prefix** (`poth` finds "pothole"), using Postgres full text with the `simple` configuration so Hindi works the same way. References also match as case-insensitive substrings, since the tokenizer splits `CP-26-000123`.
- `bbox`: `minLng,minLat,maxLng,maxLat`, in range with min < max, else `422`.

Results are always limited to the caller's [scope](#scope).

**Issue detail:**
```json
{
  "...list item fields...": "",
  "reports": [ /* staff report views, oldest first, with media */ ],
  "timeline": [ { "id": "uuid", "at": "...", "type": "created|status_changed|note", "from_status": "...|null", "to_status": "...|null",
                  "reason": "...|null", "public_note": "...|null", "visibility": "public|internal",
                  "actor": { "id": "uuid", "display_name": "..." } } ],
  "allowed_transitions": [ { "to_status": "under_review", "requires_reason": false } ]
}
```
- The timeline is oldest first and includes internal events. `actor` is `null` for events the platform made itself.
- `allowed_transitions` lists the moves the caller can make right now. Only roles whose grant covers the issue's ward count: a supervisor for Zone North is not a supervisor in Zone South.

**Changing status.** The issue row is locked before the version is compared, so two staff acting on the same version can't both win. Every accepted change increments `version` and writes a timeline event (from, to, actor, reason, public note) and an audit event in the same transaction (FR-054). The event is **public**: citizens see the move and the `public_note`, never the `reason`. Errors:
- `409 version_conflict`, `details: { version }` with the current version. The web app doesn't retry with the newer version, which would overwrite a colleague's change; it explains and offers to reload.
- `422 invalid_transition`, `details: { from_status, to_status, allowed_transitions: [{ to_status, requires_reason }] }`. This also covers system-only moves and a move to the current status.
- `422 reason_required`, `details: { to_status }`. A blank reason counts as missing.

## 7. Workflow (configurable transitions)
Transitions are stored per tenant in a `status_transitions` table: `from_status`, `to_status`, `allowed_roles[]`, `requires_reason`, `system_only`. System-only transitions are performed by the platform itself (for example `verified → assigned` during assignment in Phase 3); the status endpoint rejects them with `422 invalid_transition`.

Default transitions, installed for every tenant (existing rows are left alone):

| From | To | Roles | Reason required |
|---|---|---|---|
| reported | under_review | operator, supervisor, municipal_admin | no |
| reported / under_review | verified | operator, supervisor, municipal_admin | no |
| reported / under_review | rejected | operator, supervisor, municipal_admin | **yes** |
| rejected | under_review | supervisor, municipal_admin | **yes** |
| verified | assigned | system only (Phase 3) | — |
| *(later phases add the rest)* | | | |

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/admin/workflow/transitions` | `config:read` | Standard page envelope, in lifecycle order: `{ id, from_status, to_status, allowed_roles, requires_reason, system_only }`. Read-only in Phase 1; editing comes with FR-081. |

## 8. Development seed additions
- `demo-city` gets a city jurisdiction `SYN-CITY` (kind `city`, the union of the zones) as the parent of both zones, so the admin jurisdictions list has 7 rows. Reports outside it are rejected, and the maps start from it. Ward pickers and map overlays use `kind=ward` only.
- The five launch categories, `pothole`, `waste`, `waterlogging`, `streetlight` and `drainage`, with English and Hindi names, a few optional fields each, linked to the matching department. `streetlight` needs no photo (0–3); the others need 1–5.
- The default transitions, for both tenants.
- **60 synthetic issues** across the four `demo-city` wards over the last 30 days. Half are `reported` and the rest `under_review`, `verified` or `rejected`, each with a timeline that leads there. Each has one report from the seeded citizen, an address like `Synthetic Street N, Ward W (synthetic)`, an English or Hindi description (so search can be tried in both), and one generated placeholder photo (a flat colour with the category name and "SYNTHETIC" on it) that goes through the same processing as real uploads.
- Re-running the seed creates nothing new: ids are deterministic, and a photo a previous run left half-done is finished.

## 9. Housekeeping
An hourly Celery Beat job deletes expired OTP challenges (an hour after expiry), sessions that expired or were revoked more than 30 days ago, idempotency keys older than 24 hours, and uploads that were never completed or failed verification and are over a day old, together with their objects. It also re-queues media stuck in `processing` for 15 minutes.
