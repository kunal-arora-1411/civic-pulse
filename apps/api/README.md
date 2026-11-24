# CivicPulse API

FastAPI service for CivicPulse. Phase 0 provides tenancy (Postgres RLS), phone-OTP auth with rotating refresh tokens and staff TOTP, RBAC with jurisdiction scoping, an append-only audit trail, and admin endpoints. Phase 1 adds the reporting loop: categories, direct-to-storage photo uploads with verification and metadata-free variants, reverse geocoding, report submission, the staff issue queue and map, and the configurable status workflow. Phase 2 adds the AI layer: category suggestions, asynchronous duplicate matching with a review queue, merge and split, and explainable rule-based severity and priority, all of which keep working without the models. The interface is specified in [`docs/api/phase-0-contract.md`](../../docs/api/phase-0-contract.md), [`docs/api/phase-1-contract.md`](../../docs/api/phase-1-contract.md) and [`docs/api/phase-2-contract.md`](../../docs/api/phase-2-contract.md), and the design decisions are in [`docs/adr/`](../../docs/adr).

## Run everything with Docker

From the repo root:

```sh
docker compose -f infra/docker-compose.yml up -d --build --wait
docker compose -f infra/docker-compose.yml exec api python scripts/seed.py
```

| Service | Port | Notes |
|---|---|---|
| api | 8000 | <http://localhost:8000/docs> |
| db | 5432 | PostGIS 3.5 + pgvector + h3 (`infra/db/Dockerfile`) |
| redis | 6379 | Rate limits, Celery broker |
| minio | 9000 / 9001 | Private bucket `civicpulse-media`; CORS for `localhost:3000`/`3100` |
| minio-init | – | One-shot: creates the bucket and the `civicpulse-app` user (that bucket only) |
| mailpit | 8025 | Not used until notifications |
| worker | – | Celery: queues `default` (media processing, housekeeping, watchdog) and, until the AI worker exists, `ai` (embeddings, classification, matching) with `AI_PROVIDER=fake` |
| beat | – | Celery Beat: hourly housekeeping, the matching watchdog every minute, the nightly priority recompute (run exactly one) |
| migrate | – | One-shot `alembic upgrade head`, run as the owner role |

Credentials are development defaults inlined in the compose file. Override them from your shell or with `--env-file .env`.

## Sign in

The seed creates `demo-city`, `other-city` and one user per role (see the Phase 0 contract), plus five categories, the default workflow and about 60 synthetic issues with processed placeholder photos (Phase 1 contract, section 8). Running it again changes nothing. With `DEV_FIXED_OTP=true` (the compose default), `000000` works. The real code is also written to the API log:

```sh
curl -s -X POST localhost:8000/api/v1/auth/otp/request \
  -H 'Content-Type: application/json' -H 'X-Tenant: demo-city' \
  -d '{"phone": "+919000000001"}'
# -> {"challenge_id": "...", "expires_in": 300, "resend_after": 30}

curl -s -c jar -X POST localhost:8000/api/v1/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"challenge_id": "<id>", "code": "000000"}'
# -> {"access_token": "...", "refresh_token": "...", "user": {...}}, plus the cp_refresh cookie

curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer <access_token>"
curl -s -b jar -c jar -X POST localhost:8000/api/v1/auth/refresh
```

Platform admins (`+919000000000`) sign in **without** `X-Tenant`.

## Develop on the host

Uses [uv](https://docs.astral.sh/uv/) (on Windows, `py -3 -m uv`). Python 3.12 is pinned in `.python-version`.

```sh
cd apps/api
uv sync
docker compose -f ../../infra/docker-compose.yml up -d --wait db redis
cp ../../.env.example ../../.env          # read automatically from apps/api
uv run alembic upgrade head               # as the owner role (MIGRATION_DATABASE_URL)
uv run python scripts/seed.py
uv run uvicorn app.main:app --reload
uv run celery -A app.worker:celery_app worker --loglevel=INFO   # optional
```

## Test

```sh
uv run pytest
```

The tests need the compose `db`, `redis` and `minio` running. Storage tests use the real MinIO, in a `civicpulse-test` bucket that is emptied at the start of each run (`TEST_S3_*` to override), because signatures, signed headers and CORS are exactly what a fake would hide. Media processing runs inline in tests and nothing reaches the Celery broker; the geocoder is `none`, and the Nominatim client is tested against an in-process transport. Each run drops and recreates a `civicpulse_test` database through the owner connection and migrates it to head. The app under test then connects as `civicpulse_app`, so RLS is exercised for real, never mocked. Redis DB 15 is flushed at the start. Override the connections with `MIGRATION_DATABASE_URL`, `DATABASE_URL` and `TEST_REDIS_URL`. To run two checkouts' suites against the same services at once, give each its own `TEST_DB_NAME`, `TEST_REDIS_URL` and `TEST_S3_BUCKET`.

Lint and types (CI runs the same):

```sh
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

## Migrations

```sh
uv run alembic revision -m "add reports"   # write it by hand; autogenerate is fine for plain tables
uv run alembic upgrade head
```

- New tenant-scoped tables need `ENABLE` and `FORCE ROW LEVEL SECURITY`, the standard `tenant_isolation` policy, and grants to `civicpulse_app`. Copy the pattern in `0001_initial_schema.py`.
- `tests/test_schema.py` fails if the models and migrations drift apart.

## OpenAPI

```sh
uv run python scripts/export_openapi.py          # regenerate openapi.json (commit it)
uv run python scripts/export_openapi.py --check  # what CI runs
```

## Conventions worth knowing

- **One transaction per request.** `DbSession` commits before the response is sent and rolls back on error. Don't commit in services, except where an error response must persist a write; those spots are commented.
- **Tenant context.** `set_tenant()`, `acting_as()` and `rls_bypass(reason=...)` in `app/core/tenancy.py`. Never bypass without a reason a reviewer would accept.
- **Permissions.** Add them to `Permission` and `ROLE_PERMISSIONS` in `app/domains/rbac/permissions.py`, then guard routes with `Annotated[Principal, require(Permission.X)]`. Every permission check needs a "denied" test.
- **Audit.** Call `audit.record(...)` in the same transaction as the change, with before/after snapshots for sensitive actions.
- **Errors.** Raise `AppError` subclasses from `app/core/errors.py`. Never return ad-hoc error bodies.
- **Storage.** Use the `Storage` dependency (`app/core/storage.py`). Server-side calls go to `S3_ENDPOINT`; URLs for browsers are signed for `S3_PUBLIC_ENDPOINT`, because the signature covers the host.
- **Background jobs.** Tasks are thin sync wrappers around async functions run through `run_async()` (`app/worker.py`). Queue work from a request with `BackgroundTasks`, which run after the transaction has committed, and keep tasks idempotent (`acks_late` redelivers).
- **Scope.** Staff reads of issues and reports filter by `accessible_jurisdiction_ids`, and out-of-scope is `404`, never `403`.
- **Jobs from requests.** Queue Celery work through the `JobsDep` dependency (`app/jobs.py`), which sends tasks by name; tests replace it with `InlineJobs` (`tests/helpers.py`), which runs the work inline right after the request commits.
- **Vision models.** Domain code reaches them only through `app/ai/registry.py`. With `AI_PROVIDER=fake` (tests, the API container) `app/ai/fake.py` stands in: its embeddings come from the pixels, so tests use `make_scene(seed, variant=...)` for "same scene" and "different scene", and a `CP_TEST_LABEL` value in the image picks the classification.
- **Moving reports between issues.** Take `linking.lock_families(...)` and then `linking.lock_issues(...)` in that order, recount with `linking.refresh_counts`, and call `priority.recompute` on every issue touched.
