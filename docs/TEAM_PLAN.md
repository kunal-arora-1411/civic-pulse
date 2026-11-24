# CivicPulse — Team Plan (4 people)

**Prepared:** 24 November 2026 · **Covers:** remaining work from Phase 2 close-out to pilot go-live · **Source:** [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md)

---

## 1. Where we are

| Phase | Status |
|---|---|
| P0 Foundations | ✅ Done: tenancy (RLS), OTP auth, roles, audit, compose stack, CI config |
| P1 Core reporting loop | ✅ Done: report flow, photo uploads, issue queue, map, workflow, e2e suite |
| P2 AI layer | 🟡 Nearly done: matching, review queue, merge/split and priority are merged. The real vision model (CLIP), face blurring and evaluation are still being finished. |
| P3 Operations and field | ⬜ Not started |
| P4 SLA and notifications | ⬜ Not started |
| P5 Analytics | ⬜ Not started |
| P6 Hardening and pilot | ⬜ Not started |

**Individual plans:** each person's tasks, in build order, with dependencies, are in [`docs/team/`](team/README.md).

**Remaining:** about 13 weeks to pilot go-live with 4 people, starting **Mon 30 Nov 2026**, with go-live in the week of **22 Feb 2027**. The schedule allows for the holidays in late December.

---

## 2. Roles and ownership

Each person **owns** an area: they make the decisions, review changes to it, and answer for it. Anyone can still work anywhere. Assign real names here:

| | Role | Owns | Code areas | Main phases |
|---|---|---|---|---|
| **A** | **Backend lead / tech lead** | API design, API contracts, domain logic, data model, security model. Merges to `main`. | `apps/api/app/domains/*` (except analytics and AI), `apps/api/alembic`, `docs/api`, `docs/adr` | P3 ops backend, P4 SLA and notifications backend, P6 security and data retention |
| **B** | **Frontend lead** | Citizen app, staff console, field app, design system, i18n, accessibility | `apps/web` | P3 field app and staff ops UI, P4 notification UI, P6 offline/PWA, languages, WCAG |
| **C** | **ML and data engineer** | AI models and evaluation, matching quality, trust and abuse signals, analytics and hotspots, analytics assistant | `apps/api/app/ai`, `apps/api/app/domains/ai`, `apps/api/app/domains/analytics`, `apps/api/scripts/eval`, `docs/eval` | P2 close-out, P3 verification integrity, P5 analytics (backend + dashboards), P6 voice and abuse |
| **D** | **Platform and QA engineer** | CI/CD, environments, infrastructure, observability, e2e/load/security testing, external providers (SMS, email, push, maps), release management | `infra/`, `.github/`, `e2e/`, deployment and runbooks | Every phase: test automation and environments. P4 provider integrations. P6 pilot readiness. |

**Backups:** A ↔ C on backend and data, B ↔ D on frontend and e2e. Each backup reviews at least one PR a week in the other person's area so nobody is a single point of failure.

**Suggested `CODEOWNERS`:**
```
/apps/api/                    @A
/apps/api/app/ai/             @C
/apps/api/app/domains/ai/     @C
/apps/api/app/domains/analytics/ @C
/apps/api/scripts/eval/       @C
/apps/web/                    @B
/infra/ /.github/ /e2e/       @D
/docs/api/                    @A @B
```

---

## 3. Timeline at a glance

```
                 S1          S2          S3          S4          S5          S6        Launch
Week:           1–2         3–4         5–6         7–8         9–10       11–12        13
Starts:       30 Nov      14 Dec      28 Dec      11 Jan      25 Jan      8 Feb      22 Feb
              ─────────── ─────────── ─────────── ─────────── ─────────── ─────────── ───────
A Backend     P2 close +  Assign &    Closure,    SLA, esc-   Exports,    Retention,  Launch
              P3 contract work orders verify,     alation,    public API, guest, sec  support
                                      reopen      notify core announce    fixes
B Frontend    P2 polish + Field app + Closure &   Notif. UI,  Dashboard,  Offline,    Launch
              API client  assign UI   verify UI   SLA badges  public map  langs, a11y support
C ML & data   Real model, Before/     Verify      Metric defs Hotspots,   Voice,      Launch
              eval, AI    after evid- integrity & + analytics assistant,  abuse sig-  support
              worker      ence checks abuse rules views       AI quality  nals
D Platform/QA CI live,    Staging,    Ops e2e,    SMS/email/  Scheduled   Pen test,   Go-live
              P2 e2e,     observ-     load base-  push provi- reports,    load, DR,   checklist
              start DLT   ability     line        ders        perf + axe  runbooks
              ─────────── ─────────── ─────────── ─────────── ─────────── ─────────── ───────
Milestone      M1 AI done              M2 Ops done   M3 Notify  M4 Insight  M5 Ready   🚀 Pilot
```
> **Holiday buffer:** sprint S3 (28 Dec – 8 Jan) is planned at about 60% capacity.

---

## 4. Sprint-by-sprint breakdown

Each item has an owner (**A/B/C/D**), plus the PRD or acceptance-criteria references it delivers. "Done" means the plan's §13 definition of done is met.

### Sprint 1 · 30 Nov – 11 Dec · *Close Phase 2, open Phase 3*
| Owner | Work | Delivers |
|---|---|---|
| C | Finish the real model: CLIP on ONNX, perceptual hash, YuNet face blur, `ai-worker` container; run the evaluation and publish `docs/eval/phase-2-baseline.md`; tune thresholds from it | FR-020, FR-026, §8.1–8.2, §8.6 |
| C + A | Merge the ML branch: real `registry.py`, workers back on their own queues, remove the stand-ins in `domains/ai/vision.py`; 50-concurrent-reports test | FR-036, AC-02–AC-06 |
| A | Write the **Phase 3 contract** (teams, assignments, work orders, closure, verification, reopen). B and C review it by day 5. | — |
| A | Clean up the Phase 2 contract: merge the agents' notes into one document | AN-004-style clarity |
| B | Polish the Phase 2 UI against the real API; switch to a client **generated from `openapi.json`** (orval) | P0-11 debt |
| D | Create the GitHub repo and get **CI green on GitHub** for the first time (API, web, e2e, ML jobs); branch protection | §13 |
| D | Update the e2e suite for Phase 2 behaviour (matching status, priority sort, new nav); add e2e checks for AC-04 to AC-08 | AC-04–AC-08 |
| D | **Start SMS DLT registration** (sender ID and templates) with the chosen provider, since approval takes weeks | P4 dependency |

**🏁 M1 (11 Dec):** the real AI runs end to end in compose, every AI acceptance criterion passes in CI, and the baseline evaluation is published.

### Sprint 2 · 14 – 25 Dec · *Assignment and field work*
| Owner | Work | Delivers |
|---|---|---|
| A | Departments, teams, service areas, schedules; assignment and reassignment; accept or decline with a reason; work-order states; internal notes separate from public updates | FR-061–FR-065, FR-067 |
| B | **Field app** (mobile): work queue, work order detail with map and directions, accept / start / progress note | FR-064, FR-065, §9.3 |
| B | Staff: assign dialog, team picker, internal vs public notes | FR-062, FR-067 |
| C | Before/after evidence capture with capture time and location; AI check that the "after" photo shows the same scene as "before" (similarity flag shown to supervisors, never decisive) | FR-066, §8.6 |
| D | Staging environment (India region) with automatic deploys from `main`; Sentry + OpenTelemetry → Grafana; health alerts | §13 observability |

### Sprint 3 · 28 Dec – 8 Jan · *Closure and verification* (holiday sprint, about 60% capacity)
| Owner | Work | Delivers |
|---|---|---|
| A | Closure request with evidence → pending verification; supervisor approval; resolution window → closed; reopen; reject or withdraw a report; optimistic locking on work orders | FR-018, FR-058, FR-059, FR-070, FR-071, FR-074 |
| B | Closure and approval UI; citizen "is it fixed?" verification; reopen request; supervisor workload view | FR-068, FR-072 |
| C | Community verification rules (the FR-073 default rule), one vote per person, trust and rate limits, suspicious-pattern flags | FR-073, FR-075, §12.3 |
| D | e2e for **AC-10 to AC-12**; k6 load-test baseline; field-app conflict tests | AC-10–AC-12 |

**🏁 M2 (8 Jan):** the full operations loop works: assign → field work → evidence → closure → citizen verifies or disputes → reopen.

### Sprint 4 · 11 – 22 Jan · *SLA, escalation and notifications*
| Owner | Work | Delivers |
|---|---|---|
| A | SLA config by category, priority and ward; SLA scanner (Celery Beat); escalation rules; notification service with an **outbox** (SMS also moves out of the request path); de-duplication and rate limits; bulk actions | FR-041, FR-056, FR-057, FR-078, FR-081, §15 |
| B | In-app notification inbox, preferences, Web Push subscription, lock-screen-safe wording; SLA badges and overdue filters | §15.2, §9.2 |
| C | Metric definitions document (AN-004) and analytics materialized views, ready for Sprint 5 | AN-004 |
| D | Provider integrations behind interfaces: SMS (DLT templates), email, Web Push (VAPID); delivery logging; outage drills | §11.3, §16 |

**🏁 M3 (22 Jan):** **AC-09** passes, and every §15.1 event delivers on at least one channel.

### Sprint 5 · 25 Jan – 5 Feb · *Analytics and public view*
| Owner | Work | Delivers |
|---|---|---|
| C | Analytics API (counts, response times, SLA compliance, duplicate and review rates); hotspots with h3 cells and period comparison; recurring locations; **analytics assistant** (LLM with read-only tools, scoped to each user's permissions); AI quality trends | FR-047–FR-049, AI-001–AI-005, §14.1 |
| B | Dashboard UI (ECharts), hotspot map, public issue page and public map with generalized locations, saved filters | FR-051, FR-077, FR-084 |
| A | CSV export (permission and privacy filtered, audited); public issue API; service announcements | AN-002, FR-084, FR-087 |
| D | Scheduled summary emails; query performance tuning; **axe accessibility checks in CI** | AN-003, §13 |

**🏁 M4 (5 Feb):** dashboard numbers match hand-run SQL; the assistant refuses questions outside the user's scope.

### Sprint 6 · 8 – 19 Feb · *Hardening*
| Owner | Work | Delivers |
|---|---|---|
| A | Guest reporting (if approved); retention and anonymization jobs; tamper-evident audit (hash chain); fixes from the security review | FR-002, §12.1–12.2 |
| B | PWA: offline report drafts, offline field queue with sync and conflict screen; full Hindi plus the pilot city's regional language; voice input UI; WCAG 2.2 AA fixes | FR-013, FR-014, FR-069, §9.1 |
| C | Voice transcription (Bhashini or faster-whisper); abuse signals (repeat images, EXIF time mismatch, verification bursts); refresh thresholds with real correction data | FR-013, §12.3 |
| D | External penetration test; k6 at pilot load (p95 < 500 ms); AI, maps and SMS outage drills (**AC-15**); production infrastructure; backups with a **tested restore**; runbooks | AC-15, §13 |

**🏁 M5 (19 Feb):** all of **AC-01 to AC-15** pass on staging; no open high or critical security findings.

### Launch week · 22 – 26 Feb
| Owner | Work |
|---|---|
| D | Production deploy and go-live checklist; on-call rota |
| A | Load real ward boundaries, departments and staff accounts |
| B | Citizen help pages; staff training materials |
| C | Monitoring of AI quality and matching on live data |
| All | Pilot in 1–2 wards, daily triage of feedback |

---

## 5. Cross-team dependencies

| Needed by | What | From | By |
|---|---|---|---|
| B, C, D | Phase 3 contract | A | S1, day 5 |
| A (P4) | DLT-approved SMS templates | D | Started S1, needed S4 |
| B (S1) | Stable `openapi.json` on `main` | A | S1 |
| C (S5) | Metric definitions + materialized views | C (S4) | End of S4 |
| Everyone | Staging environment | D | End of S2 |
| A, D (launch) | Real ward boundaries, departments, staff list | Municipality | Mid-S5 |
| C (S5) | Approval to use a hosted LLM (data residency) | Municipality / product owner | Start of S5 |

---

## 6. How we work

- **Contract first.** Each phase starts with a short API contract in `docs/api/`, owned by A and reviewed by B and C. Frontend and backend build in parallel against it, using mocks (MSW) on the frontend.
- **Branches and PRs.** Short-lived branches, a PR into `main` with at least one review (from the code owner or their backup), and CI green before merge. A merges anything that crosses areas.
- **Commits.** Small and coherent, with an imperative subject of 60 characters or fewer, a plain-prose body explaining *why*, no prefixes or emojis.
- **Definition of done.** Plan §13: tests, permission checks with a "denied" test, audit for sensitive actions, i18n, accessibility check, graceful degradation.
- **Rituals.**
  - Daily async standup (yesterday / today / blocked).
  - Sprint planning Monday of weeks 1, 3, 5, …
  - Demo and retrospective on the last Friday of each sprint, always against staging, not localhost.
- **Decisions.** Anything architectural gets a short ADR in `docs/adr/`. Product decisions go in §8 below with an owner and date.
- **AI agents (optional).** Owners may hand well-scoped tasks in their own area to coding agents, using the same contract-first briefs. The owner reviews the output like any other PR.

---

## 7. Risks for this team

| Risk | Mitigation |
|---|---|
| Holiday sprint (S3) slips | Planned at about 60%; closure and verification can spill into the first days of S4 without moving M3 |
| B overloaded (field app + staff UI + PWA + languages) | D takes e2e and accessibility automation; C builds the analytics dashboards' data layer so B only builds UI; cut "Could" items first |
| Single owner per area | Backup pairs (A↔C, B↔D) review weekly |
| DLT/SMS delays | Started in S1; email and in-app fallback; staff use test numbers |
| AI quality on real photos | Thresholds tuned from Phase 2 evaluation and then pilot corrections; review queue stays conservative at launch |
| Municipal data arrives late | Synthetic wards keep development unblocked; admin UI to load real data |

---

## 8. Decisions needed (owner · deadline)

| Decision | Owner | Needed by |
|---|---|---|
| Pilot city, wards and categories | Product owner | 14 Dec |
| SMS provider choice → start DLT | D + product owner | **4 Dec** |
| Closure approval policy per category | Product owner + A | 21 Dec |
| SLA targets and escalation rules | Product owner + A | 11 Jan |
| Hosted LLM allowed (assistant, low-confidence fallback)? | Product owner | 25 Jan |
| Public map location precision | Product owner + B | 25 Jan |
| Guest reporting allowed? | Product owner | 1 Feb |
| Regional language + speech provider | Product owner + C | 1 Feb |
| Media retention periods | Product owner + A | 8 Feb |
