# Person B: frontend lead

**Mission:** own everything users touch: the citizen PWA, the staff console and the field app. Keep it fast on low-end phones, accessible (WCAG 2.2 AA) and fully bilingual.

## You own
- `apps/web/` (all routes, components, the API client, i18n messages, tests)
- The design system in `apps/web/src/components/ui`
- Accessibility and language quality

**Your backup is D.** D owns e2e and accessibility automation and reviews one of your PRs a week.

## Before you start
- Read: `apps/web/AGENTS.md` (Next.js 16.4 has breaking changes; read `node_modules/next/dist/docs/` for anything new you use), PRD §9, §15.2, `docs/api/phase-*-contract.md`.
- Read the Phase 0–2 commit bodies (`git log --format='%s%n%b' -- apps/web`). They record the hard-won Next 16 lessons:
  - `<Activity>` keeps routes mounted
  - the locale is a route param
  - `usePathname` affects the static shell
  - `params` with `use()` inside Suspense
  - Leaflet loading
  - single-flight token refresh
- Work against mocks (MSW) as soon as a contract exists; never wait for the backend.

---

## Order of implementation

| # | Task | Sprint | Depends on | Unblocks |
|---|---|---|---|---|
| 1 | **B1.3** Field app UX design (wireframes, flows) | S1 | — | B2.1 |
| 2 | **B1.4** Review the Phase 3 contract | S1 (by 8 Dec) | A1.3 | B2.\* |
| 3 | **B1.2** Switch to the generated API client (orval) | S1 | A1.2 (stable `openapi.json`) | Every later API change is cheaper |
| 4 | **B1.1** Polish the Phase 2 UI against the real API | S1 | A1.1 | M1 |
| 5 | **B2.1** Field app: queue, detail, accept/decline/start/progress | S2 | A1.3 (mocks), A2.3 (real) | B3.1 |
| 6 | **B2.2** Assign dialog + team picker | S2 | A2.2 | D3.1 |
| 7 | **B2.3** Team/department admin pages | S2 | A2.1 | — |
| 8 | **B2.4** Internal vs public notes UI | S2 | A2.4 | — |
| 9 | **B3.1** Field closure request with before/after capture | S3 | A3.1, C2.1 | D3.1 |
| 10 | **B3.2** Supervisor approval UI | S3 | A3.1 | D3.1 |
| 11 | **B3.3** Citizen "Is it fixed?" verification + reopen | S3 | A3.2, C3.1 | D3.1 |
| 12 | **B3.4** Supervisor workload view | S3 | A3.5 | — |
| 13 | **B3.5** Work-order conflict (409) screen | S3 | A3.4 | B6.2 |
| 14 | **B4.1** Notification inbox + preferences | S4 | A4.1 (mocks), A4.3 | — |
| 15 | **B4.2** Web Push subscription + service worker | S4 | A4.1, D4.1 (VAPID) | B6.1 |
| 16 | **B4.3** SLA badges + overdue filters | S4 | A4.2 | D4.3 |
| 17 | **B4.4** Bulk actions UI | S4 | A4.4 | — |
| 18 | **B5.1** Dashboard (ECharts) | S5 | A5.4 (mocks), C5.1 | M4 |
| 19 | **B5.2** Hotspot map + period comparison | S5 | C5.2 | — |
| 20 | **B5.3** Public issue page + public map | S5 | A5.2, C5.5 | — |
| 21 | **B5.4** Saved filters | S5 | A5.3 | — |
| 22 | **B5.5** Analytics assistant chat UI | S5 | C5.3 | — |
| 23 | **B6.1** PWA install + offline report drafts | S6 | A6.0, B4.2 | — |
| 24 | **B6.2** Field offline queue + sync conflicts | S6 | A6.0, B3.5 | — |
| 25 | **B6.3** Regional language | S6 | Language decision | — |
| 26 | **B6.4** Voice input UI | S6 | C6.1 | — |
| 27 | **B6.5** WCAG 2.2 AA fixes | S6 | D5.3, D6 audit | Launch |
| 28 | **B7.1** Help pages + staff training material | Launch | — | Launch |

**Why this order:**
1. **The field app design (B1.3) needs no API**, so it starts on day 1 and fills the wait for the Phase 3 contract.
2. **The generated client (B1.2) comes before Phase 3 screens.** Every new endpoint then comes typed for free, instead of adding more hand-written schemas you'd have to migrate later.
3. **Field work orders (B2.1) come before closure (B3.1)**, because closure is a step inside the work-order screen.
4. **Web Push (B4.2) introduces the service worker** that the offline work (B6.1/B6.2) builds on. Getting it in early avoids a rewrite in S6.

---

## Sprint 1 · 30 Nov – 11 Dec

### B1.3 Field app UX design
- Paper or Figma wireframes for: work queue (assigned, accepted, in progress, done), work order detail (map, directions link, photos, description, no reporter personal data), and accept / decline with reason / start / progress note / request closure with before/after photos.
- One-handed use on a 360 px phone with large tap targets. Plan for poor connectivity from the start: show a "queued" state on every action.
- Review it with a field supervisor if possible.

### B1.2 Generated API client
- Set up orval in `packages/api-client` against `apps/api/openapi.json`. Keep the existing `apiRequest` as the custom mutator; it already matches orval's signature.
- Migrate the call sites one domain at a time; delete the hand-written zod schemas once their generated replacements are in.
- CI regenerates the client and fails on any diff (ask D to wire this up).

### B1.1 Phase 2 polish against the real API
- Re-run every Phase 2 screen against the real stack once A1.1 lands: the review queue, merge/split, overrides, settings.
- Fix shape mismatches at the right layer, and tell A if the API is the problem.
- Known gap to close: after resolving a review task, show the reference of the newly created issue.

## Sprint 2 · 14 – 25 Dec
- **B2.1 Field app.** Under the existing `(field)` route group:
  - queue with filters and pull-to-refresh
  - work order detail with a lazy-loaded mini-map
  - accept / decline (with reason) / start / progress note
  - build against MSW mocks from A1.3 first, then switch to the real API when A2.3 lands
- **B2.2** Assign dialog on staff issue detail: a team picker filtered by category and ward, an optional assignee, and a note.
- **B2.3** Admin pages for departments, teams, members, service areas and schedules.
- **B2.4** Notes composer with an internal/public toggle. Internal notes are visually distinct, and the citizen view never shows them.

## Sprint 3 · 28 Dec – 8 Jan (~60% capacity)
- **B3.1 Field closure.** Camera capture for an `after` photo (and `before` if not taken earlier); a side-by-side preview; a closure reason. Uses the existing upload pipeline (compression, progress, retry) with purpose `work_evidence`.
- **B3.2 Supervisor approval.** A queue of closure requests with before/after comparison and C's scene-similarity flag (shown as advice, never as a verdict), plus approve and reject with a reason.
- **B3.3 Citizen verification.** "Is it fixed?" on the report detail for eligible citizens, with yes / no plus an optional photo. A "still a problem" reopen request.
- **B3.4** Supervisor workload view: load per team and member, and overdue items.
- **B3.5** A 409 reconcile screen for work orders, showing what changed and letting the user choose.

## Sprint 4 · 11 – 22 Jan
- **B4.1** In-app notification inbox (bell with unread count, list, mark read) and preferences per channel and event. Wording is safe for lock screens.
- **B4.2** Web Push: subscribe/unsubscribe and a service worker (Serwist). Keep the service worker minimal now; it grows in S6.
- **B4.3** SLA badges (due soon / breached, with icon and text, never colour alone) and overdue filters in the queue and on the map.
- **B4.4** Bulk select in the queue, with bulk assign and status change, a confirmation step and a per-item result summary.

## Sprint 5 · 25 Jan – 5 Feb
- **B5.1 Dashboard:**
  - KPI tiles, trends, breakdowns by category, ward and department, response times, SLA compliance
  - every number links to its metric definition (AN-004)
  - filters synced to the URL (AN-001)
  - use the `dataviz` guidelines for chart colours and accessibility
- **B5.2** Hotspot map with h3 cells, a period-comparison toggle and a legend.
- **B5.3** Public issue page and public map: generalized locations, no personal data, status history, shareable URLs.
- **B5.4** Saved filters (save, rename, delete, set default).
- **B5.5** Assistant chat panel: streaming answers, each one showing "period · filters · data used", and a clear refusal state.

## Sprint 6 · 8 – 19 Feb
- **B6.1 PWA.** Install prompt, offline report drafts in IndexedDB (Dexie), photos queued, "will send when online".
- **B6.2 Field offline queue.** Actions queued with idempotency keys and synced on reconnect; conflicts use the B3.5 screen.
- **B6.3** The pilot city's regional language: full message file, reviewed by a native speaker.
- **B6.4** Voice input: record, transcribe (C6.1), edit the transcript before submitting.
- **B6.5** Fix every axe and manual audit finding on the key flows (report, my reports, login, field, queue, detail).

## Launch week
- **B7.1** Citizen help pages (how to report, what happens next, privacy) in all languages; one-page staff guides per role.

---

## Recurring duties
- **Every user-facing string goes through i18n.** English and Hindi keys must stay identical (CI test).
- Screenshot each new screen at 390 px and desktop, in both languages, before the PR.
- Review UX-affecting backend changes for their effect on the UI.
