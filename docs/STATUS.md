# Project status and TODO

**Last updated:** 26 November 2026 · Paused here; continue from the TODO below.

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
- [x] **CI cost:** the e2e job builds the images with BuildKit's layer cache in the GitHub Actions cache and runs the real AI worker on every PR; the duplicate `images` job is gone ([ADR 0005](adr/0005-ci-real-model-image-cache.md)). Not yet seen running on GitHub (D1.1).
- [ ] **End-to-end walkthrough** (the real `ai-worker` stack was up and being seeded when the work paused) with real photos on the stack running the real `ai-worker` (curl + browser).
- [ ] **Update the e2e suite** for Phase 2 behaviour (partly done: tests that care what a report matches now report from fresh spots in the empty West Delhi area, and staff accounts are made per run so tests don't wait on OTP cooldowns; still to check against the stack): wait for the matching outcome on the confirmation and report pages; the default queue sort is `-priority`; new Priority column; new nav entries (Review queue, Matching, Priority rules, AI models).
- [ ] **New e2e tests against the real model:** written (`e2e/tests/ai.spec.ts`, `ai-down.spec.ts`, real Commons photos in `e2e/fixtures/` with attribution; the model classifies both as potholes, cosine 0.81 between them, below the 0.92 floor), **not yet run against the stack** because the development Docker engine hung (see below).
  - AC-02: real pothole photo gets a suggestion (openly licensed fixture with attribution)
  - AC-03: AI worker stopped → the report is still accepted and goes to manual
  - AC-04: the same photo twice auto-links and the counts update
  - AC-05: a nearby different scene isn't auto-linked
  - AC-06: an ambiguous report creates a review task and the operator resolves it
  - AC-07/AC-08: merge/split through the UI
- [ ] **e2e green 3 times in a row** against the real stack.
- [ ] **Concurrency at scale:** the pytest burst now also runs at 50 and the e2e `load` project sends 50 real reports at once; neither has run yet (Docker), and the latency table in [`eval/phase-2-matching-load.md`](eval/phase-2-matching-load.md) is empty.
- [x] **Contract cleanup:** section K and the frontend's edits are folded into the main text of [`api/phase-2-contract.md`](api/phase-2-contract.md) (checked against `openapi.json`; the related-issue links are audit-only, not timeline events).
- [x] **Docs:** README and `apps/api/README.md` sections on the AI worker, the model download and the evaluation scripts; the compose file takes host ports and an image tag from the environment so a second stack can run beside the first.
- [ ] **Blocked on Docker (26 Nov):** after the C: drive filled up, Docker Desktop's engine and its WSL VM stopped answering (`docker ps` and `wsl -d docker-desktop` hang; the published ports time out). Restart Docker Desktop, then: run pytest (including the 50-report burst), bring up the stack, run the e2e suite 3× in a row, and fill in the load numbers.
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
