# CivicPulse — Implementation Plan

**Based on:** CivicPulse PRD v1.0 · **Prepared:** 24 November 2026 · **Status:** Draft for review

---

## 1. Planning assumptions

| Assumption | Value used in this plan | If different |
|---|---|---|
| Target | **City pilot**: one tenant, one municipality, real citizens and staff | A demo cuts to Phases 0–2 plus a slim Phase 3 (see §9). A product adds Phase 7. |
| Team | 1 backend engineer, 1 frontend engineer, 1 full-stack/ML engineer, part-time designer and QA | With 2 people, roughly double the durations. |
| Duration | ~22 weeks to pilot launch, in 2-week sprints | |
| Stack | As agreed: Next.js PWA, FastAPI, PostgreSQL + PostGIS + pgvector + h3, Redis + Celery, MinIO/S3, open_clip on ONNX, Leaflet | |
| Data | Synthetic or consented data until the pilot (PRD §18.1) | |
| AI hosting | Self-hosted CLIP on CPU. Hosted LLM only for low-confidence fallback and the analytics assistant, behind a provider interface | |

## 2. Phase overview

```
Week:  1  2 | 3  4  5 | 6  7  8  9 | 10 11 12 13 | 14 15 | 16 17 18 | 19 20 21 22
       P0   | P1      | P2         | P3          | P4    | P5       | P6
       Found| Core    | AI layer   | Operations  | SLA & | Analytics| Hardening
       ation| loop    |            | & field     | notify| & insight| & pilot
                      ▲ M1 Demo-able             ▲ M2 Ops-complete  ▲ M3 Pilot go-live
```

| Phase | Goal | Weeks | Milestone |
|---|---|---|---|
| P0 Foundations | Repo, infra, auth, tenancy, RBAC, audit, CI | 1–2 | — |
| P1 Core loop | Citizen submits report → issue → admin sees and updates it | 3–5 | — |
| P2 AI layer | Classification, embeddings, duplicate matching, review queue, merge/split, priority | 6–9 | **M1: demo-able** |
| P3 Operations | Assignment, field app, evidence, closure, verification, reopen | 10–13 | — |
| P4 SLA and notifications | SLA timers, escalation, SMS/push/email | 14–15 | **M2: ops-complete** |
| P5 Analytics | Dashboard, hotspots, exports, analytics assistant, public pages | 16–18 | — |
| P6 Hardening and pilot | Offline, languages, accessibility, security, load testing, launch | 19–22 | **M3: pilot go-live** |

---

## 3. Phase 0 — Foundations (weeks 1–2)

**Goal:** a working skeleton that every later feature plugs into, with security and tenancy built in from day one.

### Tasks
| ID | Task | Owner |
|---|---|---|
| P0-01 | Monorepo: pnpm + Turborepo (`apps/web`), uv workspace (`apps/api`, `workers/*`), shared lint/format (Biome, ruff, pyright) | FS |
| P0-02 | `infra/docker-compose.yml`: Postgres 16 (PostGIS, pgvector, h3-pg), Redis, MinIO, Mailpit, API, worker, web | FS |
| P0-03 | FastAPI skeleton: `/api/v1`, domain modules, settings, structured JSON logging, correlation IDs, health/readiness endpoints | BE |
| P0-04 | Standard error object, pagination/filter/sort conventions, idempotency-key middleware (PRD §11.1) | BE |
| P0-05 | Alembic setup and base schema: `tenants`, `users`, `roles`, `permissions`, `user_roles`, `departments`, `jurisdictions` (PostGIS polygons), `audit_events` | BE |
| P0-06 | Postgres row-level security on `tenant_id`, with the tenant set per request via `SET LOCAL`. Test that cross-tenant reads fail | BE |
| P0-07 | Auth: phone OTP (stub SMS provider in development), JWT access tokens plus rotating refresh tokens, session revocation, argon2, staff TOTP MFA | BE |
| P0-08 | RBAC: permission decorator/dependency, jurisdiction scoping helper | BE |
| P0-09 | Audit service: append-only `audit_events` (before/after JSON, actor, entity), DB trigger blocking UPDATE/DELETE | BE |
| P0-10 | Next.js skeleton: route groups `(citizen)`, `(admin)`, `(field)`, auth flow, layout shells, Tailwind + shadcn/ui, next-intl wiring (English plus one placeholder language) | FE |
| P0-11 | OpenAPI → TypeScript client generation (orval) in `packages/api-client`, run in CI | FS |
| P0-12 | CI (GitHub Actions): lint, type-check, pytest with testcontainers (real PostGIS), Vitest, build images | FS |
| P0-13 | Seed script: one demo tenant, wards (sample GeoJSON), departments, users per role | BE |
| P0-14 | Architecture decision records (ADRs) for the stack choices, tenancy model and auth | All |

### Exit criteria
- `docker compose up` starts the full stack; a seeded user of each role can log in.
- **AC-14** (tenant isolation) and **AC-13** (unauthorized access) pass as automated tests.
- CI is green and required on every pull request.

**PRD coverage:** FR-001 (OTP), FR-004, FR-005, FR-006, FR-082, FR-083 (infrastructure), §11.1, §12.1 baseline.

---

## 4. Phase 1 — Core reporting loop (weeks 3–5)

**Goal:** the end-to-end report → issue loop works with **no AI**: each report creates its own issue, and admins can see and update it.

### Schema
`categories` (tree, required fields, evidence types, dedup radius/window), `reports`, `media_assets`, `civic_issues` (geometry point, category, status, severity, priority, `report_count`, `unique_reporter_count`), `issue_updates`, `status_transitions` (configurable state machine), `issue_followers`.

### Tasks
| ID | Task | Owner |
|---|---|---|
| P1-01 | Category admin API and UI (FR-019, FR-079), seeded with the 5 launch categories | BE/FE |
| P1-02 | Media upload: pre-signed MinIO URL → client PUT → confirm. Content-type sniffing, size limits, checksum, EXIF read and strip on the public copy | BE |
| P1-03 | `POST /reports` with idempotency key: validate, check ward point-in-polygon, save in one transaction, return reference | BE |
| P1-04 | Out-of-jurisdiction handling: reject with a clear message (§16) | BE |
| P1-05 | Temporary rule: each report creates a new issue (later replaced by the matcher in P2). Keep `report_count` updated in the same transaction | BE |
| P1-06 | Workflow engine: transitions table (`from`, `to`, `allowed_roles`, `requires_reason`, `requires_evidence`); `PATCH /issues/{id}/status` checks it and writes `issue_updates` + audit (FR-052–FR-054) | BE |
| P1-07 | Citizen reporting flow (mobile-first, 4 steps): photo → location (GPS plus draggable pin, accuracy shown) → category and description → review and submit. Browser-side image compression, upload progress, retry | FE |
| P1-08 | Reverse geocoding behind a provider interface (Nominatim in development) (FR-011) | BE |
| P1-09 | Citizen "My reports" and issue status timeline (FR-016) | FE |
| P1-10 | Admin work queue: table with filters, sorting, pagination; issue detail page with reports, media, map and history (FR-055) | FE |
| P1-11 | Admin map: Leaflet + markercluster, synchronized with the list (FR-045, FR-046, FR-050) | FE |
| P1-12 | Search by ID, address, category, status and text using Postgres full-text search (FR-076) | BE |
| P1-13 | Profile and preferences (FR-003) | FE |

### Exit criteria
- **AC-01** passes in Playwright: citizen submits photo + location → gets a reference → sees it in history.
- An operator moves an issue through the states, and every transition is audited.
- Retrying a submission with the same idempotency key never creates two reports (§16).

**PRD coverage:** FR-003, FR-007–FR-012, FR-015, FR-016, FR-019, FR-032 (temporary), FR-045, FR-046, FR-050, FR-052–FR-055, FR-076, FR-079, FR-080.

---

## 5. Phase 2 — AI layer (weeks 6–9)

**Goal:** classification, duplicate detection and priority, all explainable and all with a manual fallback.

### Schema
`model_registry`, `predictions`, `embeddings` (vector + model version, HNSW index), `match_decisions` (report, candidate issue, signal scores JSON, score, decision, decided by), `review_tasks`, `ai_feedback`, `priority_config` (per tenant).

### Tasks
| ID | Task | Owner |
|---|---|---|
| P2-01 | `workers/ai` service: Celery queue `ai`, export open_clip (SigLIP/CLIP ViT-B) to ONNX, CPU inference, model registry entry | ML |
| P2-02 | Media preparation job: resize, perceptual hash, YuNet face blur on the public copy | ML |
| P2-03 | Embedding job: save the image vector with model version; re-index command for model changes | ML |
| P2-04 | Zero-shot classification: one text prompt set per category plus "not a civic issue" and "unknown"; top-3 results with confidence; thresholds per tenant (FR-020, FR-022) | ML |
| P2-05 | Low-confidence fallback behind an `LLMProvider` interface, off by default and switchable per tenant | ML |
| P2-06 | Citizen UI: show the AI-suggested category for the citizen to confirm or change. Store corrections as labels (FR-021) | FE |
| P2-07 | Asynchronous flow: the report is accepted immediately; the AI pipeline runs after; if AI fails, the report is marked `classification_pending` and routed to manual triage (AC-03) | BE |
| P2-08 | **Duplicate matcher:** PostGIS candidate search (radius/window per category, open or recently closed issues) → score (geo decay, visual cosine, category compatibility, time decay, perceptual-hash bonus) → decide (auto-link / review / new). Weights and thresholds per tenant (FR-024–FR-030) | BE/ML |
| P2-09 | Concurrency: advisory lock on the geohash cell while linking; re-check candidates inside the lock; transactional counts. Load test with parallel reports at one spot (FR-036) | BE |
| P2-10 | Review queue UI: report vs. top candidates side by side, signal breakdown ("18 m · same category · 0.91 visual · 2 days"), accept/reject (FR-031, FR-035, FR-037) | FE |
| P2-11 | Merge (choose the surviving issue; reports move over; the old issue becomes a tombstone that redirects) and split (choose reports → new or existing issue). Both audited, counts recalculated (FR-033, FR-034) | BE/FE |
| P2-12 | Related-issue links without merging (FR-060) | BE |
| P2-13 | Severity hint from category rules plus proximity to sensitive places (schools, hospitals) via PostGIS; operator override with reason (FR-038) | BE |
| P2-14 | Priority engine: rules from tenant JSON config; factors are severity, unique reporters, age, recurrence, affected area, SLA status; bands; stored factor breakdown; recalculated on events; override with reason (FR-039–FR-044) | BE |
| P2-15 | Evaluation harness: labelled dataset (target 300 images + 200 report pairs, synthetic and consented); script reports per-class precision/recall/F1, duplicate precision/recall, false-merge rate (PRD §3.2) | ML |

### Exit criteria
- **AC-02 to AC-08** pass as automated tests (AC-05 includes "close by but visually and categorically different" adversarial cases).
- Evaluation report produced and baseline numbers recorded; thresholds tuned on it.
- 50 simultaneous reports at the same spot never produce duplicate issues or wrong counts.

### 🏁 Milestone M1 — Demo-able (end of week 9)
A citizen reports → AI classifies → duplicates link automatically or go to review → the admin sees a prioritized, explained queue on a map.

**PRD coverage:** FR-020–FR-022, FR-024–FR-044, FR-060, §8.1–§8.4, §8.6.

---

## 6. Phase 3 — Operations and field (weeks 10–13)

**Goal:** the operational loop from assignment to verified closure.

### Tasks
| ID | Task | Owner |
|---|---|---|
| P3-01 | Department/team/service-area setup, working schedules, supported categories (FR-061) | BE/FE |
| P3-02 | Assignments: assign/reassign to a team or person, accept/decline with reason (FR-062, FR-063) | BE |
| P3-03 | Field interface (mobile): work queue, work order detail with map and directions link, accept / start / progress note / request closure (FR-064, FR-065) | FE |
| P3-04 | Before/after evidence capture with capture time and location (FR-066) | FE/BE |
| P3-05 | Internal notes kept separate from public updates; enforced at the API level by visibility (FR-067) | BE |
| P3-06 | Supervisor workload view: per-team load, overdue items, distribution (FR-068) | FE |
| P3-07 | Closure request with required evidence → `pending_verification`; supervisor approve/reject (FR-070, FR-071) | BE |
| P3-08 | Citizen/community verification: eligibility rules, the FR-073 default rule, one vote per person, trust checks and rate limits (FR-072–FR-075) | BE |
| P3-09 | Resolution window → `closed` after the configured period; negative feedback → review/reopen (FR-058, FR-074) | BE |
| P3-10 | Reject report with reason and guidance; withdraw report leaves a tombstone (FR-018, FR-059) | BE/FE |
| P3-11 | Add evidence or comment to an existing issue; follow issue; moderation queue (FR-017, FR-085, FR-086) | BE/FE |
| P3-12 | Bulk assign/status actions with confirmation and audit (FR-078) | FE/BE |
| P3-13 | Stale-update detection: `version` column with optimistic locking; 409 with a reconcile screen (§16) | BE/FE |

### Exit criteria
- **AC-10, AC-11, AC-12** pass end to end: assign → field accepts → evidence → closure → citizen disputes → reopen.
- A field user cannot see reporter contact details or anything outside their assigned work (§4.1).

**PRD coverage:** FR-017, FR-018, FR-058, FR-059, FR-061–FR-068, FR-070–FR-075, FR-078, FR-085, FR-086.

---

## 7. Phase 4 — SLA, escalation and notifications (weeks 14–15)

### Tasks
| ID | Task | Owner |
|---|---|---|
| P4-01 | SLA config per category, priority and jurisdiction: acknowledge/assign/resolve targets (FR-056) | BE |
| P4-02 | Celery Beat SLA scanner: time elapsed, "due soon", breached; escalation rules (notify supervisor, raise priority) (FR-057, FR-041, FR-081) | BE |
| P4-03 | Notification service: event → template → per-channel delivery with a provider interface; delivery log; de-duplication and rate limits (§15) | BE |
| P4-04 | Channels: in-app inbox, Web Push (VAPID), email (SES/Postmark), SMS (MSG91/Gupshup with **DLT templates** — start registration in week 1) | BE |
| P4-05 | Notification preferences UI; lock-screen-safe wording (§15.2) | FE |
| P4-06 | Outage behavior: queue and retry with backoff, dead-letter queue, in-app fallback (§16) | BE |
| P4-07 | SLA badges and overdue filters in the admin queue (§9.2) | FE |

### Exit criteria
- **AC-09** passes: an overdue critical issue shows the breach and escalates.
- Every event in the §15.1 table sends a notification on at least one channel.

### 🏁 Milestone M2 — Ops-complete (end of week 15)

---

## 8. Phase 5 — Analytics and insight (weeks 16–18)

### Tasks
| ID | Task | Owner |
|---|---|---|
| P5-01 | Metric definitions doc (AN-004), written first; every dashboard number uses these definitions | All |
| P5-02 | Analytics API: overview counts, status breakdown, response times (mean/median), SLA compliance, duplicate/review rates. Materialized views refreshed by Celery (§14.1) | BE |
| P5-03 | Hotspots: h3 cell aggregation, comparison between periods, recurring-location detection (FR-047–FR-049) | BE |
| P5-04 | Dashboard UI (ECharts) with date, ward, zone, category, priority, status and department filters (AN-001) | FE |
| P5-05 | CSV export with permission and privacy filtering; audited (AN-002) | BE |
| P5-06 | Scheduled summary emails (AN-003) | BE |
| P5-07 | Analytics assistant: LLM with tool use over ~10 read-only analytics functions, run with the user's data scope; every answer states the period and filters used (AI-001–AI-004) | ML/BE |
| P5-08 | Public issue page and public map with generalized locations (coarse h3 cells, no reporter data) (FR-051, FR-084, §12.2) | FE/BE |
| P5-09 | Saved filters (FR-077); service announcements (FR-087) | FE/BE |
| P5-10 | AI quality dashboard: correction rate, review rate, false-merge feedback over time (§8.6 drift) | ML/FE |

### Exit criteria
- Dashboard numbers match hand-run SQL on seeded data.
- Assistant refuses or scopes questions outside the user's permissions (tested), and never runs generated SQL.

**PRD coverage:** FR-047–FR-049, FR-051, FR-077, FR-084, FR-087, §14, AN-001–AN-004, AI-001–AI-005.

---

## 9. Phase 6 — Hardening and pilot launch (weeks 19–22)

### Tasks
| ID | Task | Owner |
|---|---|---|
| P6-01 | PWA: installable, Serwist service worker, offline report drafts (FR-014), field offline queue in Dexie with sync and conflict handling (FR-069) | FE |
| P6-02 | Voice input: Bhashini or faster-whisper, editable transcript (FR-013) | ML/FE |
| P6-03 | Languages: full Hindi plus the city's regional language; language picker available before login (§9.1) | FE |
| P6-04 | Accessibility: axe-core in CI, keyboard and screen-reader pass on key flows, WCAG 2.2 AA fixes | FE/QA |
| P6-05 | Guest reporting (if approved) with CAPTCHA and tighter rate limits (FR-002) | BE |
| P6-06 | Abuse controls: perceptual-hash repeat detection, EXIF-time mismatch flags, verification-burst detection, report flagging (§12.3) | BE/ML |
| P6-07 | Security: dependency and container scanning, security headers/CSP, upload malware scan (ClamAV), external penetration test, fix findings | BE |
| P6-08 | Load test (k6): p95 < 500 ms on common reads at the agreed load; AI queue keeps up with report bursts | BE |
| P6-09 | Graceful degradation drills: AI down, maps down, SMS down (AC-15) | QA |
| P6-10 | Production infrastructure: India-region VM(s), managed Postgres or tuned self-hosted, S3 bucket lifecycle rules, Caddy, secrets manager, Sentry, OpenTelemetry → Grafana/Prometheus/Loki, alerts | FS |
| P6-11 | Backups with a tested restore drill; RPO/RTO documented (§13) | FS |
| P6-12 | Data retention jobs and account anonymization (§12.2, §16) | BE |
| P6-13 | Load real ward boundaries, departments and staff; train staff; write citizen help pages | All |
| P6-14 | Pilot launch in 1–2 wards, then expand | All |

### Exit criteria
- All of **AC-01 to AC-15** pass in a staging environment that mirrors production.
- Penetration test has no open high or critical findings; restore drill succeeded.

### 🏁 Milestone M3 — Pilot go-live (end of week 22)

---

## 10. Faster tracks

**Hackathon or demo (~6–8 weeks, 2–3 people):** P0 (without MFA or row-level security, single tenant) → P1 → P2 (P2-01–P2-11 and P2-14) → a slim P3 (assign + status + citizen confirm) → hotspot heatmap only. Seed realistic synthetic data. Skip SMS (use email or in-app), offline mode, voice and the assistant.

**After the pilot (Phase 7, product):** multi-tenant onboarding UI, workflow editor UI, staff single sign-on (Keycloak/SAML), trained classifier from collected corrections, pothole detector (RT-DETR), text-similarity signal, municipal system integrations, Kubernetes, more cities.

---

## 11. Decisions needed and when (PRD §18.3)

| Decision | Blocks | Needed by |
|---|---|---|
| Launch city, wards and categories | P0-13 seed, P6-13 | Week 2 (sample data until then) |
| Citizen and staff authentication methods | P0-07 | Week 1 |
| SMS provider and **DLT registration** | P4-04 | **Start week 1** (takes weeks) |
| Hosted LLM allowed? Data residency rules | P2-05, P5-07 | Week 6 |
| Model licences acceptable | P2-01 | Week 6 |
| Closure approval policy per category | P3-07 | Week 10 |
| SLA targets and escalation rules | P4-01 | Week 14 |
| Public map location precision | P5-08 | Week 16 |
| Guest reporting allowed? | P6-05 | Week 18 |
| Languages and speech provider | P6-02, P6-03 | Week 18 |
| Media retention periods | P6-12 | Week 19 |
| Municipal system integrations | Phase 7 | After pilot |

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Zero-shot classification too weak on real Indian street photos | Many manual corrections | Corrections feed a trained classifier (linear probe in days); LLM fallback for low confidence; manual flow always works |
| False merges of nearby distinct problems | Lost reports, lost trust | Conservative auto-link threshold at launch (review-heavy); split is always available; adversarial test cases in CI |
| Too little labelled data for evaluation | Can't report §3.2 metrics | Build the labelled set in P2 with synthetic and consented images; label pilot data as it arrives |
| DLT/SMS approval delays | No OTP at launch | Start in week 1; email/WhatsApp OTP fallback; test numbers in staging |
| Scope creep (87 FRs) | Pilot slips | "Should" and "Could" items are the first to cut; each phase has a fixed exit test |
| Low adoption by field staff | Issues stall at "assigned" | Involve field staff in P3 design; very simple field interface; offline support |
| Report spam or manipulation | Distorted priority | Unique-reporter counting, rate limits, perceptual hash, verification rules (P2, P6) |
| Municipal data (wards, teams) arrives late | Launch blocked | OSM admin boundaries as a placeholder; admin UI to load data |

---

## 13. Definition of done (every task)

- Code reviewed; CI green (lint, types, tests).
- API changes reflected in OpenAPI; TypeScript client regenerated; Schemathesis contract tests pass.
- Permission checks have tests, including at least one "denied" test.
- Sensitive actions write audit events.
- User-facing text goes through i18n (no hard-coded strings).
- Key screens checked with axe and keyboard.
- Feature works when its external dependency (AI, maps, notifications) is down, or degrades with a clear message.
