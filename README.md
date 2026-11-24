# CivicPulse

CivicPulse lets citizens report civic problems (potholes, overflowing bins, dark streetlights, blocked drains) to their municipality with a photo and a location, and follow each one until it's fixed. Municipal staff triage the reports in a work queue and on a map. It's being built for Indian city pilots, phase by phase; Phases 0 and 1 (foundations and the core reporting loop) are done.

## Repository layout

| Path | What it is |
|---|---|
| `apps/api` | FastAPI service: tenancy with Postgres row-level security, OTP sign-in, RBAC, audit, reports, media, issues and workflow. Python 3.12, uv. See [`apps/api/README.md`](apps/api/README.md). |
| `apps/web` | Next.js 16 web app: the citizen report flow and the staff admin console, in English and Hindi. |
| `e2e` | Playwright end-to-end tests against the real stack. |
| `infra` | Docker Compose for local development (Postgres + PostGIS, Redis, MinIO, Mailpit, API, worker, beat). |
| `docs/api` | The API contracts the backend and frontend share. |
| `docs/adr` | Architecture decision records. |

## Prerequisites

- Docker with Compose v2
- Node.js 22+ and pnpm 10 (`corepack enable` picks up the pinned version)
- For API work outside Docker: Python 3.12 and [uv](https://docs.astral.sh/uv/) (`py -3 -m uv` on Windows)

## Quick start

```sh
# 1. Start the stack (API on :8000, with its database, storage and worker)
docker compose -f infra/docker-compose.yml up -d --build --wait

# 2. Load the synthetic demo data (safe to run again)
docker compose -f infra/docker-compose.yml exec -T api python scripts/seed.py

# 3. Run the web app
pnpm install
pnpm dev
```

| URL | |
|---|---|
| <http://localhost:3000> | Web app (citizen pages; staff go to `/admin`) |
| <http://localhost:8000/docs> | API reference (Swagger UI) |
| <http://localhost:9001> | MinIO console (`civicpulse` / `civicpulse-minio`) |
| <http://localhost:8025> | Mailpit |

Sign in with a seeded phone number. In development the code `000000` always works (and the real one is in the API log).

| Phone | Role |
|---|---|
| 9000000005 | Citizen |
| 9000000002 | Operator |
| 9000000003 | Supervisor (Roads) |
| 9000000001 | Municipal admin |

All seeded data is synthetic. The full list of accounts is in the [Phase 0 contract](docs/api/phase-0-contract.md#seed-data-development-only-synthetic).

## Tests

**API** (needs the compose `db`, `redis` and `minio` running):

```sh
cd apps/api
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

**Web** (unit and component tests with Vitest, against a mocked API):

```sh
pnpm --filter @civicpulse/web test
pnpm --filter @civicpulse/web typecheck
pnpm lint
```

### Running the e2e suite

The Playwright suite drives the web app against the real, seeded stack, so do steps 1 and 2 of the quick start first. Then:

```sh
pnpm --filter @civicpulse/e2e exec playwright install chromium   # once
pnpm --filter @civicpulse/e2e test
pnpm --filter @civicpulse/e2e report                             # open the last HTML report
```

It builds the web app and serves it with `next start` on :3000, or reuses a server already running there (for example `pnpm dev`). A setup step checks that the API is up and seeded and tells you what to run if it isn't. Tests create their own data and use fresh citizen numbers, so they can run repeatedly on the same database. The compose stack's OTP limits are set for this; if you run the API with production limits, sign-ins will start failing with `rate_limited` after a few runs.

CI runs all three suites on every pull request (`.github/workflows/ci.yml`).

## Documents

- [Product requirements](CivicPulse_Product_Requirements_Document_v1.0.md)
- [Implementation plan](IMPLEMENTATION_PLAN.md)
- API contracts: [Phase 0](docs/api/phase-0-contract.md) (tenancy, auth, administration), [Phase 1](docs/api/phase-1-contract.md) (reports, media, issues, workflow)
- ADRs: [stack and modular monolith](docs/adr/0001-stack-and-modular-monolith.md), [multi-tenancy with row-level security](docs/adr/0002-multi-tenancy-with-row-level-security.md), [authentication](docs/adr/0003-authentication.md)
