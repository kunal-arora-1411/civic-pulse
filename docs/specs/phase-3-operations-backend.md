# Spec: Phase 3 backend — operations and field (Person A, Sprints 1–3)

Covers A1.3, A1.4, A2.1–A2.4, A3.1–A3.5 from `docs/team/person-a-backend.md`.
Phase 2 close-out (A1.1, A1.2) and Phase 4+ work are separate.

## Problem Statement

Today a civic issue can be reported, classified, de-duplicated, prioritised
and moved as far as `verified`. Then it stops. A municipality has no way to
say which department and team owns the work, no way to hand it to a field
worker, no record of whether that worker accepted it, no proof the work was
done, and no way for the citizen who reported it to say "it's still broken".
The lifecycle states `assigned`, `in_progress`, `pending_verification`,
`resolved`, `closed` and `reopened` exist in the vocabulary but nothing in the
API reaches them. Supervisors can't see who is overloaded, staff can't leave
notes that citizens won't see, and operators can't reject or citizens withdraw
a report cleanly. Frontend (B) and ML (C) are blocked until the backend
publishes what these endpoints look like.

## Solution

Publish the Phase 3 contract first, then build the operational loop in
workflow order, each step creating the state the next one needs:

teams and service areas → assignment → work orders (accept / decline / start /
progress) → closure request with evidence → supervisor approval → resolution
window → citizen verification → closed or reopened.

Alongside: internal vs public notes, report reject and withdraw, optimistic
locking on work orders, and a supervisor workload view. Every new table is
tenant-scoped with row-level security, every sensitive action is audited,
and a field worker sees only their own work orders with no reporter personal
data. When this lands, AC-10, AC-11 and AC-12 pass end to end over the API.

## User Stories

### Organisation setup (FR-061)
1. As a municipal admin, I want to create, rename and deactivate teams under a department, so that work can be routed to real crews.
2. As a municipal admin, I want to add and remove staff as team members with a role in the team (lead or member), so that the team roster matches reality.
3. As a municipal admin, I want to set a team's service area as a list of jurisdictions (wards or zones), so that the system knows where the team operates.
4. As a municipal admin, I want to set which categories a team handles, so that a streetlight crew is never offered a pothole.
5. As a municipal admin, I want to set a team's working schedule (days and hours, timezone), so that later SLA work can respect working time.
6. As a municipal admin, I want every team change to be audited, so that changes to routing are traceable.
7. As a municipal admin, I want deactivating a team to be refused while it still holds open work orders, so that no work is orphaned.
8. As a supervisor, I want the system to suggest which teams can take an issue from its category and ward, so that I assign correctly without memorising the org chart.
9. As a supervisor, I want suggested teams ordered by specificity (ward match before zone match), so that the most local team is first.

### Assignment (FR-062, AC-10)
10. As a supervisor, I want to assign a verified issue to a team, optionally to a named member, with a note, so that someone owns the work.
11. As a supervisor, I want assignment to move the issue from `verified` to `assigned` automatically, so that I don't make a second status change.
12. As a supervisor, I want to reassign an issue to another team or person with a reason, so that I can correct routing or rebalance load.
13. As a supervisor, I want the previous assignment to stay readable in the issue's assignment history, so that I can see who held it and when.
14. As a supervisor, I want assignment refused when the assignee isn't a member of the chosen team or the team doesn't cover the issue's category, so that bad assignments can't happen.
15. As a supervisor, I want reassigning to cancel the old open work order and create a new one, so that the old assignee's queue is cleaned up.
16. As a citizen, I want my issue's timeline to say "Assigned to the Roads department", without the worker's name, so that I know progress is happening.
17. As a platform, I want an `issue.assigned` row written to the outbox in the same transaction, so that Phase 4 notifications can deliver it without changes here.
18. As an operator without `issue:assign`, I want assignment refused with 403, so that only supervisors route work.

### Work orders and the field queue (FR-063–FR-065)
19. As a field worker, I want to list my work orders filtered by state (pending acceptance, accepted, in progress, completion requested, done), so that I know what to do next.
20. As a field worker, I want a work order detail with category, description, location (`[lng, lat]`), address, report photos and priority, so that I can find and fix the problem.
21. As a field worker, I want the detail to exclude reporter name, phone and email, so that citizen privacy is preserved (§4.1).
22. As a field worker, I want another worker's work order to return 404, not 403, so that I can't probe for its existence.
23. As a field worker, I want to accept a work order, so that my supervisor knows I've taken it.
24. As a field worker, I want to decline a work order with a mandatory reason, so that my supervisor can reassign it.
25. As a supervisor, I want a declined work order to put the issue back in my queue as needing reassignment, so that it isn't lost.
26. As a field worker, I want to start work, which moves the issue to `in_progress`, so that the citizen sees work has begun.
27. As a field worker, I want to post progress notes with an optional location and timestamp, so that my supervisor can follow along.
28. As a field worker, I want to upload before and after photos as work evidence with capture time and optional location, so that completion is provable (FR-066).
29. As a field worker, I want an action that doesn't fit the work order's current state to return 409 with the current state, so that my app shows what really happened.
30. As a field worker working offline, I want a stale update (old `version`) to return 409 with the current work order, so that the app shows a reconcile screen instead of overwriting newer changes (§16).
31. As a supervisor, I want every work-order transition recorded with actor and time, so that I can audit field activity.

### Notes (FR-067)
32. As an operator or supervisor, I want to add an internal note to an issue, so that staff can coordinate without citizens seeing it.
33. As an operator or supervisor, I want to add a public update to an issue, so that citizens hear from the municipality directly.
34. As a citizen, I want to see public updates and never internal notes in my timeline, so that I get relevant information only.
35. As a field worker, I want my progress notes to be internal by default, so that half-finished observations aren't published.

### Closure and approval (FR-070, FR-071, AC-11)
36. As a field worker, I want to request closure with at least one after photo or a configured closure reason (for example "duplicate of existing work"), so that closure always has justification.
37. As a field worker, I want closure refused with a clear error when neither evidence nor an allowed reason is given, so that I fix it before leaving the site.
38. As a municipal admin, I want a per-category policy saying whether closure needs supervisor approval, so that high-risk categories get a second look.
39. As a supervisor, I want closure requests on approval-required categories to land the issue in `pending_verification`, so that I review them.
40. As a supervisor, I want to see C's before/after scene-match score as advice next to the evidence, so that I can spot mismatched photos without the AI deciding (§8.6).
41. As a supervisor, I want to approve a closure, moving the issue to `resolved`, so that the resolution window starts.
42. As a supervisor, I want to reject a closure with a reason, moving the issue back to `in_progress` and the work order back to in progress, so that the worker returns.
43. As a field worker on a category that doesn't require approval, I want closure to go to `pending_verification` and then follow the verification rule, so that citizens can still confirm.
44. As an operator with `issue:update` but not `issue:approve_closure`, I want approve refused with 403, so that approval stays with supervisors.

### Verification, resolution window and reopen (FR-058, FR-072–FR-074, AC-12)
45. As a citizen who reported or follows an issue, I want to confirm it is resolved or say it is unresolved, with an optional note and photo, so that the municipality hears from the street.
46. As a citizen who neither reported nor follows the issue, I want verification refused, so that strangers can't decide closure.
47. As a citizen, I want my second vote on the same issue refused (or treated as an update of my first), so that each person counts once.
48. As a platform, I want verification eligibility and the closure rule decided by C's rules engine and the state changes applied here, so that the policy lives in one place.
49. As a citizen, I want a single "still unresolved" response to send the issue to review or reopen it according to policy, so that one honest complaint is enough to trigger a look.
50. As a supervisor, I want a resolved issue to move to `closed` automatically after the resolution window, unless there is unresolved feedback, so that closure doesn't need manual work.
51. As a municipal admin, I want the resolution window configurable per tenant, so that it fits local practice.
52. As a citizen, I want to request reopening of a resolved or closed issue that has come back, so that recurring problems are tracked (FR-058).
53. As a platform, I want a new report on a closed issue to become either a reopen request or a new linked recurrence issue depending on category policy, so that history is kept (§16).
54. As a supervisor, I want reopened issues to return to my queue with the reopen reason visible, so that I can reassign them.

### Reject and withdraw (FR-018, FR-059)
55. As an operator, I want to reject a report with a reason code and citizen-facing guidance (for example "out of jurisdiction, contact the state highway authority"), so that the citizen knows what to do.
56. As a citizen, I want to see the rejection guidance on my report, but not internal reasons, so that I'm informed without exposing staff discussion.
57. As a citizen, I want to withdraw my own report, so that I can retract a mistake.
58. As a platform, I want a withdrawn report kept as a tombstone with the issue intact and report counts recomputed, so that audit and other reporters aren't affected.
59. As a citizen, I want withdrawal refused once the issue is already resolved or closed, so that history stays coherent.

### Workload (FR-068)
60. As a supervisor, I want per-team counts of open, in-progress and overdue work orders, so that I can see where work is piling up.
61. As a supervisor, I want per-member distribution within a team, so that I can rebalance.
62. As a supervisor, I want the workload view limited to teams in my jurisdiction scope, so that I see only what I manage.

### Cross-cutting
63. As any tenant, I want every new table protected by row-level security, so that another municipality can never read my data.
64. As a security reviewer, I want each new endpoint to have a permission-denied test and a cross-tenant test, so that access control is proven.
65. As a frontend developer, I want the Phase 3 contract published by 4 Dec with examples, so that I can build against MSW mocks in parallel.
66. As an ML engineer, I want the `work_evidence` media purpose with `phase: before|after` fixed in the contract, so that C2.1 can start.
67. As a frontend developer, I want every new timeline event type to state whether citizens see it, so that the citizen timeline is correct.
68. As a frontend developer, I want new error codes in the existing error envelope and lists in the existing pagination shape, so that client code doesn't fork.
69. As a field worker with a flaky connection, I want field mutations to honour the existing idempotency key, so that retries don't double-accept or double-post notes.
70. As a Hindi-speaking citizen, I want public timeline text and rejection guidance available in Hindi, so that I can read it.

## Implementation Decisions

**Contract (A1.3).** `docs/api/phase-3-contract.md`, structured like Phase 2's,
due 4 Dec and reviewed by B and C. Any later deviation updates it in the same
commit. Uses existing conventions: error envelope, pagination, idempotency
keys, `[lng, lat]` coordinates.

**Schema (A1.4).** One migration (0007) adding, all tenant-scoped with RLS
and composite `(tenant_id, …)` foreign keys like the existing tables:
- `teams` (department, name, active), `team_members` (user, team role),
  `team_jurisdictions` (service area as jurisdiction links),
  `team_categories`, `team_schedules` (weekday, start, end, timezone).
- `issue_assignments` (issue, team, assignee nullable, note, assigned_by,
  ended_at, end_reason). One open assignment per issue, enforced by a partial
  unique index; history is the closed rows.
- `work_orders` (issue, assignment, assignee, state, decline_reason,
  `version` integer for optimistic locking, timestamps per transition).
  States: `pending_acceptance → accepted → in_progress →
  completion_requested → done`, plus `declined` and `cancelled`
  (reassignment). Enforced by a CHECK on the state vocabulary; allowed moves
  live in code, since they are not tenant-configurable.
- `work_order_updates` (progress note, optional point, actor).
- `closure_requests` (issue, work order, reason code nullable, note, state
  `pending|approved|rejected`, decided_by, decision_reason).
- `issue_verifications` (issue, user, outcome `resolved|unresolved`, note),
  unique on `(issue, user)` for one vote per person.
- `outbox_events` (aggregate, event type, payload JSON, created_at,
  dispatched_at null). Write-only in Phase 3.
- Category policy columns: `closure_requires_approval`,
  `allowed_closure_reasons`, `post_closure_policy` (`reopen|recurrence`).
- Tenant config: resolution window (default from decision; placeholder
  7 days).
- Report columns for withdrawal (`withdrawn_at`) and rejection
  (`rejection_code`, `citizen_guidance`).
- `MediaPurpose.WORK_EVIDENCE` with a `phase` column (`before|after`)
  required for that purpose.
- New `EventType`s: `assigned`, `reassigned`, `work_order_accepted`,
  `work_order_declined`, `work_started`, `progress`, `closure_requested`,
  `closure_approved`, `closure_rejected`, `verification`, `reopened`,
  `report_withdrawn`, `report_rejected`. Citizen-visible: assigned (team
  name only), work_started, closure_approved, reopened, report_rejected
  (guidance only), and public notes. Everything else internal.

**Workflow transitions.** Extend `DEFAULT_TRANSITIONS` and the frozen copy
in the migration: `assigned → in_progress`, `in_progress →
pending_verification`, `pending_verification → resolved`,
`pending_verification → in_progress`, `resolved → closed`, `resolved →
reopened`, `closed → reopened`, `reopened → assigned`, and a path back to
`verified` on decline. Moves driven by assignment, work orders, closure and
the Beat job are `system_only`; the generic status endpoint keeps refusing
them. Existing tenants get the new rows through the idempotent installer,
which preserves tenant changes.

**Permissions.** Reuse the declared ones (`issue:assign`,
`issue:approve_closure`, `workorder:read_assigned`, `workorder:update`,
`evidence:upload`, `issue:verify`). Add `team:manage` (municipal admin),
`issue:note_internal` (operator, supervisor, field worker),
`report:reject` (operator, supervisor), `report:withdraw_own` (citizen),
`workload:read` (supervisor, admin). All staff permissions stay behind staff
MFA.

**Modules.**
- `org`: team CRUD, membership, service areas, schedules, and
  `eligible_teams(category, jurisdiction)` — the only routing helper.
- New `assignments` domain: assign/reassign, assignment history, outbox
  write. Owns the `verified → assigned` system transition.
- New `workorders` domain: state machine as one pure function
  `next_state(current, action) -> state | error` plus a service that applies
  it with the `version` check (`UPDATE … WHERE version = :v`; zero rows →
  409 carrying current state). Field router under `/field/work-orders`
  scopes every query by `assignee_id = principal`, returning 404 otherwise,
  and serialises with a field-specific schema that has no reporter fields.
- New `closure` domain: closure request, approve/reject, verification
  endpoint, resolution-window Beat job, reopen. Calls C3.1's rules engine
  through its function interface; does not reimplement eligibility.
- `issues`: notes endpoint with visibility; citizen timeline filter extended
  for new event types.
- `reports`: reject and withdraw; withdraw recomputes issue counts with the
  existing consolidation helpers.
- Workload: read-only aggregate query, inside `workorders`.

**Endpoints (summary; the contract has the shapes).**
- Admin: `GET/POST/PATCH /admin/teams`, `PUT /admin/teams/{id}/members`,
  `…/service-area`, `…/categories`, `…/schedule`; `GET
  /issues/{id}/eligible-teams`.
- `POST /issues/{id}/assignments`, `GET /issues/{id}/assignments`.
- `GET /field/work-orders`, `GET /field/work-orders/{id}`, `POST
  /field/work-orders/{id}/accept|decline|start|progress|request-closure`;
  each mutation takes `version`.
- `POST /issues/{id}/closure/approve|reject`.
- `POST /issues/{id}/verification` `{ outcome, note?, media_ids? }`.
- `POST /issues/{id}/reopen-requests`.
- `POST /issues/{id}/notes` `{ body, visibility }`.
- `POST /reports/{id}/reject`, `POST /reports/{id}/withdraw`.
- `GET /workload?team_id=`.

**Status sync rules.** Accept → issue stays `assigned`; start → `in_progress`
(the plan said "accepting moves to in_progress"; the contract will pick one —
start is recommended so `assigned` means "acknowledged, not yet on site").
Request closure → `pending_verification`. Approve → `resolved`. Reject
closure → `in_progress`. Decline → assignment ended, issue back to `verified`
with a "needs reassignment" flag in the queue.

**Background job.** `close_resolved_issues` on Beat (queue `default`, never
`ai`), runs every 15 minutes under `system_session()` per tenant, moves
`resolved` issues past their window with no open `unresolved` verification
to `closed`. Idempotent.

**Audit.** Team changes, assignment, reassignment, closure approve/reject,
report reject, report withdraw and reopen go through the audit service.

**ADR.** One ADR for the outbox (table shape, same-transaction write,
consumer arrives in Phase 4).

## Testing Decisions

- Test external behaviour at the HTTP API through the existing async test
  client and factories; assert on responses, timeline output and DB state
  visible through the API, not on internal function calls.
- **Seams (proposed, highest first):**
  1. The HTTP API — almost every story is tested here, using the
     `phase1`/`phase2` helper pattern (a `phase3` helper that builds a
     verified issue with a team and a field worker).
  2. The migration — one test that every table created by 0007 has RLS
     enabled and forced, plus downgrade/upgrade, extending
     `test_migrations.py`.
  3. The resolution-window job — called directly as a function with a
     controlled clock, since Beat scheduling itself isn't worth testing.
  4. The work-order `next_state` function — a small table test of allowed
     and refused moves, because the matrix is easier to read there than
     through HTTP.
- Required per endpoint: happy path, permission-denied (403), cross-tenant
  (404/invisible), and validation failure.
- Field privacy: a field worker gets 404 on another worker's order; the
  field detail response contains no reporter phone, email or name (assert
  on the raw JSON keys).
- Notes: internal note absent from the citizen timeline; public note present.
- Optimistic locking: two updates with the same `version`, second gets 409
  with the current state.
- Verification: ineligible citizen refused; second vote refused; one
  `unresolved` triggers review/reopen; two confirmations resolve.
- AC-10/11/12 as one API-level test of the full loop, then D's e2e suite.
- Prior art: `test_workflow.py` (transitions, installer idempotency),
  `test_tenancy.py` (RLS), `test_access_control.py` (denials),
  `test_review.py` and `test_consolidation.py` (multi-step issue flows and
  count recomputation), `test_audit.py`, `test_idempotency.py`.

## Out of Scope

- Phase 2 close-out (A1.1 ML merge, A1.2 contract cleanup, e2e work).
- SLA targets, scanner and escalation (A4.2); outbox dispatch and all
  notification delivery (A4.3). Phase 3 only writes outbox rows.
- Bulk assign/status (A4.4), even though the plan lists P3-12 in Phase 3.
- Follow issue, add-evidence-to-existing-issue and the moderation queue
  (P3-11, FR-017/085/086) — not in Person A's Sprint 1–3 list; needs an owner.
- The verification rules engine and suspicious-pattern detection (C3.1,
  C3.2) and the scene-match score (C2.1) — consumed, not built here.
- All frontend work (B) and e2e suites (D).
- Offline sync protocol beyond the `version`/409 behaviour (Phase 6 contract).

## Further Notes

- **Pending decisions:** closure approval policy per category (needed 21
  Dec) — until then default `closure_requires_approval = true` for all
  categories. Resolution window length and post-closure policy have no
  scheduled decision; defaults (7 days, `reopen`) are placeholders the
  contract must flag.
- **Follow eligibility gap:** FR-072 lets followers verify, but following is
  P3-11 and unowned. Until it lands, eligibility is reporters only.
- **Known gap carried forward:** issue scope is jurisdiction-only; teams give
  a natural place to add category scoping for supervisors — worth deciding in
  the contract review.
- Commit rules from `CLAUDE.md` apply to every agent brief, including no AI
  attribution trailers.
