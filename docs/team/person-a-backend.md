# Person A: backend lead / tech lead

**Mission:** own the API and data model from Phase 3 to the pilot. Write each phase's contract so everyone else can work in parallel, keep `main` healthy, and make sure every endpoint enforces tenancy, scope and audit.

## You own
- `apps/api/app/domains/*`, except `ai` and `analytics`, which belong to C
- `apps/api/alembic/` (all migrations: **you are the only person who merges migrations**, to keep the revision chain linear)
- `docs/api/*` (contracts), `docs/adr/*`
- Merging to `main` for any change that crosses areas

**Your backup is C.** C reviews one of your PRs a week, and you review one of C's.

## Before you start
- Read: `IMPLEMENTATION_PLAN.md` §6–§9, PRD §6.3, §7.7–7.10, §12, §15, `docs/api/phase-*-contract.md`, `docs/adr/`.
- Know the existing patterns: RLS session handling and `system_session()`, the audit service, the idempotency helper, the error envelope, pagination, permissions (`app/domains/rbac/permissions.py`), the workflow transitions table, and `app/worker.py` (`run_async`, queues).

---

## Order of implementation

| # | Task | Sprint | Depends on | Unblocks |
|---|---|---|---|---|
| 1 | **A1.3** Phase 3 contract | S1 (due 4 Dec) | — | B2.\*, C2.1, C3.1, D2.3 |
| 2 | **A1.1** Merge the ML branch with C | S1 | C1.1, C1.2 | B1.1, D1.2 |
| 3 | **A1.2** Clean up the Phase 2 contract | S1 | A1.1 | B1.2 |
| 4 | **A1.4** Phase 3 schema and migration | S1 | A1.3 | A2.\* |
| 5 | **A2.1** Departments, teams, service areas | S2 | A1.4 | A2.2, B2.3 |
| 6 | **A2.2** Assignment and reassignment | S2 | A2.1 | A2.3, B2.2 |
| 7 | **A2.3** Work orders (accept/decline/start/progress) | S2 | A2.2 | B2.1 (real API), A3.1 |
| 8 | **A2.4** Internal notes vs public updates | S2 | A1.4 | B2.4 |
| 9 | **A3.1** Closure request + supervisor approval | S3 | A2.3, closure-policy decision | B3.1, B3.2, A3.2 |
| 10 | **A3.2** Resolution window → closed; reopen | S3 | A3.1, C3.1 | B3.3, D3.1 |
| 11 | **A3.3** Reject and withdraw report | S3 | — | B3.3 |
| 12 | **A3.4** Work-order optimistic locking | S3 | A2.3 | B3.5 |
| 13 | **A3.5** Supervisor workload API | S3 | A2.3 | B3.4 |
| 14 | **A4.1** Phase 4 contract | S3 end (8 Jan) | — | B4.\*, D4.1 |
| 15 | **A4.2** SLA config, scanner, escalation | S4 | A4.1, SLA decision | B4.3, D4.3 |
| 16 | **A4.3** Notification service + outbox | S4 | A4.1, D4.1 | B4.1, B4.2 |
| 17 | **A4.4** Bulk actions | S4 | A2.2 | B4.4 |
| 18 | **A5.4** Phase 5 contract (with C) | S4 end (22 Jan) | C4.1 | B5.\* |
| 19 | **A5.1** CSV export | S5 | — | B5.1 |
| 20 | **A5.2** Public issue API | S5 | C5.5, precision decision | B5.3 |
| 21 | **A5.3** Saved filters + announcements | S5 | — | B5.4 |
| 22 | **A6.0** Phase 6 contract (with B) | S5 end (5 Feb) | — | B6.\* |
| 23 | **A6.1** Guest reporting | S6 | Guest-reporting decision | B6.1 |
| 24 | **A6.2** Retention + anonymization | S6 | Retention decision | D6.4 |
| 25 | **A6.3** Tamper-evident audit | S6 | — | — |
| 26 | **A6.4** Security fixes | S6 | D6.1 | Launch |
| 27 | **A7.1** Real data import tools | Launch | City data | Launch |

**Why this order:**
1. **Contracts come first** in every sprint, because B and C are blocked without them.
2. **Within Phase 3, build in workflow order:** teams → assignment → work orders → closure → verification → reopen. Each step needs the state the previous one creates.
3. **Notes (A2.4) and reject/withdraw (A3.3)** are independent, so they fill gaps while you wait on reviews.

---

## Sprint 1 · 30 Nov – 11 Dec · *Close Phase 2, open Phase 3*

### A1.3 Phase 3 contract (`docs/api/phase-3-contract.md`)
Due **Fri 4 Dec**, then reviewed by B and C. Cover:
- **Teams:** `teams`, `team_members` (role in team), service areas (jurisdiction links) and supported categories per team, working schedules (FR-061).
- **Assignment:** `POST /issues/{id}/assignments { team_id, assignee_id?, note }`. Uses the system transition `verified → assigned`. Reassignment keeps history (FR-062).
- **Work orders:** states `pending_acceptance → accepted → in_progress → completion_requested → done`, plus `declined` with a reason (FR-063–065). A field worker sees **only** their assigned work orders, with minimal personal data (§4.1).
- **Field endpoints:** `GET /field/work-orders`, `GET /field/work-orders/{id}`, `POST …/accept|decline|start|progress`.
- **Evidence:** media purpose `work_evidence` with `phase: before|after` (agreed with C for C2.1).
- **Closure:** closure request → `pending_verification`; supervisor approve/reject; resolution window → `closed`; reopen request (FR-058, FR-070–074).
- **Verification:** `POST /issues/{id}/verification { outcome: resolved|unresolved, note?, media_ids? }` with eligibility rules. The rules engine itself is C3.1; you own the endpoint and state changes.
- **Report reject/withdraw** (FR-018, FR-059) and the workload view (FR-068).
- **New permissions and role mapping;** new timeline event types and whether citizens see each one.

### A1.1 Merge the ML branch (pair with C)
- Rebase C's branch onto `main`. The real `app/ai/registry.py` replaces the fake-only stub.
- Swap the stand-ins in `app/domains/ai/vision.py` for the real `phash.py`, `faces.py` and `prompts.py`.
- Compose: the regular `worker` goes back to `--queues=default`, and the `ai-worker` takes `ai`.
- Check by running the API suite, then the e2e suite, against a stack with the real `ai-worker`.

### A1.2 Phase 2 contract cleanup
Fold section K and the frontend's notes into the main text of `docs/api/phase-2-contract.md`, so it reads as one coherent document, as was done for Phases 0 and 1.

### A1.4 Phase 3 schema
One migration covering every table in A1.3, with RLS on all of them. Add a migration test that checks every new table has RLS enabled.

---

## Sprint 2 · 14 – 25 Dec · *Assignment and field work*

### A2.1 Departments, teams, service areas, schedules
Admin CRUD (audited), with a team's service area expressed as jurisdiction IDs. Add a helper that picks which team can take an issue, from its category and ward.

### A2.2 Assignment
- Assign and reassign. On assignment the status moves `verified → assigned` through the system transition.
- Assignment history stays readable.
- Emit a domain event row (`outbox_events`) for "issue assigned". It's consumed by A4.3 in S4; for now only write the row.

### A2.3 Work orders
- Accept, decline with a reason, start, progress note with optional location (FR-065).
- Status sync: accepting moves the issue to `in_progress`.
- Field-worker scoping is enforced in queries. **Test that a field worker can't read another worker's order (404) or see reporter phone/email.**

### A2.4 Internal notes
`POST /issues/{id}/notes { body, visibility: internal|public }`. Public notes reach the citizen timeline; internal ones never do (test both).

**Done when:** a supervisor assigns an issue, and the field worker accepts and starts it, all over the API with tests. B's field app works against your real endpoints by the end of S2.

---

## Sprint 3 · 28 Dec – 8 Jan · *Closure and verification* (~60% capacity)

### A3.1 Closure + approval
- Closure request requires evidence (an `after` photo) or a configured closure reason.
- A per-category policy decides whether supervisor approval is needed (FR-071).
- Approve moves the issue to `resolved`; reject sends it back to `in_progress` with a reason.

### A3.2 Resolution window and reopen
- A Beat job moves `resolved → closed` after the window, unless there's unresolved feedback.
- Negative verification, using C3.1's rules, opens a review or reopens the issue (FR-074).
- A report on a closed issue is treated as a recurrence or a reopen, depending on category policy (§16).

### A3.3 Reject / withdraw
- Reject with a reason and guidance for the citizen (FR-059).
- Withdraw leaves a tombstone; counts are recomputed and the issue is kept (FR-018).

### A3.4 Optimistic locking for work orders
`version` on work orders; a `409` with the current state so B can show a "reconcile" screen (§16).

### A3.5 Workload API
Per team: open, overdue and in-progress counts, and distribution per member (FR-068).

### A4.1 Phase 4 contract (due Fri 8 Jan)
- SLA rules by category, priority and ward (acknowledge/assign/resolve targets).
- Escalation actions.
- Notification events (§15.1), templates, channels and preferences; the in-app inbox API; the Web Push subscription API.
- The outbox design.

**Done when:** AC-10, AC-11 and AC-12 pass in D's e2e suite.

---

## Sprint 4 · 11 – 22 Jan · *SLA and notifications*

### A4.2 SLA
- SLA config tables and admin API.
- SLA state computed per issue (due at, due soon, breached).
- A Beat scanner every 5 minutes; escalation (notify supervisor, raise priority via the priority engine).
- SLA status feeds the priority factor that was a placeholder in Phase 2.

### A4.3 Notification service
- Outbox → dispatcher → channel adapters. Adapters come from D4.1, behind the interfaces you define.
- Templates per locale; preferences; de-duplication and rate limits; delivery log.
- **Move OTP SMS out of the request path into the outbox,** keeping the OTP response time fast.

### A4.4 Bulk actions
Bulk assign and status change with confirmation, per-item results and an audit entry for each.

### A5.4 Phase 5 contract (with C, due Fri 22 Jan)

**Done when:** AC-09 passes, and every §15.1 event creates an outbox row that's delivered on at least one channel.

---

## Sprint 5 · 25 Jan – 5 Feb · *Analytics and public view*
- **A5.1 CSV export:** filtered, permission and privacy aware (no reporter personal data without `user:manage`), streamed, audited (AN-002).
- **A5.2 Public issue API:** a public issue page and public map feed, using C5.5's location generalisation. No reporter data, no internal events (FR-084, FR-051).
- **A5.3** Saved filters per user (FR-077), service announcements (FR-087).
- **A6.0 Phase 6 contract (with B, due 5 Feb):** guest reporting limits, the offline sync and conflict protocol, voice upload.

## Sprint 6 · 8 – 19 Feb · *Hardening*
- **A6.1 Guest reporting** (only if approved): CAPTCHA, strict rate limits, reduced tracking (FR-002).
- **A6.2 Retention jobs:** media and personal data per the retention decision; account anonymization that keeps the issue intact (§12.2, §16).
- **A6.3 Audit hash chain:** each audit row stores the hash of the previous one, plus a verification command.
- **A6.4** Fix every high and critical finding from D6.1, and triage the medium ones.

## Launch week · 22 – 26 Feb
- **A7.1 Import tools:** ward/zone GeoJSON → jurisdictions, staff CSV → users and roles, departments and teams. Idempotent, with dry-run mode.
- On call for backend issues during the pilot.

---

## Recurring duties
- Review every PR that touches `apps/api`, except C's areas, within one working day.
- Keep `openapi.json` current: the CI staleness check must pass.
- Write an ADR for any architecture decision (queueing, outbox, retention, audit chain).
- Hold a contract review meeting (30 minutes) at the start of each phase.
