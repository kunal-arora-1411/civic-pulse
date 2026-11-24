# Community support and public tracking: API contract

Builds on the Phase 0–3 contracts; their conventions still apply (error envelope, pagination, `X-Request-ID`, localised text, `[lng, lat]` in GeoJSON). [`apps/api/openapi.json`](../../apps/api/openapi.json) is the precise, generated form. Change this file in the same commit as any deviation.

**Goal:** citizens can say "I face this too", confirm or dispute a fix from their own report, and anyone can follow the city's issues without signing in. The web screens are the citizen report page (`/reports/{id}`), the public tracker (`/track`), the public issue page (`/track/{id}`) and the ward scorecard (`/track/scorecard`).

## 1. Support ("I face this too")

| Method | Path | Permission | Response |
|---|---|---|---|
| GET | `/api/v1/issues/{id}/support` | `report:create` | `SupportState` |
| POST | `/api/v1/issues/{id}/support` | `report:create` | `SupportState` |
| DELETE | `/api/v1/issues/{id}/support` | `report:create` | `SupportState` |

```json
{ "issue_id": "uuid", "support_count": 6, "supported": true }
```

- One support per citizen per issue; POST twice and DELETE twice are harmless. Supporting also follows the issue; withdrawing stops following.
- Errors: `401` signed out; `403 forbidden` for staff (they don't hold `report:create`); `404` unknown or other tenant; `422 invalid_transition` on a rejected or closed issue; `422 issue_merged` on a merged one.
- **Priority:** support from citizens who did not report the issue adds a small, capped, logarithmic bonus under the factor `community` (`explanation_key: "priority.community"`, `value` = supporters). The factor is listed only when someone supports the issue. It can never decide alone (PRD §8.6).

The web toggles support optimistically and rolls back on any error. Signed-out visitors see the count and a link to `/login?next=…`; staff see the count only.

## 2. Reporter's view of an issue (owner view additions)

`GET /api/v1/reports/{id}` (owner view) — `issue` gains:

| Field | Type | Meaning |
|---|---|---|
| `support_count` | int | Citizens who said "I face this too". |
| `closure` | `CitizenClosure \| null` | Set while the issue is `pending_verification`, `resolved` or `closed`. |
| `my_verification` | `"resolved" \| "unresolved" \| null` | The caller's answer for the current closure round. |
| `can_verify` | bool | Whether `POST /issues/{id}/verification` would be accepted now. |
| `can_reopen` | bool | Whether `POST /issues/{id}/reopen` would be accepted now. |

```json
"closure": {
  "state": "pending",
  "requested_at": "2026-11-23T10:00:00+05:30",
  "reason_code": "contractor_done",
  "after_photos": [ { "id": "uuid", "status": "ready", "thumb_url": "…", "display_url": "…", "original_url": null } ]
}
```
`state` is `pending` (waiting for approval or confirmations) or `approved`. After photos are the public, face-blurred copies only.

## 3. Verification and reopen

As in the [Phase 3 contract §6](phase-3-contract.md#6-verification-resolution-window-and-reopen):

- `POST /api/v1/issues/{id}/verification` `{ "outcome": "resolved" | "unresolved", "note": "optional, ≤ 2000" }` → `200` with the caller's report owner view. The web requires a note for `unresolved`.
  Errors: `403 not_eligible` (no non-withdrawn report on the issue), `409 already_verified` (answered this round), `422 invalid_transition` (not `pending_verification` or `resolved`).
- `POST /api/v1/issues/{id}/reopen` `{ "reason": "required, ≤ 2000" }` from `resolved` or `closed` → `reopened`. A reporter gets their report owner view; staff get the issue detail.
  Errors: `403 not_eligible`, `422 invalid_transition`, `422 validation_error` (empty reason).

## 4. Public tracking (no login)

`/api/v1/public/{tenant}/…` where `{tenant}` is the tenant slug (`demo-city` in development; the web reads `NEXT_PUBLIC_TENANT`). No token and no `X-Tenant`: the URL is the whole cache key. Responses carry `Cache-Control: public, max-age=30, stale-while-revalidate=120`; each client address gets 300 requests a minute (`429 rate_limited` beyond). Unknown tenant: `404`.

Nothing public identifies a person: no reporter names or contacts, no address text, no internal notes, only face-blurred photos, and locations snapped to the centre of a coarse H3 cell. Rejected issues, merged issues and issues with no remaining reports are left out of lists; a merged issue's own page still opens and points to the survivor.

| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/issues` | `status` (repeatable), `category_id`, `ward_id`, `sort`, `limit`, `offset` | `Page<PublicIssueItem>` |
| GET | `/issues/geojson` | `status`, `category_id`, `ward_id` | `PublicFeatureCollection` (≤ 2000, `truncated`) |
| GET | `/issues/{id}` | | `PublicIssueDetail` |
| GET | `/scorecard` | | `Scorecard` |

`sort`: `-created_at` (default), `created_at`, `-updated_at`, `-support_count`, `-report_count`.

```json
// PublicIssueItem
{ "id": "uuid", "reference": "CP-26-000123", "status": "in_progress",
  "category": { "id": "uuid", "code": "pothole", "name_i18n": { "en": "Pothole" }, "icon": "construction" },
  "ward": { "id": "uuid", "name": "Ward 3" },
  "location": { "lat": 12.97, "lng": 77.59, "precision_m": 175 },
  "report_count": 3, "support_count": 5, "thumb_url": "…",
  "created_at": "…", "updated_at": "…", "resolved_at": null, "age_days": 4.2 }

// PublicIssueDetail = PublicIssueItem +
{ "timeline": [ { "at": "…", "type": "created", "from_status": null, "to_status": "reported", "public_note": null } ],
  "before_photos": [ { "thumb_url": "…", "display_url": "…" } ],
  "after_photos": [],
  "merged_into": "CP-26-000090", "merged_into_id": "uuid" }

// PublicFeature (geometry is generalised, [lng, lat])
{ "type": "Feature", "id": "uuid", "geometry": { "type": "Point", "coordinates": [77.59, 12.97] },
  "properties": { "id": "uuid", "reference": "CP-26-000123", "status": "in_progress",
                  "category_code": "pothole", "report_count": 3, "support_count": 5 } }

// Scorecard: every ward, by name
{ "wards": [ { "ward": { "id": "uuid", "name": "Ward 1" },
               "open_count": 4, "resolved_count": 6, "median_resolution_days": 3.5 } ] }
```

- `merged_into` / `merged_into_id`: the reference and id of the issue this one was merged into, or `null`. The id lets the public page link to it.
- `resolved_count` counts `resolved` and `closed`; `median_resolution_days` is from report to resolution, `null` when nothing in the ward is resolved.
