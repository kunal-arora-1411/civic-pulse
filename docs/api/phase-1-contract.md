# Phase 1 API contract: core reporting loop

This builds on [`phase-0-contract.md`](phase-0-contract.md). All its conventions still apply: tenant resolution, the error envelope, pagination, `X-Request-ID`, `Idempotency-Key` and phone formats. If either side needs to change this file, change it in the same commit and say so.

**Phase 1 goal:** a citizen submits a report with photos and location. Each report creates its own civic issue (duplicate matching arrives in Phase 2). Staff see issues in a queue and on a map, and move them through the lifecycle.

## New permissions in use
Already defined in Phase 0: `report:create`, `report:read_own`, `report:read`, `issue:read`, `issue:triage`, `issue:update`, `config:read`, `config:manage`. Staff issue access is limited by the principal's jurisdiction scope (ward/zone), using the Phase 0 helper.

## Localised text
Fields ending in `_i18n` are objects keyed by locale, for example `{ "en": "Pothole", "hi": "गड्ढा" }`. The API returns the full object. The client picks the user's locale and falls back to `en`.

---

## 1. Tenant (extended)
`GET /api/v1/tenants/current` adds:
```json
{ "...": "...", "map": { "center": [77.5946, 12.9716], "zoom": 12, "bounds": [77.50, 12.90, 77.70, 13.05] } }
```
Coordinates are always `[lng, lat]`, following GeoJSON order. The bounds come from the tenant's city jurisdiction geometry.

## 2. Categories
```json
{
  "id": "uuid", "code": "pothole", "parent_id": null,
  "name_i18n": { "en": "Pothole / road damage", "hi": "गड्ढा / सड़क क्षति" },
  "description_i18n": { "en": "...", "hi": "..." },
  "icon": "construction",
  "evidence": { "min_photos": 1, "max_photos": 5 },
  "fields": [
    { "key": "road_name", "type": "text", "required": false, "label_i18n": {...} },
    { "key": "size", "type": "select", "required": false, "label_i18n": {...},
      "options": [{ "value": "small", "label_i18n": {...} }, { "value": "large", "label_i18n": {...} }] }
  ],
  "default_department_id": "uuid|null",
  "dedup": { "radius_m": 30, "window_days": 30 },
  "sort_order": 10, "is_active": true
}
```
- Field `type` is one of `text`, `number`, `select`, `boolean`.
- `icon` is a lucide icon name.
- `dedup` is stored now but only used from Phase 2 onward.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/categories` | `X-Tenant` or bearer | Active categories only, flat list ordered by `sort_order`. Used by the report form. |
| GET | `/api/v1/admin/categories` | `config:read` | Includes inactive categories |
| POST | `/api/v1/admin/categories` | `config:manage` | Create. `code` is unique per tenant. Audited. |
| PATCH | `/api/v1/admin/categories/{id}` | `config:manage` | Partial update, including `is_active` and `fields`. Audited. |

Seed the five launch categories: `pothole`, `waste`, `waterlogging`, `streetlight`, `drainage`. Each gets English and Hindi names and 1–3 sensible fields, and is linked to the matching seeded department.

## 3. Media upload
Uploads go directly to object storage with pre-signed URLs. The API never streams image bytes on upload.

**Step 1: create an upload**
`POST /api/v1/media/uploads` (requires `report:create` or `evidence:upload`)
```json
{ "purpose": "report_evidence", "content_type": "image/jpeg", "size_bytes": 482113, "checksum_sha256": "hex" }
```
Returns `201`:
```json
{ "upload_id": "uuid", "method": "PUT", "url": "http://localhost:9000/...signed...", "headers": { "Content-Type": "image/jpeg" }, "expires_in": 600, "max_size_bytes": 10485760 }
```
- Allowed types: `image/jpeg`, `image/png`, `image/webp`. Maximum 10 MB (configurable).
- If not, the API returns `422 unsupported_media_type` or `422 file_too_large`.
- Each user may hold at most 20 incomplete uploads at once.

**Step 2:** the client `PUT`s the file bytes to `url` with the given headers. MinIO/S3 must accept this from the web origin (CORS).

**Step 3: complete the upload**
`POST /api/v1/media/uploads/{upload_id}/complete`, with no body.
- The server checks that the object exists, that its size matches, that the checksum matches, and that the content really is an image of the declared type (inspecting the bytes, not trusting the header).
- On failure: `422 upload_verification_failed`, and the object is deleted.
- On success: `200` with a media asset:
```json
{ "id": "uuid", "status": "processing", "content_type": "image/jpeg", "width": 3024, "height": 4032,
  "variants": { "thumb": null, "display": null }, "captured_at": "2026-11-24T08:12:00+05:30" }
```
- `captured_at` comes from EXIF when present.

**Processing:** a Celery job reads EXIF capture time and GPS (stored privately) and makes `display` (max 1600 px, WebP) and `thumb` (max 400 px, WebP) copies with **all metadata removed**. The asset status becomes `ready`, or `failed` with the reason recorded. The original file keeps its metadata and is visible to staff only.

**Reading media:** media appears embedded in report and issue responses as:
```json
{ "id": "uuid", "status": "ready", "width": 1200, "height": 1600,
  "thumb_url": "signed GET url|null", "display_url": "signed GET url|null", "original_url": "signed GET url|null (staff only)",
  "captured_at": "...|null" }
```
- Signed GET URLs expire after 10 minutes.
- The URLs use the **public** storage endpoint (`S3_PUBLIC_ENDPOINT`, `http://localhost:9000` in development), not the internal Docker hostname.

## 4. Geocoding and jurisdiction lookup
`GET /api/v1/geo/reverse?lat=12.97&lng=77.59` (`X-Tenant` or bearer)
```json
{ "address_text": "MG Road, Shivajinagar, Bengaluru", "in_jurisdiction": true,
  "ward": { "id": "uuid", "name": "Ward 3 (synthetic)", "code": "W03" }, "zone": { "id": "uuid", "name": "..." } }
```
- `ward` and `zone` come from PostGIS and are always present when the point is inside the city.
- `address_text` comes from the geocoder behind a provider interface (`GEOCODER=nominatim|none`). It's `null` when the geocoder is off or fails, and the call still returns `200`.
- Results are cached in Redis by coordinates rounded to ~11 m.
- The Nominatim provider sends a generic User-Agent and stays within 1 request per second.

## 5. Reports

**Create:** `POST /api/v1/reports` (`report:create`). The **`Idempotency-Key` header is required**; without it the API returns `422`.
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
- `location.source` is `gps`, `pin` or `manual` (provenance is kept, PRD §10.2).
- Validation errors:
  - Point outside the city: `422 out_of_jurisdiction`.
  - Photo count outside the category's `min_photos`/`max_photos`: `422 evidence_required`.
  - Media not owned by the caller, not completed, already attached elsewhere, or failed: `422 invalid_media`.
  - `details` that don't match the category fields: `422 validation_error`, with per-field details.
  - Description: 0–2000 characters. Phase 1 deployment policy is "at least one photo **or** a description of 10+ characters", enforced after the category evidence rule.
- In **one transaction**, the server:
  - stores the report
  - assigns `ward_id` (the smallest ward containing the point)
  - creates the civic issue (temporary Phase 1 rule: one issue per report)
  - sets `report_count = 1` and `unique_reporter_count = 1`
  - writes the issue's `created` timeline event and an audit event
- Returns `201`, a report object (below).

**Reference formats:** human-friendly sequences per tenant: reports `R-26-000123`, issues `CP-26-000123` (`26` = year). Sequential, unique per tenant, and never reused.

**Report object** (owner view):
```json
{
  "id": "uuid", "reference": "R-26-000123", "created_at": "...",
  "category": { "id": "uuid", "code": "pothole", "name_i18n": {...}, "icon": "construction" },
  "description": "...", "details": {...},
  "location": { "lat": 12.9716, "lng": 77.5946, "accuracy_m": 12.5, "source": "gps" },
  "address_text": "...", "ward": { "id": "uuid", "name": "..." },
  "media": [ /* media objects */ ],
  "status": "accepted",
  "issue": {
    "id": "uuid", "reference": "CP-26-000123", "status": "reported",
    "timeline": [ { "at": "...", "type": "status_changed", "from_status": null, "to_status": "reported", "public_note": null } ]
  }
}
```
- `status` (the report's own state) is `accepted` or `withdrawn` in Phase 1.
- `issue.timeline` contains **public events only**: no internal notes, no staff identities.

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/reports` | `report:create` | See above |
| GET | `/api/v1/users/me/reports` | `report:read_own` | Own reports, newest first. List items: `{ id, reference, created_at, category, thumb_url, address_text, issue: { reference, status } }`. Filter `status`. |
| GET | `/api/v1/reports/{id}` | owner, or `report:read` within scope | Owner view as above. Staff get the staff view (reporter `{ id, display_name }` but **never** phone or email unless they hold `user:manage`). |

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
| GET | `/api/v1/issues` | `issue:read` | Filters below. `sort`: `-created_at` (default), `created_at`, `-updated_at`, `-report_count`. |
| GET | `/api/v1/issues/geojson` | `issue:read` | Same filters, plus a required `bbox`. Returns a GeoJSON `FeatureCollection` of points with properties `{ id, reference, status, category_code, report_count }`, capped at 5000 features with `"truncated": true` when capped. Used for the map. |
| GET | `/api/v1/issues/{id}` | `issue:read` within scope | Issue detail, below |
| PATCH | `/api/v1/issues/{id}/status` | per the transition rule | `{ to_status, reason?, public_note?, version }`. Version mismatch → `409 version_conflict` with the current `version` in `details`. Disallowed transition → `422 invalid_transition` with the allowed targets in `details`. Missing required reason → `422 reason_required`. |

**Filters** (all optional, combined with AND):
- `status` (repeatable), `category_id` (repeatable), `ward_id` (repeatable)
- `from` / `to` (created_at, ISO dates, inclusive, Asia/Kolkata)
- `q`: search over issue reference, report reference, address and report descriptions, using Postgres full text with the `simple` config so Hindi text works too
- `bbox`: `minLng,minLat,maxLng,maxLat`

Results are always limited to the caller's jurisdiction scope. An issue outside scope returns `404`, not `403`, so nothing about its existence leaks.

**Issue detail:**
```json
{
  "...list item fields...": "",
  "reports": [ /* staff report views, oldest first, with media */ ],
  "timeline": [ { "id": "uuid", "at": "...", "type": "status_changed|created|note", "from_status": "...", "to_status": "...",
                  "reason": "...|null", "public_note": "...|null", "visibility": "public|internal",
                  "actor": { "id": "uuid", "display_name": "..." } } ],
  "allowed_transitions": [ { "to_status": "under_review", "requires_reason": false } ]
}
```

## 7. Workflow (configurable transitions)
Transitions are stored per tenant in a `status_transitions` table: `from_status`, `to_status`, `allowed_roles[]`, `requires_reason`, `system_only`. System-only transitions are performed by the platform itself (for example `verified → assigned` during assignment in Phase 3). The status endpoint rejects them with `422 invalid_transition`.

Default transitions seeded per tenant for Phase 1:

| From | To | Roles | Reason required |
|---|---|---|---|
| reported | under_review | operator, supervisor, municipal_admin | no |
| reported / under_review | verified | operator, supervisor, municipal_admin | no |
| reported / under_review | rejected | operator, supervisor, municipal_admin | **yes** |
| rejected | under_review | supervisor, municipal_admin | **yes** |
| verified | assigned | system only (Phase 3) | — |
| *(later phases add the rest)* | | | |

Every transition writes a timeline event (previous status, new status, actor, timestamp, reason) and an audit event, and increments `version` (FR-054).

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/admin/workflow/transitions` | `config:read` | Read-only in Phase 1. Editing comes with FR-081 later. |

## 8. Development seed additions
- The five categories with Hindi names, as described above.
- The default transitions, for both tenants.
- **About 60 synthetic issues** across the four `demo-city` wards. Each has one report from the seeded citizen, a mix of categories and statuses (`reported`, `under_review`, `verified`, `rejected`), creation times spread over the last 30 days, and one generated placeholder image (a flat colour with the category name and "SYNTHETIC" drawn on it), uploaded to MinIO and processed into variants.
- Re-running the seed does not create duplicates.

## 9. Housekeeping included in Phase 1
- A Celery Beat job deletes expired OTP challenges, expired or revoked sessions older than 30 days, idempotency keys older than 24 hours, and incomplete uploads older than 24 hours (including their objects).
