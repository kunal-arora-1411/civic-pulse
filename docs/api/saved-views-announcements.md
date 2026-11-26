# API contract: saved analytics views and service announcements

Base path `/api/v1`, tenant from `X-Tenant` (public routes: the slug in
the path), bearer token, errors in the usual envelope
(phase-0-contract.md). P5-09: FR-077 and FR-087.

## 1. Saved analytics views (FR-077)

Named dashboard filters, **private to the person who saved them**. All
routes need **`analytics:read`** (403 otherwise). Another person's view
answers 404, as if it didn't exist. Not audited: they are preferences.

| Method | Path | Body | Result |
|---|---|---|---|
| `GET` | `/analytics/views` | | `AnalyticsView[]`, the default first, then by name |
| `POST` | `/analytics/views` | `{name, filters, is_default?}` | 201 `AnalyticsView` |
| `PATCH` | `/analytics/views/{id}` | any of `name`, `filters`, `is_default` | 200 `AnalyticsView` |
| `DELETE` | `/analytics/views/{id}` | | 204 |

```jsonc
// AnalyticsView
{ "id": "uuid", "name": "NE, October", "is_default": false,
  "filters": { "range": "custom", "from": "2026-10-01", "to": "2026-10-31",
               "category_id": null, "ward_id": "uuid",
               "status": ["reported", "verified"], "interval": "week" },
  "created_at": "…", "updated_at": "…" }
```

- `filters` mirrors the dashboard URL. `range` is `7d | 30d | 90d | mtd |
  custom` (default `30d`); `from`/`to` (IST days) only with `custom`, and
  `from <= to`; `interval` is `day | week`. Unknown keys are 422.
- `name`: 1–80 characters, unique per person ignoring case (409
  `name_taken`).
- At most one default: saving or patching a view with `is_default: true`
  clears the flag on the others. The dashboard opens on the default view
  when the URL has no filters.
- At most 20 views per person (422 `too_many_views`).

## 2. Service announcements (FR-087)

Notices for one ward, or the whole city (`ward_id` null), optionally
about one category: planned works, outages and advisories. Shown publicly
from `starts_at` until `ends_at`, unless withdrawn.

### Admin

Reading needs **`config:read`**; creating, editing and withdrawing need
**`config:manage`** (municipal admin). Each change is audited
(`announcement.create`, `announcement.update`, `announcement.withdraw`,
entity type `announcement`, with before/after).

| Method | Path | Notes |
|---|---|---|
| `GET` | `/admin/announcements?state=&ward_id=&limit=&offset=` | `Page<Announcement>`, latest start first |
| `POST` | `/admin/announcements` | 201; `ends_at` after `starts_at` and in the future |
| `GET` | `/admin/announcements/{id}` | |
| `PATCH` | `/admin/announcements/{id}` | only the fields sent; `ward_id: null` / `category_id: null` widen it; 409 `withdrawn` once withdrawn |
| `POST` | `/admin/announcements/{id}/withdraw` | takes it down now; repeating it is a no-op |

```jsonc
// AnnouncementCreate
{ "kind": "planned_works",            // planned_works | outage | advisory
  "title_i18n": { "en": "Road resurfacing", "hi": "सड़क मरम्मत" },   // en required, ≤200
  "body_i18n": { "en": "Main Road is closed overnight." },          // en required, ≤2000
  "ward_id": "uuid | null", "category_id": "uuid | null",
  "starts_at": "2026-11-26T18:00:00+05:30", "ends_at": "2026-11-28T06:00:00+05:30" }

// Announcement
{ "id": "uuid", "kind": "planned_works", "title_i18n": {…}, "body_i18n": {…},
  "ward": { "id": "uuid", "code": "W-NE", "name": "Ward NE" } | null,
  "category": { "id": "uuid", "code": "pothole", "name_i18n": {…}, "icon": "…" } | null,
  "starts_at": "…", "ends_at": "…",
  "state": "scheduled | active | ended | withdrawn", "withdrawn_at": null,
  "created_by": { "id": "uuid", "display_name": "Ada Admin" },
  "created_at": "…", "updated_at": "…" }
```

`ward_id` must be a ward of the tenant and `category_id` one of its
categories (422 otherwise).

### Public: `GET /public/{tenant}/announcements?ward_id=&category_id=`

No login; cached and rate-limited like the other public routes. The
notices showing now, newest first, at most 50, as `Announcement` without
`state`, `withdrawn_at`, `created_by`, `created_at` and `updated_at`.
With `ward_id`, city-wide notices are included too; with `category_id`,
notices for every category are included too.
