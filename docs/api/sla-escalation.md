# SLA targets and escalation: API contract

Builds on the Phase 0–3 contracts; their conventions still apply (error envelope, pagination, `X-Request-ID`, localised text). [`apps/api/openapi.json`](../../apps/api/openapi.json) is the precise, generated form. Change this file in the same commit as any deviation.

**Goal:** administrators set how long each category's issues may stay open (FR-056); staff see what is overdue or about to be (FR-057); an overdue issue shows its breach and escalates as configured (AC-09). The web screens are the SLA targets settings page (`/admin/settings/sla`), the work queue (`/admin/issues`) and the issue page (`/admin/issues/{id}`).

**Scope.** Targets are resolution targets: from the first report to `resolved`. Acknowledgement and assignment targets, per-jurisdiction targets and raising the priority on breach are not built yet.

## 1. Targets

| Method | Path | Permission | Response |
|---|---|---|---|
| GET | `/api/v1/admin/sla-targets` | `config:read` | `SlaTargets` |
| PUT | `/api/v1/admin/sla-targets` | `config:manage` | `SlaTargets` |

```json
{
  "items": [
    { "id": "uuid", "category_id": "uuid", "priority_band": null, "resolve_hours": 72, "escalate_after_hours": 24 },
    { "id": "uuid", "category_id": "uuid", "priority_band": "critical", "resolve_hours": 8, "escalate_after_hours": 24 }
  ]
}
```

- A target with `priority_band: null` covers every band the category has no narrower target for. A category with no target has no deadline.
- `resolve_hours` and `escalate_after_hours` are whole hours from 1 to 8760.
- PUT replaces the whole set (send `{"items": [...]}` without `id`). It is audited as `config.sla_targets_updated` with the old and new sets, and every open issue is rescheduled against the new set in the same transaction.
- Errors: `401` signed out; `403 forbidden` without the permission; `422 validation_failed` for a value out of range, two targets for the same category and band, or a category id this tenant doesn't have.

## 2. Deadlines on issues

A database trigger keeps each issue's deadline current, so every path that writes an issue schedules it the same way:

- The clock starts when the issue is created and restarts when it is reopened.
- `due_at` = clock start + the matching target: the one for the issue's effective band (an override counts) if there is one, else the category-wide one. It is recomputed when the category, the band or the status changes, and when the targets are saved.
- `resolved`, `rejected` and `closed` freeze `due_at` (the clock is paused); the issue is then never overdue.
- If a recomputed deadline is in the future again (a relaxed target, a lower band, a reopen), the breach and escalation are cleared.

Every staff issue representation (`GET /issues` items, `GET /issues/{id}`, related issues) gains:

| Field | Type | Meaning |
|---|---|---|
| `due_at` | datetime \| null | The resolution deadline; null when no target applies. |
| `overdue` | bool | Open and past `due_at`. |
| `sla_state` | `"none" \| "on_track" \| "due_soon" \| "overdue"` | `due_soon`: a quarter or less of the target time is left. `none`: no deadline, or finished. |

`GET /issues/{id}` also gains:

| Field | Type | Meaning |
|---|---|---|
| `breached_at` | datetime \| null | When the scanner first found the issue past its deadline. |
| `escalation_level` | 0 \| 1 \| 2 | 0 none; 1 the department's supervisors were told; 2 the municipal admins were told. |

**Filter.** `GET /issues` and `GET /issues/geojson` accept `overdue=true` (open and past the deadline) or `overdue=false` (everything else). `sort` accepts `due_at` / `-due_at`.

The public tracker does not show deadlines.

## 3. Escalation

Celery Beat runs `civicpulse.sla.scan` every 5 minutes on the `default` queue. For each open, unmerged issue past `due_at`:

1. **Level 1** (first time seen): `breached_at` is set, an internal `sla_breached` timeline event is written (`data: {"level": 1, "due_at": ...}`), and every active supervisor whose role is scoped to the category's default department, or to no department, gets a notification.
2. **Level 2** (`escalate_after_hours` after `breached_at`, still open): an internal `sla_escalated` event, and every active municipal admin gets a notification.

Each level happens once per breach; overlapping runs are harmless. Each escalation is audited as `issue.sla_escalated`. Citizens are never told.

Notifications use the existing inbox (`GET /api/v1/notifications`) with:

```json
{
  "kind": "sla_breach",
  "title_key": "sla_breach.title",
  "body_key": "sla_breach.body_level_1",
  "params": { "issue": "CP-26-000123", "level": 1 },
  "link": "/admin/issues/{id}",
  "issue_id": "uuid"
}
```

`body_key` is `sla_breach.body_level_2` for level 2.

## 4. Workload and analytics

- `GET /api/v1/workload`: `TeamLoad.overdue` is now an integer, the number of issues with open work orders for the team that are past their deadline.
- `GET /api/v1/analytics/overview` gains the KPI `sla_compliance` (unit `ratio`): of the issues first resolved in the period that had a deadline, the share resolved on or before it (see [`docs/metrics.md`](../metrics.md#sla-compliance)).
