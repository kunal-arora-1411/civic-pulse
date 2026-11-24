# API contract: analytics and in-app notifications

Base path `/api/v1`, tenant from `X-Tenant`, bearer token, errors in the
usual envelope (phase-0-contract.md). Coordinates are `[lng, lat]` or
`lng`/`lat` fields, never Leaflet order. Every figure is defined once in
[`docs/metrics.md`](../metrics.md); responses name the entry they use in
`metric` / `metrics`.

## 1. Analytics (AN-001 to AN-004)

All endpoints are `GET`, read-only, and need **`analytics:read`**
(municipal admin and supervisor by default). Without it: `403
permission_denied`. Nothing here is audited: it only reads aggregates.

### Shared filters

| Query | Type | Default | Meaning |
|---|---|---|---|
| `from` | `YYYY-MM-DD` | `to` − 29 days | First IST day, inclusive |
| `to` | `YYYY-MM-DD` | today (IST) | Last IST day, inclusive |
| `category_id` | uuid | none | One category |
| `ward_id` | uuid | none | One ward |
| `status` | issue status, repeatable | none | Issues currently in one of these states; for report metrics, reports whose issue is |

`from` after `to`, or a span over 366 days: `422 validation_failed`.

Every response carries the filters it applied, with the period just
before for comparison:

```json
"filters": {
  "period":   {"start": "2026-10-26", "end": "2026-11-24"},
  "previous": {"start": "2026-09-26", "end": "2026-10-25"},
  "category_id": null, "ward_id": null, "status": []
}
```

### `GET /analytics/overview`

Headline KPIs: value for the period, value for the previous period, and a
sparkline (daily buckets up to 45 days, weekly beyond).

```json
{
  "filters": {...},
  "kpis": [
    {"metric": "reports", "unit": "count", "value": 412, "previous": 377,
     "sparkline": [{"bucket": "2026-10-26", "value": 11}, ...]}
  ]
}
```

`metric` is one of `reports`, `issues`, `unique_reporters`,
`resolution_time`, `acknowledgement_time` (`unit: "hours"`),
`duplicate_rate`, `review_rate`, `reopen_rate` (`unit: "ratio"`, 0–1).
`value`, `previous` and a point's `value` are `null` when there is
nothing to measure (for example no resolutions yet).

### `GET /analytics/trend?interval=day|week`

```json
{"metrics": ["reports", "issues", "resolved"], "interval": "day",
 "filters": {...},
 "points": [{"bucket": "2026-11-24", "reports": 14, "issues": 9, "resolved": 6}]}
```

Every bucket in the period is present (zeros included). Weekly buckets
start on the ISO Monday. `resolved` counts first resolutions in the bucket.

### `GET /analytics/by-status`

`{"metric": "issues_by_status", "filters", "total", "items": [{"status", "count"}]}`:
issues created in the period by current status. Only states with issues
are listed.

### `GET /analytics/by-category`

`{"metric": "issues_by_category", "filters", "items": [{"category": CategoryRef, "total", "statuses": [{"status", "count"}]}]}`,
most issues first. `CategoryRef` is `{id, code, name_i18n, icon}` as in
Phase 1.

### `GET /analytics/by-ward`

```json
{"metrics": ["issues_by_ward", "resolution_time"], "filters": {...},
 "items": [{"ward": {"id": "…", "code": "SYN-W01", "name": "Synthetic Ward 1"},
            "issues": 120, "open": 41, "resolved": 70,
            "median_resolution_hours": 81.5}]}
```

Most issues first. `ward: null` is the row for issues outside every ward.

### `GET /analytics/resolution-times`

```json
{"metric": "resolution_time", "filters": {...}, "count": 180,
 "mean_hours": 96.2, "median_hours": 71.0, "p90_hours": 210.4,
 "bins": [{"lower_hours": 0, "upper_hours": 24, "count": 30}, ...,
          {"lower_hours": 720, "upper_hours": null, "count": 2}]}
```

Bin edges: 0, 24, 48, 72, 168, 336, 720 hours and an open-ended last bin.

### `GET /analytics/matching-quality`

```json
{"metrics": ["auto_link_rate", "review_rate", "duplicate_rate", "correction_rate"],
 "filters": {...}, "decided_reports": 480,
 "auto_link_rate": 0.17, "review_rate": 0.09, "duplicate_rate": 0.24,
 "correction_rate": 0.05, "feedback_count": 40}
```

Rates are 0–1 or `null` when the denominator is zero.

### `GET /analytics/hotspots?resolution=8`

`resolution` 5–10 (default 8).

```json
{"metric": "hotspots", "filters": {...}, "resolution": 8,
 "items": [{"cell": "8861892e0bfffff", "lng": 77.571, "lat": 12.984,
            "issues": 17, "open": 6}]}
```

Densest first, at most 400 cells. `lng`/`lat` is the cell centre; the
client draws the hexagon from `cell`.

### `GET /analytics/activity`

`{"metric": "report_activity", "filters", "items": [{"weekday", "hour", "count"}]}`:
reports by IST weekday (0 = Monday) and hour (0–23). Empty cells are
omitted.

## 2. In-app notifications

Every signed-in user (citizen or staff) sees **only their own**
notifications; no extra permission. Someone else's id is a `404`, never a
`403`, so ids can't be probed. Text arrives as message keys plus
parameters and is rendered in the reader's language
(`notifications.messages` in the web app's messages). The keys in the
example are illustrative.

```json
{"id": "uuid", "kind": "issue_status",
 "title_key": "issue_status.title", "body_key": "issue_status.body",
 "params": {"reference": "ISS-000123", "status": "resolved"},
 "link": "/issues/…", "issue_id": "uuid",
 "read_at": null, "created_at": "2026-11-24T06:00:00Z"}
```

`kind`: `report_new_issue`, `report_linked`, `issue_status`,
`review_task`, `assignment`. Clients must still render an unknown kind
(generic icon).

| Method and path | Body / query | Response |
|---|---|---|
| `GET /notifications` | `limit`, `offset`, `unread=true` | `{items, total, limit, offset, unread}`, newest first. `unread` is always the full unread count. |
| `GET /notifications/unread-count` | | `{"unread": 3}`. Cheap enough to poll for the header badge. |
| `POST /notifications/read-all` | | `{"updated": 3}` |
| `POST /notifications/{id}/read` | | The notification. Idempotent; another user's id: `404`. |

Errors: `401` without a session, `422` for a malformed id or page.
