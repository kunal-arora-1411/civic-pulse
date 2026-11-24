# Phase 3 API contract: operations and field

This builds on the Phase 0–2 contracts; their conventions still apply (tenant resolution, error envelope, pagination, `X-Request-ID`, scope, localised text, `[lng, lat]` in GeoJSON and `lat`/`lng` fields in bodies). [`apps/api/openapi.json`](../../apps/api/openapi.json) is the precise, generated form. Change this file in the same commit as any deviation.

**Phase 3 goal:** the operational loop from assignment to verified closure. A supervisor assigns a verified issue to a team and a field worker; the worker accepts, starts, posts progress and requests closure with an after photo; a supervisor approves (or citizens confirm); after the resolution window the issue closes. A citizen who says "still broken" sends it back.

## Conventions added in Phase 3

### Permissions in use
No new permissions. Phase 3 starts checking ones declared in Phase 0:

| Permission | Roles | Used for |
|---|---|---|
| `config:read` / `config:manage` | admin (`config:read` also operator, supervisor) | Teams |
| `issue:assign` | supervisor | Assign, reassign, eligible teams, workload |
| `issue:approve_closure` | supervisor | Approve or reject a closure request |
| `issue:update` | operator, supervisor | Notes, staff reopen |
| `workorder:read_assigned` | field_worker | Field queue and detail |
| `workorder:update` | field_worker | Accept, decline, start, progress, request closure |
| `evidence:upload` | field_worker | Uploading `work_evidence` media |
| `issue:verify` | citizen, community_contributor | Verification and citizen reopen |

Staff endpoints are limited by the issue's ward against the caller's grant for the permission used (the Phase 1 scope rule). Out of scope is `404`.

### Field worker privacy (PRD §4.1)
Field endpoints are scoped to `work_orders.assignee_id = caller`. Anyone else's work order is `404`, never `403`. Field responses have **no** reporter fields at all (no name, phone, email or id): the schema has nowhere to put them.

### New error codes
| Code | Status | When |
|---|---|---|
| `version_conflict` | 409 | Work order changed since the caller read it. `details.work_order` is the current work order (field view), so the app can show a reconcile screen. (Issue endpoints keep Phase 1's `details.version`.) |
| `invalid_work_order_action` | 409 | The action doesn't fit the work order's state. `details: { state, action }`. |
| `not_assignable` | 422 | Issue status doesn't allow (re)assignment, `details.status`. |
| `team_not_eligible` | 422 | Team inactive, doesn't handle the category, or doesn't cover the ward. `details.reason`: `inactive`, `category`, `area`. |
| `assignee_not_in_team` | 422 | `assignee_id` isn't a member of the team. |
| `evidence_required` | 422 | Closure with no `after` photo and no allowed `reason_code`. `details: { allowed_reason_codes }`. |
| `invalid_media` | 422 | As Phase 1; new reasons `wrong_phase`. |
| `not_eligible` | 403 | Caller can't verify or reopen this issue (not a reporter on it). |
| `already_verified` | 409 | The caller already answered for this closure round. |
| `invalid_transition` | 422 | As Phase 1, also when an action needs a status the issue isn't in. |
| `team_has_open_work` | 409 | Deactivating a team that still holds open work orders. |

### Audit actions
`team.created`, `team.updated`, `issue.assigned`, `issue.reassigned`, `work_order.declined`, `closure.requested`, `closure.approved`, `closure.rejected`, `issue.reopened`, `issue.closed` (by the system, no actor), `issue.note_added`, `report.withdrawn`.

### Timeline event types
New `type` values on issue timelines. "Citizen" says whether the event is `public` (the citizen timeline shows `type`, `from_status`, `to_status`, `public_note`, never the reason, actor or data).

| Type | Status move | Citizen | `data` (staff only) |
|---|---|---|---|
| `assigned` | verified/reopened → assigned | yes | `{ team: {id,name}, assignee: {id,display_name}\|null, note }` |
| `reassigned` | in_progress → assigned, or none | no | same as `assigned`, plus `previous_team_id`, `previous_assignee_id` |
| `work_order_accepted` | — | no | `{ work_order_id }` |
| `work_order_declined` | assigned → verified | no | `{ work_order_id }`; reason in `reason` |
| `work_started` | assigned → in_progress | yes | `{ work_order_id }` |
| `progress` | — | no | `{ work_order_id, note, location: {lat,lng}\|null, media_ids }` |
| `closure_requested` | in_progress → pending_verification | yes | `{ closure_request_id, reason_code, note, media_ids }` |
| `closure_approved` | pending_verification → resolved | yes | `{ closure_request_id }`; optional `public_note` |
| `closure_rejected` | pending_verification → in_progress | no | `{ closure_request_id, by: "supervisor"\|"citizen" }`; reason in `reason` |
| `verification` | — or → resolved | only when it resolves | `{ closure_request_id, outcome, note }` |
| `reopened` | resolved/closed → reopened | yes | `{ by: "citizen"\|"staff" }`; reason in `reason` |
| `closed` | resolved → closed | yes | — (system, no actor) |
| `report_withdrawn` | — | no | `{ report_id }` |
| `note` (Phase 1 type, now used) | — | if `visibility: public` | body in `public_note` (public) or `reason` (internal) |

---

## 1. Teams (FR-061)

A team belongs to a department and has members, a service area (jurisdictions), the categories it handles, and a working schedule.

```json
{
  "id": "uuid", "department": { "id": "uuid", "code": "ROADS", "name": "Roads" },
  "name": "Pothole crew North", "is_active": true,
  "members": [ { "user": { "id": "uuid", "display_name": "Farah Field" }, "team_role": "lead|member" } ],
  "jurisdiction_ids": ["uuid"],
  "category_ids": ["uuid"],
  "schedule": { "timezone": "Asia/Kolkata", "days": [ { "weekday": 0, "start": "09:00", "end": "18:00" } ] },
  "created_at": "...", "updated_at": "..."
}
```
- `weekday` 0 = Monday. `start` < `end`, `HH:MM`. One entry per weekday at most. `schedule` may be `null`. Phase 3 stores it; SLA (Phase 4) reads it.
- **Covers a ward** when one of its `jurisdiction_ids` is the ward or an ancestor of it. A team with no jurisdictions covers nothing.
- Members must be active users of the tenant with a staff role.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/admin/teams` | `config:read` | Page envelope; filters `department_id`, `is_active`; sort `name` (default), `created_at`. |
| POST | `/api/v1/admin/teams` | `config:manage` | `{ department_id, name, members?, jurisdiction_ids?, category_ids?, schedule? }` → `201`. Name unique per department (`409 conflict`). |
| GET | `/api/v1/admin/teams/{id}` | `config:read` | |
| PATCH | `/api/v1/admin/teams/{id}` | `config:manage` | Any of `name`, `is_active`, `members`, `jurisdiction_ids`, `category_ids`, `schedule`. Lists **replace** the stored list. `is_active: false` with open work orders → `409 team_has_open_work`. |
| GET | `/api/v1/issues/{id}/eligible-teams` | `issue:assign` in scope | Active teams that handle the issue's category and cover its ward, most local first (a team covering the ward itself before one covering its zone, then by name). Items: `{ team: {id,name,department}, members: [...] }`. |

## 2. Assignment (FR-062, AC-10)

`POST /api/v1/issues/{id}/assignments` (`issue:assign` in scope)
```json
{ "team_id": "uuid", "assignee_id": "uuid|null", "note": "optional", "reason": "required when reassigning", "version": 4 }
```
- **First assignment** needs status `verified` or `reopened`; the issue moves to `assigned` through the system transition. Event `assigned` (public).
- **Reassignment** (an assignment is open, status `assigned` or `in_progress`) needs a `reason` (`422 reason_required`). The old assignment ends (`end_reason: reassigned`), its open work order is `cancelled`, and an `in_progress` issue moves back to `assigned`. Event `reassigned` (internal).
- Other statuses: `422 not_assignable`.
- The team must be eligible (§1) and the assignee a member of it.
- With an `assignee_id`, a work order is created in `pending_acceptance`. Team-only assignments have no work order until reassigned to a person.
- `version` is the issue's (`409 version_conflict` as in Phase 1). Returns `201` with the issue detail.
- Writes an `outbox_events` row `issue.assigned` with `{ issue_id, assignment_id, team_id, assignee_id, work_order_id }` in the same transaction. Nothing consumes it until Phase 4.

`GET /api/v1/issues/{id}/assignments` (`issue:read` in scope): all assignments, newest first:
```json
{ "id": "uuid", "team": { "id": "uuid", "name": "..." }, "assignee": { "id": "uuid", "display_name": "..." } | null,
  "note": "...", "assigned_by": { "id": "uuid", "display_name": "..." }, "assigned_at": "...",
  "ended_at": "...|null", "end_reason": "reassigned|declined|null",
  "work_order": { "id": "uuid", "state": "accepted", "version": 2 } | null }
```

**Issue detail additions** (staff): `operations: { assignment: <as above>|null, closure_request: <§5>|null }` with the open assignment and the pending closure request.

## 3. Field work orders (FR-063–FR-066)

**States:** `pending_acceptance → accepted → in_progress → completion_requested → done`, plus `declined` and `cancelled` (ends). Every change increments `version`.

| Action | From | To | Issue moves |
|---|---|---|---|
| accept | pending_acceptance | accepted | — (stays `assigned`) |
| decline | pending_acceptance, accepted | declined | assigned → verified; the assignment ends (`declined`) and the supervisor reassigns |
| start | accepted | in_progress | assigned → in_progress |
| progress | accepted, in_progress | (same) | — |
| request-closure | in_progress | completion_requested | in_progress → pending_verification |
| *(closure approved)* | completion_requested | done | — |
| *(closure rejected)* | completion_requested | in_progress | — |
| *(reassigned)* | any open | cancelled | — |

**Field view** (no reporter data):
```json
{
  "id": "uuid", "state": "accepted", "version": 2, "created_at": "...", "updated_at": "...",
  "issue": {
    "id": "uuid", "reference": "CP-26-000123", "status": "assigned",
    "category": { "id": "uuid", "code": "pothole", "name_i18n": {...}, "icon": "construction" },
    "location": { "lat": 12.97, "lng": 77.59 }, "address_text": "...", "ward": { "id": "uuid", "name": "..." },
    "priority_band": "high|null", "descriptions": ["report descriptions, oldest first"],
    "photos": [ /* media objects from the reports, display/thumb only */ ]
  },
  "evidence": [ { "...media object...": "", "phase": "before|after" } ],
  "updates": [ { "at": "...", "note": "...", "location": { "lat": 0, "lng": 0 } | null } ]
}
```

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/field/work-orders` | `workorder:read_assigned` | The caller's work orders, page envelope, newest first. Filter `state` (repeatable). Default: every state except `declined` and `cancelled`. |
| GET | `/api/v1/field/work-orders/{id}` | `workorder:read_assigned` | Field view. Someone else's: `404`. |
| POST | `…/{id}/accept` | `workorder:update` | `{ version }` |
| POST | `…/{id}/decline` | `workorder:update` | `{ version, reason }`, reason required |
| POST | `…/{id}/start` | `workorder:update` | `{ version }` |
| POST | `…/{id}/progress` | `workorder:update` | `{ version, note, location?: {lat,lng}, media_ids?: [] }`; at least a note or a photo |
| POST | `…/{id}/request-closure` | `workorder:update` | `{ version, media_ids?: [], reason_code?, note? }` (§5) |

All mutations return `200` with the field view. A stale `version` is `409 version_conflict` with the current field view in `details.work_order`; an action that doesn't fit the state is `409 invalid_work_order_action`. Retrying a request after a lost response therefore never applies it twice.

**Evidence (FR-066).** Upload with `POST /media/uploads` and `{ "purpose": "work_evidence", "phase": "before|after", ... }` (`evidence:upload`); `phase` is required for `work_evidence` and forbidden otherwise. Attach by listing `media_ids` on `progress` or `request-closure`. Rules: the caller's own, `work_evidence`, completed, not attached elsewhere (Phase 1 `invalid_media` reasons). Capture time and GPS come from EXIF as for reports; the original stays staff-only. ML (C2.1) compares `after` photos with the report photos and its `scene_match` is advice for the supervisor only.

## 4. Notes (FR-067)

`POST /api/v1/issues/{id}/notes` (`issue:update` in scope): `{ "body": "1–2000 chars", "visibility": "internal|public" }` → `201` with the timeline event. Internal notes never reach a citizen; public notes appear on the citizen timeline as `type: "note"` with the body as `public_note`. Field workers post internal notes through `progress`.

## 5. Closure and approval (FR-070, FR-071, AC-11)

**Category policy** (new category fields, editable through the existing category admin API):
- `closure_requires_approval` (bool, default `true`): when true, only a supervisor's approval resolves the issue; citizen confirmations are recorded but don't resolve it.
- `closure_reason_codes` (string list, default `[]`): reasons that allow closure without an after photo, e.g. `["no_issue_found", "handled_by_other_agency"]`.
- `post_closure_policy` (`reopen` default, or `recurrence`): stored now; used when recurrence handling lands (see Out of scope).

**Request** (`request-closure` in §3): needs at least one `after` photo on the work order (attached now or before) **or** a `reason_code` from the category's list, else `422 evidence_required`. Creates a closure request and moves the issue to `pending_verification`.

**Closure request object** (in issue detail `operations.closure_request`):
```json
{ "id": "uuid", "state": "pending|approved|rejected", "requested_by": { "id": "uuid", "display_name": "..." },
  "requested_at": "...", "reason_code": "...|null", "note": "...|null", "after_photos": [ /* media */ ],
  "requires_approval": true, "confirmations": 1, "unresolved": 0 }
```

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/issues/{id}/closure/approve` | `issue:approve_closure` in scope | `{ version, public_note? }`. Issue `pending_verification → resolved`, work order `done`, the resolution window starts. |
| POST | `/api/v1/issues/{id}/closure/reject` | `issue:approve_closure` in scope | `{ version, reason }`. Issue → `in_progress`, work order → `in_progress`. |

Both return the issue detail. No pending closure request: `422 invalid_transition`.

## 6. Verification, resolution window and reopen (FR-058, FR-072–FR-074, AC-12)

**Eligibility (Phase 3):** a citizen with a non-withdrawn report on the issue. Followers join when following exists (P3-11).

`POST /api/v1/issues/{id}/verification` (`issue:verify`): `{ "outcome": "resolved|unresolved", "note": "optional" }` → `200` with the caller's report owner view.
- Allowed while the issue is `pending_verification` or `resolved`; otherwise `422 invalid_transition`. One answer per citizen per closure round (`409 already_verified`). Ineligible: `403 not_eligible`.
- **Default rule (FR-073), applied after each answer:**
  - one `unresolved` → the closure request is rejected (`by: citizen`) and the issue goes `pending_verification → in_progress` (work order back to `in_progress`), or `resolved → reopened`;
  - otherwise, if the category doesn't require approval and at least `confirmations_required` distinct citizens answered `resolved` (default 2), `pending_verification → resolved`.
- The rule lives in one pure function the ML/data owner (C3.1) will replace with the configurable engine; the endpoint and state changes stay.

**Resolution window:** a Beat job every 15 minutes closes `resolved` issues whose `resolved_at` is older than the tenant's window (event `closed`, audit `issue.closed`). Window and threshold are tenant config:

| Method | Path | Permission | Body |
|---|---|---|---|
| GET/PUT | `/api/v1/admin/config/closure` | `config:read` / `config:manage` | `{ "resolution_window_hours": 168, "confirmations_required": 2 }` (window 1–2160 h, confirmations 1–10) |

**Reopen:** `POST /api/v1/issues/{id}/reopen` `{ "reason": "required" }` from `resolved` or `closed` → `reopened`. Callers: an eligible citizen (`issue:verify`) or staff with `issue:update` in scope. Reopened issues go back to the assignment queue (assign from `reopened`).

## 7. Reports: reject and withdraw (FR-018, FR-059)

**Reject** stays Phase 1's status change to `rejected`, which already requires an internal `reason`; the citizen guidance is the `public_note` (shown on the citizen timeline). No new endpoint.

**Withdraw:** `POST /api/v1/reports/{id}/withdraw` (the reporter, `report:read_own`) → `200` owner view with `status: "withdrawn"`.
- The report is kept (a tombstone) and stays linked to its issue; it no longer counts in `report_count` / `unique_reporter_count`, which are recounted. Event `report_withdrawn` (internal), audit `report.withdrawn`.
- Refused with `422 invalid_transition` when the issue is `resolved` or `closed`, or matching hasn't placed the report yet (`details.reason: "matching_pending"`). Withdrawing twice returns the same view.

## 8. Workload (FR-068)

`GET /api/v1/workload` (`issue:assign`): teams whose service area overlaps the caller's scope (all teams for tenant-wide supervisors).
```json
{ "items": [ { "team": { "id": "uuid", "name": "..." },
  "open": 7, "pending_acceptance": 2, "in_progress": 3, "overdue": null,
  "members": [ { "user": { "id": "uuid", "display_name": "..." }, "open": 4, "in_progress": 2 } ] } ] }
```
`open` counts work orders in `pending_acceptance`, `accepted`, `in_progress` and `completion_requested`. `overdue` is `null` until SLA targets exist (Phase 4).

## 9. Workflow defaults added

All system-only (the status endpoint refuses them); installed for every tenant, existing rows untouched:

| From | To | Done by |
|---|---|---|
| verified | assigned | assignment (Phase 1 row) |
| reopened | assigned | assignment |
| in_progress | assigned | reassignment |
| assigned | verified | decline |
| assigned | in_progress | start |
| in_progress | pending_verification | closure request |
| pending_verification | resolved | approval or confirmations |
| pending_verification | in_progress | closure rejected |
| resolved | closed | resolution window |
| resolved | reopened | reopen, unresolved verification |
| closed | reopened | reopen |

## 10. Seed additions
A "Roads North" team in ROADS with the seeded field worker (lead), covering Zone North, handling `pothole`.

## Out of scope for this contract
- Recurrence on a new report near a closed issue (PRD §16), bulk actions (A4.4), follow / add evidence / moderation (P3-11), SLA and overdue (Phase 4), notification delivery (Phase 4 reads the outbox), suspicious-verification detection (C3.2), verification photos.
