# Person D: platform and QA engineer

**Mission:** make every change safe to ship. You own CI/CD, the environments, observability, every test that crosses layers (e2e, load, security, contract), the external providers (SMS, email, push), and getting the pilot live.

## You own
- `infra/` (compose, images, deployment), `.github/` (CI/CD)
- `e2e/` (the Playwright suite against the real stack)
- Staging and production environments, secrets, backups, runbooks
- Provider accounts and adapters: SMS (DLT), email, Web Push (VAPID), map tiles
- Release management and the go-live checklist

**Your backup is B.** You review one of B's PRs a week (accessibility and e2e), and B reviews one of yours.

## Before you start
- Read: `README.md`, `apps/api/README.md`, `infra/docker-compose.yml`, `.github/workflows/ci.yml`, `e2e/` (its helpers, the fixture conventions, why each test uses its own seeded account), and PRD §11.3, §12.1, §13, §16.
- **CI has never run on GitHub.** Every job was only run locally, so expect some first-run fixes.

---

## Order of implementation

| # | Task | Sprint | Depends on | Unblocks |
|---|---|---|---|---|
| 1 | **D1.3** SMS provider account + **start DLT registration** | S1 (day 1–5) | SMS-provider decision (4 Dec) | D4.1 → A4.3 |
| 2 | **D1.1** GitHub repo, CI green, branch protection, `CODEOWNERS` | S1 | Repo created | D2.1, everyone's PRs |
| 3 | **D1.5** PR template + contribution guide | S1 | D1.1 | — |
| 4 | **D1.2** e2e for Phase 2 behaviour + AC-04–AC-08 | S1 | A1.1 | M1 |
| 5 | **D1.4** Schemathesis contract tests in CI | S1 | D1.1 | Catches drift for B1.2 |
| 6 | **D2.1** Staging environment + automatic deploys | S2 | D1.1 | All sprint demos, D6.4 |
| 7 | **D2.2** Observability (Sentry, OpenTelemetry, Grafana, alerts) | S2 | D2.1 | D6.3 |
| 8 | **D2.3** e2e harness for field and multi-role flows | S2 | A1.3 | D3.1 |
| 9 | **D3.1** e2e AC-10–AC-12 | S3 | A3.2, B3.1–B3.3 | M2 |
| 10 | **D3.2** k6 load-test baseline | S3 | D2.1 | D6.2 |
| 11 | **D3.3** Offline/conflict test scaffolding | S3 | A3.4 | B6.2 |
| 12 | **D4.1** Provider adapters: SMS, email, Web Push | S4 | D1.3, A4.1 | A4.3 |
| 13 | **D4.2** Notification outage drills | S4 | A4.3, D4.1 | AC-15 |
| 14 | **D4.3** e2e AC-09 + notification checks | S4 | A4.2, A4.3 | M3 |
| 15 | **D5.1** Scheduled summary emails | S5 | C5.1, D4.1 | — |
| 16 | **D5.2** Performance tuning | S5 | C4.2 | D6.2 |
| 17 | **D5.3** axe accessibility checks in CI | S5 | — | B6.5 |
| 18 | **D6.4** Production infrastructure | S6 (start early) | D2.1 | D6.5, launch |
| 19 | **D6.1** External penetration test | S6 (book in S4) | Staging stable | A6.4 |
| 20 | **D6.2** Load test at pilot scale | S6 | D3.2, D5.2 | Launch |
| 21 | **D6.3** Degradation drills (AC-15) | S6 | D2.2, D4.2 | M5 |
| 22 | **D6.5** Backups + **tested restore** | S6 | D6.4 | Launch |
| 23 | **D6.6** Runbooks + on-call rota | S6 | D6.4 | Launch |
| 24 | **D7.1** Go-live checklist + production deploy | Launch | All of the above | 🚀 |

**Why this order:**
1. **DLT registration (D1.3) is first** because it has the longest external lead time in the whole plan. Every day's delay comes straight out of S4.
2. **CI on GitHub (D1.1) comes before everything else technical,** since nobody's PRs are trustworthy until it's green.
3. **Staging (D2.1) is in S2,** so every sprint demo from S2 onward runs on a real environment, not on localhost.
4. **Book the penetration test in S4 for S6.** External testers book up weeks ahead.
5. **Start production infrastructure (D6.4) at the beginning of S6,** not the end, because the restore drill (D6.5) needs it.

---

## Sprint 1 · 30 Nov – 11 Dec

### D1.3 SMS + DLT (start on day 1)
- Once the provider is chosen (MSG91, Gupshup or similar), register the principal entity, sender ID (header) and templates: OTP, report accepted, status changed, assigned, more information needed, closure requested, reopened.
- **Templates must match our wording exactly.** Agree the text with A and B first.
- Track approval status in the sprint board. Fallback: email and in-app.

### D1.1 CI on GitHub
- Create the repo (private) and push `main`.
- Fix the first-run failures in each job: API (ruff, pyright, pytest with Postgres, Redis and MinIO), web (biome, typecheck, test, build), e2e (compose stack + Playwright) and ML (models cached on `models.lock.json`).
- Branch protection: PR required, CI green, one code-owner review.
- Add the `CODEOWNERS` from `TEAM_PLAN.md` with real usernames.
- Target CI time: under 15 minutes for the main pipeline. Run e2e in parallel.

### D1.2 Phase 2 e2e
- Update the existing tests:
  - the confirmation screen now shows the matching step ("Checking for similar reports…"), so wait for the outcome
  - reports show "Checking" until they're placed
  - the default queue sort is `-priority`
  - the console smoke test needs the new nav entries (Review queue, Matching, Priority rules, AI models)
- New tests: AC-04 (linking updates both counts), AC-05 (a nearby but different report isn't auto-linked), AC-06 (review task with signals), AC-07/AC-08 (merge and split through the UI).

### D1.4 Schemathesis
Run property-based contract tests against `openapi.json` in CI, starting with the read endpoints, then the writes using seeded fixtures.

### D1.5 PR template
Checklist from plan §13 (tests, permission-denied test, audit, i18n, accessibility, degradation), screenshots for UI changes, a contract-change checkbox.

## Sprint 2 · 14 – 25 Dec
- **D2.1 Staging:**
  - an India-region VM, or managed Postgres plus a VM for the app containers, with a private S3 bucket
  - Caddy with TLS, secrets in a secrets manager (never in the repo), automatic deploy on merge to `main`
  - a seeded demo tenant, migrations run as the owner role, the app as `civicpulse_app`
- **D2.2 Observability:**
  - Sentry (API, worker, web)
  - OpenTelemetry traces → Grafana Tempo or similar
  - Prometheus metrics, including queue depth for `default` and `ai`, task failures and API p95
  - Loki for the JSON logs, with the existing request IDs
  - alerts for errors, queue backlog and failed health checks
- **D2.3 e2e harness for field work:** fixtures for a team, a supervisor and a field worker; a phone viewport project; helpers that move an issue to `assigned` through the API, so tests start from the state they need.

## Sprint 3 · 28 Dec – 8 Jan (~60% capacity)
- **D3.1 AC-10 to AC-12 e2e:** assign → field accepts → before/after evidence → closure → supervisor approves → the citizen says "still broken" → the issue reopens.
- **D3.2 k6 baseline:** the main read endpoints (queue, detail, GeoJSON, my reports) and report submission at a modest load on staging. Record p50/p95/p99 as the baseline.
- **D3.3 Offline/conflict scaffolding:** Playwright helpers that toggle offline mode and create conflicting edits from two sessions.

## Sprint 4 · 11 – 22 Jan
- **D4.1 Provider adapters** behind A's interfaces:
  - SMS using the DLT template IDs
  - email via SES or Postmark, with DKIM/SPF set up
  - Web Push with VAPID keys
  - delivery receipts/webhooks recorded in the delivery log
  - a sandbox mode for development and CI
- **D4.2 Outage drills:** with SMS or email down, notifications queue and retry with backoff, land in the dead-letter queue, and show in-app status (§16).
- **D4.3** AC-09 e2e (an overdue critical issue shows the breach and escalates), plus checks that every §15.1 event produces a notification.
- **Book the external penetration test** for S6.

## Sprint 5 · 25 Jan – 5 Feb
- **D5.1** Scheduled operational summary emails (AN-003), using C's analytics API and the email adapter.
- **D5.2 Performance:** `EXPLAIN ANALYZE` on the slow queries found by tracing; add or adjust indexes with A and C; check that the RLS bypass clause isn't spoiling query plans (flagged in Phase 0).
- **D5.3** axe-core in the e2e suite for the key pages, failing on serious or critical violations.

## Sprint 6 · 8 – 19 Feb
- **D6.4 (start on day 1) Production:** the same setup as staging, sized for the pilot, with separate credentials, S3 lifecycle rules and a WAF/rate limiting at the edge.
- **D6.1 Penetration test:** give the testers scope, accounts and environment; triage the findings into A's and B's queues.
- **D6.2 Load test at pilot scale:** p95 under 500 ms on common reads, and the AI queue keeping up with bursts of reports.
- **D6.3 Degradation drills (AC-15):** with the AI worker, map tiles, SMS or geocoding down, core reporting and issue management still work.
- **D6.5 Backups:** automated Postgres backups and object storage versioning. **Do a full restore into a fresh environment and time it**, then document the RPO and RTO.
- **D6.6 Runbooks:** deploy/rollback, restore, rotate secrets, model switch (with C), incident response; plus the on-call rota for the pilot.

## Launch week
- **D7.1 Go-live checklist:** DNS and TLS, secrets, backups verified, alerts routed, the SMS templates approved, a production smoke test, rollback rehearsed. Deploy, then watch.

---

## Recurring duties
- Keep CI under 15 minutes and fix flaky tests within one day: **quarantine, don't ignore.**
- Every sprint demo runs on staging.
- Review every PR touching `infra/`, `.github/` or `e2e/`.
- Track provider approvals (DLT) and vendor bookings (penetration test) on the board.
