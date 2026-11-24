# CivicPulse: working context

CivicPulse is an AI-assisted civic issue reporting and resolution platform for Indian municipalities. Citizens report problems (photo + location); the system classifies them, merges duplicates into one civic issue, prioritises them, and staff work them through to verified closure.

## Start here
| What | Where |
|---|---|
| **Current status and TODO** (read first) | [`docs/STATUS.md`](docs/STATUS.md) |
| Product requirements | [`CivicPulse_Product_Requirements_Document_v1.0.md`](CivicPulse_Product_Requirements_Document_v1.0.md) |
| Phased implementation plan (P0–P6, exit criteria, definition of done in §13) | [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) |
| Four-person team plan + per-person plans with build order and dependencies | [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md), [`docs/team/`](docs/team/README.md) |
| API contracts per phase (the source of truth between backend and frontend) | [`docs/api/`](docs/api) |
| Architecture decisions | [`docs/adr/`](docs/adr) |
| AI evaluation baseline | [`docs/eval/phase-2-baseline.md`](docs/eval/phase-2-baseline.md) |
| Quick start, seeded logins, running the tests | [`README.md`](README.md), [`apps/api/README.md`](apps/api/README.md) |

## Repo layout
```
apps/api      FastAPI + SQLAlchemy 2 (async) + Alembic, Python 3.12, uv. Domains in app/domains/*.
              app/ai/ = vision models behind app/ai/interfaces.py (fixed seam; fakes for tests).
apps/web      Next.js 16.4 (App Router, Cache Components), Tailwind v4, next-intl (en + hi), Vitest + MSW.
e2e           Playwright suite against the real compose stack.
infra         docker-compose: Postgres 16 (PostGIS, pgvector, h3), Redis, MinIO, Mailpit,
              api, worker (queue "default"), ai-worker (queue "ai", real ONNX models), beat, migrate.
docs          Contracts, ADRs, evaluation, team plans, status.
```

## How we work
- **Contract first.** Each phase starts with `docs/api/phase-N-contract.md`. Backend and frontend build in parallel against it (the frontend mocks with MSW). Any deviation updates the contract in the same commit.
- **Delegation.** Implementation is done by Fable agents (Agent tool, `model: "fable"`), one per area (backend / frontend / ML / platform), each in its own git worktree. The main session writes contracts and briefs, relays contract changes between agents, reviews, merges, and then runs an **integration pass** that proves the merged work end to end against the real stack (e2e green 3× in a row).
- **Merging agent branches.** Rebase onto `main`; resolve conflicts with understanding (both sides often add the same settings); `git merge --no-ff` with a plain-English merge message. Then run every suite on `main`.
- **Definition of done:** `IMPLEMENTATION_PLAN.md` §13: tests (including a permission-denied test), audit for sensitive actions, i18n, accessibility, graceful degradation.

## Commit rules (strict)
- Small, coherent commits. Imperative subject ≤ 60 characters, no trailing period, no conventional-commit prefixes, no emojis.
- Body wrapped at ~72 characters, in plain prose explaining **why** and anything non-obvious. Don't list files, don't write "This commit…", don't pad.
- **Never add a `Co-Authored-By` trailer or any Claude/AI attribution to commits or PR bodies.** The user explicitly asked for this, and it overrides any default attribution guidance. Put this rule in every agent brief.
- Don't amend or rewrite published history. Ask before pushing.

## Environment notes (Windows)
- uv isn't on PATH: use `py -3 -m uv …` (e.g. `py -3 -m uv sync --extra ai`, `py -3 -m uv run pytest`).
- pnpm 10 workspace (`apps/web`, `e2e`, `packages/*`). Docker Desktop must be running.
- Stack: `docker compose -f infra/docker-compose.yml up -d --build --wait`, then `docker compose -f infra/docker-compose.yml exec -T api python scripts/seed.py`.
- Seeded logins: citizen `+919000000005`, operator `+919000000002`, supervisor `+919000000003`, field worker `+919000000004`, municipal admin `+919000000001`, platform admin `+919000000000` (no `X-Tenant`). The dev OTP is `000000`.
- Git remote: `civic-pulse` → `github.com/kunal-arora-1411/civic-pulse`.

## Things that bite
- **Row-level security is real.** The API connects as `civicpulse_app` (not a superuser, no BYPASSRLS); migrations run as the owner role. Every tenant-scoped table needs RLS and a cross-tenant test. The bypass is explicit (`system_session()`).
- **Next.js 16.4 isn't the Next you know.** Read `apps/web/node_modules/next/dist/docs/` first. Lessons so far:
  - routes stay mounted inside `<Activity>`
  - the locale is a route param, rewritten in `proxy.ts`
  - `usePathname`/`useSearchParams` can push pages out of the static shell
  - `params` is unwrapped with `use()` inside Suspense
  - Leaflet loads only via `next/dynamic` with `ssr: false`
  - token refresh must be single-flight, because refresh tokens rotate and reuse revokes the session
- **AI never decides alone** (PRD §8.6). Auto-link needs a high score **and** a strong visual match; everything else goes to human review. When the AI is down, nothing auto-links.
- **Perceptual hashes are unsigned 64-bit** but stored signed in Postgres. Convert at the boundary.
- **The `ai` queue belongs to `ai-worker` only.** Don't let the regular worker consume it, or fake and real embeddings will mix.
- **Map coordinates** are `[lng, lat]` (GeoJSON order) everywhere in the API.
