# ADR 0001: Stack and a modular monolith

- Status: accepted
- Date: 2026-11-24

## Context

CivicPulse needs a citizen PWA, an operations console, geospatial queries, background jobs and, later, an AI pipeline. A small team builds it (PRD §18, plan §1), and it has to be pilot-ready in about 22 weeks.

## Decision

- **One backend service**, `apps/api`: FastAPI on Python 3.12, organised by domain (`app/domains/{tenants,auth,users,rbac,audit,org}`) with shared plumbing in `app/core`. Each domain owns its models, schemas, service and router. Domains call each other's service functions, never each other's tables.
- **PostgreSQL 16** with PostGIS (jurisdictions, locations), pgvector (image embeddings, Phase 2) and h3 (hotspot binning, Phase 5). Search, vectors and geometry all live in one transactional store, and Phase 0 doesn't need another database.
- **SQLAlchemy 2 (async) + asyncpg, Alembic** for migrations. Migrations are written by hand where clarity matters (RLS, triggers, grants), and a test checks that the models and migrations haven't drifted apart.
- **Redis + Celery** for background work and rate limiting. Workers run the same image and code as the API, so they share models and tenancy rules.
- **uv** for Python dependencies, with a committed `uv.lock`. **pnpm + Turborepo** for the web side.
- **OpenAPI is the contract.** Every route has an explicit `operation_id`, the schema is committed (`apps/api/openapi.json`), and CI fails if it goes stale. The frontend generates its client from it.

## Consequences

- One deployable, one database and one migration history keep Phase 0–3 simple. Cross-domain changes are ordinary refactors, not version negotiations.
- The boundaries are a convention, enforced in review rather than by the network. If a domain later needs independent scaling (the CLIP inference service is the likely first), it can be extracted along an existing domain seam.
- Celery is heavier than a minimal queue, but it's well understood and has scheduling, retries and routing, which Phase 4 (SLA timers, escalations) needs.
