# Project status and TODO

**Last updated:** 24 November 2026 · Paused here; continue from the TODO below.

## Where we are

| Phase | Status |
|---|---|
| P0 Foundations | ✅ Done |
| P1 Core reporting loop | ✅ Done: e2e suite green against the real stack |
| P2 AI layer | 🟡 **Integration pass in progress.** All three branches (ML, backend, frontend) are merged on `main`. Wiring fixes are mostly committed; end-to-end proof and docs remain. |
| P3–P6 | ⬜ Not started. See [`TEAM_PLAN.md`](TEAM_PLAN.md) and [`team/`](team/README.md). |

### Phase 2: already on `main`
- **ML:**
  - CLIP ViT-B/32 on ONNX Runtime (`Xenova/clip-vit-base-patch32`, MIT), YuNet face blur (MIT), numpy pHash
  - `ai-worker` image (~645 MB compressed, no torch)
  - evaluation baseline in [`eval/phase-2-baseline.md`](eval/phase-2-baseline.md): 94.7% test accuracy on 187 openly licensed images
- **Backend:**
  - asynchronous duplicate matching with an advisory lock (10 concurrent identical reports → 1 issue, tested 15×)
  - review queue, merge/split/related
  - severity and priority rules with factor explanations, overrides
  - matching/priority config, AI models and quality endpoints
- **Frontend:**
  - AI category suggestion in the report flow
  - "Checking for similar reports…"
  - review queue with signal breakdown
  - priority/severity cards and overrides, merge/split dialogs, settings pages
- **Integration fixes committed so far:**
  - real pHash, face blur and prompts in the pipeline
  - pHash stored signed in Postgres and unsigned elsewhere
  - the tenant's classification threshold applied in the API
  - the auto-link visual floor tied to the active model (0.92 from the evaluation)
  - photos published only after face checks
  - the `ai` queue owned by the AI worker alone
  - model registration at start-up
  - the admin AI pages reading the API's shapes
  - the new issue's reference shown after resolving a review

---

## TODO: finish Phase 2 (milestone M1)

- [x] **Type checking:** pyright green with and without the `ai` extra; CI type-checks with the extra installed (`08b8330`).
- [ ] **CI cost:** decide how e2e runs in CI without rebuilding the ~1.4 GB AI worker every time (layer cache / compose profile / separate real-model job). The real model must still run somewhere in CI.
- [ ] **End-to-end walkthrough** (the real `ai-worker` stack was up and being seeded when the work paused) with real photos on the stack running the real `ai-worker` (curl + browser).
- [ ] **Update the e2e suite** for Phase 2 behaviour: wait for the matching outcome on the confirmation and report pages; the default queue sort is `-priority`; new Priority column; new nav entries (Review queue, Matching, Priority rules, AI models).
- [ ] **New e2e tests against the real model:**
  - AC-02: real pothole photo gets a suggestion (openly licensed fixture with attribution)
  - AC-03: AI worker stopped → the report is still accepted and goes to manual
  - AC-04: the same photo twice auto-links and the counts update
  - AC-05: a nearby different scene isn't auto-linked
  - AC-06: an ambiguous report creates a review task and the operator resolves it
  - AC-07/AC-08: merge/split through the UI
- [ ] **e2e green 3 times in a row** against the real stack.
- [ ] **Concurrency at scale:** 50 simultaneous near-identical reports → exactly one issue with correct counts; record the matching latency.
- [ ] **Contract cleanup:** fold section K and the frontend's edits into the main text of [`api/phase-2-contract.md`](api/phase-2-contract.md).
- [ ] **Docs:** README and `apps/api/README.md` sections on the AI worker, the model download and the evaluation scripts.
- [ ] **Housekeeping:** remove the leftover worktree `.claude/worktrees/agent-a444236bd94054a03` and its branch once the integration pass is merged (its compose stack was replaced by the one running from `infra/`); delete the folder `.claude/worktrees/agent-a14a93622fdf6aff0`, which was locked by a process when the worktree was unregistered.

## TODO: rest of Sprint 1 (30 Nov – 11 Dec)

| ID | Task | Owner | Blocked on |
|---|---|---|---|
| A1.3 | **Phase 3 contract** (teams, assignments, work orders, closure, verification) | Backend | — · due **4 Dec** |
| A1.4 | Phase 3 schema and migration | Backend | A1.3 |
| B1.2 | Switch to an orval-generated API client | Frontend | Phase 2 integration done |
| B1.3 | Field app wireframes and flows | Frontend | — |
| D1.1 | CI green on GitHub (first real run), branch protection, CODEOWNERS | Platform/QA | — (remote exists: `civic-pulse`) |
| D1.4 | Schemathesis contract tests in CI | Platform/QA | D1.1 |
| D1.5 | PR template and contribution guide | Platform/QA | — |
| D1.3 | Start SMS DLT registration | Platform/QA | **SMS provider decision** |

## Phase 6 hardening (branch `feature/p6-hardening`)

Built; see [`api/phase-6-contract.md`](api/phase-6-contract.md) and [ADR 0005](adr/0005-retention-and-anonymization.md).
- **PWA (P6-01):** manifest and icons, hand-written `public/sw.js` (offline shell, cached pages, Background Sync), offline banner (`experimental.useOffline`), reports sent offline queued in IndexedDB and sent with the same Idempotency-Key and body.
- **Voice (P6-02):** dictation into the description with the browser's speech recognition; editable transcript, no audio kept.
- **Accessibility (P6-04):** axe-core checks of key pages in the e2e suite (serious and critical violations fail).
- **Security (P6-07):** per-address limits on OTP verify, MFA verify, refresh and tenant lookup; CSP and security headers on the web app; optional ClamAV scan of uploads (fails closed); CI job with pip-audit, pnpm audit, Trivy (config and API image) and gitleaks.
- **Load (P6-08):** `infra/load/reads.js` (k6, p95 < 500 ms thresholds).
- **Observability (P6-10):** opt-in Sentry and OpenTelemetry (OTLP) for the API and worker, with PII scrubbing.
- **Backups (P6-11):** `infra/backup/` backup, restore and drill scripts; RPO/RTO in [`runbooks/backup-restore.md`](runbooks/backup-restore.md).
- **Retention (P6-12):** citizen self-service anonymization; original-photo purge after `MEDIA_ORIGINAL_RETENTION_DAYS` (off by default).

Still to do for P6:
- [ ] Run the API suite, the web unit tests and e2e on the merged branch (not run where it was built: see the branch report).
- [ ] Offline photo capture: photos taken offline need their blobs handed to the queue (the queue already uploads queued photos; the photo step doesn't pass them yet). `/report` also still needs a session, which can't be restored offline.
- [ ] Field-app offline queue with conflict handling (FR-069).
- [ ] Guest reporting (P6-05): waiting on the decision (1 Feb). Needs nullable phones or guest users, CAPTCHA and a per-tenant switch (new config key and migration).
- [ ] Abuse controls (P6-06), degradation drills (P6-09), AI-queue burst test (P6-08), web-side Sentry, production infrastructure (P6-10), external penetration test.
- [ ] Record the first restore drill and the measured RTO; agree retention periods and set `MEDIA_ORIGINAL_RETENTION_DAYS`.
- [ ] Bhashini or faster-whisper for languages the browsers' speech recognition doesn't cover.

## Decisions needed from the product owner

| Decision | Needed by |
|---|---|
| **SMS provider** (MSG91 / Gupshup / …) → starts DLT registration | **4 Dec 2026** |
| Pilot city, wards and categories | 14 Dec |
| Closure approval policy per category | 21 Dec |
| SLA targets and escalation | 11 Jan 2027 |
| Hosted LLM allowed (analytics assistant)? | 25 Jan |
| Public map location precision | 25 Jan |
| Guest reporting allowed? | 1 Feb |
| Regional language + speech provider | 1 Feb |
| Media retention periods | 8 Feb |

## Known gaps carried forward
- **Report rate limit is global:** the per-citizen submission limits are settings, not per-tenant configuration (tenant configs would need a new key, a migration and admin UI).
- **Evaluation data:** small (187 images), mostly Flickr via Openverse (Commons rate-limited downloads), with few Indian scenes for some classes. Duplicate pairs are synthetic augmentations. These are baseline numbers, not real-world performance.
- **SMS:** still sent inside the request; moves to an outbox in Phase 4 (A4.3).
- **Audit:** not hash-chained yet (A6.3).
- **Signed URLs:** they change on every request, so browsers can't cache photos.
