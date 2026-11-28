# CivicPulse API

FastAPI service for CivicPulse. Phase 0 provides tenancy (Postgres RLS), phone-OTP auth with rotating refresh tokens and staff TOTP, RBAC with jurisdiction scoping, an append-only audit trail, and admin endpoints. Phase 1 adds the reporting loop: categories, direct-to-storage photo uploads with verification and metadata-free variants, reverse geocoding, report submission, the staff issue queue and map, and the configurable status workflow. Phase 2 adds the AI layer: category suggestions, asynchronous duplicate matching with a review queue, merge and split, and explainable rule-based severity and priority, all of which keep working without the models. The interface is specified in [`docs/api/phase-0-contract.md`](../../docs/api/phase-0-contract.md), [`docs/api/phase-1-contract.md`](../../docs/api/phase-1-contract.md) and [`docs/api/phase-2-contract.md`](../../docs/api/phase-2-contract.md), and the design decisions are in [`docs/adr/`](../../docs/adr).

## Run everything with Docker

From the repo root:

```sh
docker compose -f infra/docker-compose.yml up -d --build --wait
docker compose -f infra/docker-compose.yml exec ai-worker python scripts/seed.py
```

| Service | Port | Notes |
|---|---|---|
| api | 8000 | <http://localhost:8000/docs> |
| db | 5432 | PostGIS 3.5 + pgvector + h3 (`infra/db/Dockerfile`) |
| redis | 6379 | Rate limits, Celery broker |
| minio | 9000 / 9001 | Private bucket `civicpulse-media`; CORS for `localhost:3000`/`3100` |
| minio-init | – | One-shot: creates the bucket and the `civicpulse-app` user (that bucket only) |
| mailpit | 8025 / 1025 | Collects the outbox's notification email; nothing leaves the machine. SMTP on 1025 |
| worker | – | Celery, queue `default`: media processing, housekeeping, priority recomputes and the matching watchdog. Never the `ai` queue |
| ai-worker | – | Celery, queue `ai` (its only consumer): embeddings, classification, face blurring and matching with the real CLIP and YuNet models on CPU. See [the AI worker](#the-ai-worker) |
| beat | – | Celery Beat: hourly housekeeping, the matching watchdog every minute, the nightly priority recompute, and a weekly matching quality check that logs a `matching_quality_alert` warning when a category's correction or false-merge rate exceeds `QUALITY_ALERT_RATIO` times its 4-week baseline (run exactly one) |
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

## Vision models

The AI layer (`app/ai/`) runs CLIP ViT-B/32 (`Xenova/clip-vit-base-patch32`, MIT) and YuNet face detection (MIT) on ONNX Runtime, CPU only, with no torch. Domain code reaches the models only through `app/ai/registry.py`, which picks them by `AI_PROVIDER`:

| `AI_PROVIDER` | Where | What runs |
|---|---|---|
| `fake` (default) | tests, the API container, the `worker` | `app/ai/fake.py`: deterministic embeddings from the pixels and a classifier steered by a `CP_TEST_LABEL` tag. Needs nothing extra. |
| `onnx` | the `ai-worker` | The real models from `AI_MODEL_DIR` (default `/models`). Needs `uv sync --extra ai` and the weights. |

### The AI worker

The `ai-worker` compose service is the only consumer of the Celery queue `ai`: `analyze_media` (embedding, pHash and face blurring of each photo), `classify` (category suggestions) and `match_report` (duplicate matching). Keeping it the only consumer means every embedding in the database comes from one model; never add `ai` to the regular worker's queues. Its image (`infra/ai-worker/Dockerfile`, ~1.4 GB) is the API code plus the `ai` extra and the weights, which are baked in at build time and verified against `models.lock.json` again at start-up. On start-up it records the models in `model_registry`, which is what `GET /admin/ai/models` shows and what decides the active model's auto-link visual floor (0.92 for CLIP).

It runs one task at a time (each process holds both CLIP towers, about 1 GB) and needs ~1.5 GB of RAM. Throughput and latency are in [`docs/eval/phase-2-baseline.md`](../../docs/eval/phase-2-baseline.md#latency-and-footprint) and [`docs/eval/phase-2-matching-load.md`](../../docs/eval/phase-2-matching-load.md).

When it is down, nothing breaks for the citizen: classification answers `failed` and the web app asks for a manual choice; photos wait at `processing` (with `AI_FACE_BLUR` on, only the face check publishes them); and the matching watchdog on the regular worker matches reports older than two minutes without the visual signal, never auto-linking (contract D.1). To try it: `docker compose -f infra/docker-compose.yml stop ai-worker`.

Running the `ai` queue with the fake models instead, for quick local work without the 600 MB of weights:

```sh
docker compose -f infra/docker-compose.yml -f infra/docker-compose.fake-ai.yml up -d --build --wait
```

Start from a fresh database (`down -v`) when switching between the two; embeddings from different models are never compared.

### Downloading the models

```sh
uv sync --extra ai
uv run python scripts/download_models.py --model-dir .models      # ~600 MB, hashes checked against models.lock.json
uv run python scripts/download_models.py --model-dir .models --verify-only
AI_MODEL_DIR=.models uv run pytest tests/ai --confcutdir=tests/ai  # model tests; no database needed
```

`models.lock.json` pins each model to a Hugging Face Hub commit and records its licence and the sha256 of every file. To change a model, edit its pin in `scripts/download_models.py` and run it with `--update-lock`; the image's weight layer is keyed on the lock, so the next build fetches the new files. Without weights the model tests skip; CI sets `AI_REQUIRE_MODELS=1` so that they fail instead. `--candidate clip-int8|clip-laion2b` installs an evaluated alternative into another `--model-dir`.

To move to another vision model in a running system, re-embed every photo with `scripts/reindex_embeddings.py --model-id <id>` (resumable, rate-limited, `--dry-run`); the steps are in [`docs/runbooks/switch-vision-model.md`](../../docs/runbooks/switch-vision-model.md).

### Evaluation scripts

`scripts/eval/` measures the models on a small openly licensed image set. `manifest.csv` lists every image with its source page, author, licence and sha256, and its calib/test split; the images themselves aren't committed and download into `.eval-cache/`. Results and how to read them: [`docs/eval/phase-2-baseline.md`](../../docs/eval/phase-2-baseline.md).

| Script | What it does |
|---|---|
| `fetch_commons.py download` | Downloads the manifest's images and checks their hashes. Commons throttles hard (one file every ~20 s), so the first fetch is slow. `search` and `finalize` rebuild the candidate list and the manifest. |
| `fetch_openverse.py` | Finds more openly licensed candidates on Flickr through Openverse, for thin classes |
| `review_sheet.py` | Contact sheets of the candidates, for looking at every image before it is kept |
| `eval_classification.py` | Zero-shot accuracy, per-class precision/recall/F1, confusion matrix, threshold sweep and temperature fit (`--json` for the raw results) |
| `eval_dedup.py` | Visual similarity of augmented same-photo pairs against different photos of one category: ROC/PR and false-merge rate per floor, and the pHash rule |
| `tune_prompts.py` | Greedy prompt search, cross-fitted within calib |
| `bench_latency.py` | Embedding, prompt, face and pHash timings on this machine |

```sh
uv run python scripts/eval/fetch_commons.py download
AI_MODEL_DIR=.models uv run python scripts/eval/eval_classification.py --json out/classification.json
AI_MODEL_DIR=.models uv run python scripts/eval/eval_dedup.py --json out/dedup.json
AI_MODEL_DIR=.models uv run python scripts/eval/bench_latency.py
```

Rerun the evaluation, and refit the temperature, whenever the prompts or the model change, and update the baseline document with the date and model id.

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

## Verifying the audit trail

Every audit event is in a per-tenant SHA-256 hash chain (plus one for platform
events), extended by a `BEFORE INSERT` trigger — nothing in the app writes
`chain_seq`, `prev_hash` or `hash`, and an INSERT that supplies them is refused.
That is why no call site changed and no future one can forget. Verify with:

```sh
uv run python -m scripts.verify_audit_chain --tenant demo-city
uv run python -m scripts.verify_audit_chain --all-tenants --mode independent
uv run python -m scripts.verify_audit_chain --platform --checkpoints --json
```

Exit `0` passed, `1` broken, `2` usage error or no database. `--mode
independent` recomputes every hash in Python and never calls `audit_hash_v1`, so
it still finds a break if the SQL function itself was rewritten; it is the CLI
default, while the nightly job uses the cheaper `db` mode. `--platform` needs the
RLS bypass and is CLI-only.

What to do when it fails is in
[`docs/runbooks/audit-chain-recovery.md`](../../docs/runbooks/audit-chain-recovery.md),
and why it is built this way is [ADR 0007](../../docs/adr/0007-audit-hash-chain.md).
`AUDIT_ANCHOR_KEY` (required in production) signs the hourly checkpoint and must
never be stored in the database.

The framing exists twice — `audit_framing_v1` in SQL and `app/domains/audit/chain.py`
in Python — and must agree byte for byte. `tests/fixtures/audit_chain_v1.json`
pins both. **If that fixture changes, read the diff line by line**: it is the tripwire
for a real change to the format, and regenerating it blindly defeats the point.

## Conventions worth knowing

- **One transaction per request.** `DbSession` commits before the response is sent and rolls back on error. Don't commit in services, except where an error response must persist a write; those spots are commented.
- **Tenant context.** `set_tenant()`, `acting_as()` and `rls_bypass(reason=...)` in `app/core/tenancy.py`. Never bypass without a reason a reviewer would accept.
- **Permissions.** Add them to `Permission` and `ROLE_PERMISSIONS` in `app/domains/rbac/permissions.py`, then guard routes with `Annotated[Principal, require(Permission.X)]`. Every permission check needs a "denied" test.
- **Audit.** Call `audit.record(...)` in the same transaction as the change, with before/after snapshots for sensitive actions. The trigger chains the row; do not pass chain columns.
- **Errors.** Raise `AppError` subclasses from `app/core/errors.py`. Never return ad-hoc error bodies.
- **Storage.** Use the `Storage` dependency (`app/core/storage.py`). Server-side calls go to `S3_ENDPOINT`; URLs for browsers are signed for `S3_PUBLIC_ENDPOINT`, because the signature covers the host.
- **Background jobs.** Tasks are thin sync wrappers around async functions run through `run_async()` (`app/worker.py`). Queue work from a request with `BackgroundTasks`, which run after the transaction has committed, and keep tasks idempotent (`acks_late` redelivers).
- **Scope.** Staff reads of issues and reports filter by `accessible_jurisdiction_ids`, and out-of-scope is `404`, never `403`.
- **Jobs from requests.** Queue Celery work through the `JobsDep` dependency (`app/jobs.py`), which sends tasks by name; tests replace it with `InlineJobs` (`tests/helpers.py`), which runs the work inline right after the request commits.
- **Vision models.** Domain code reaches them only through `app/ai/registry.py`. With `AI_PROVIDER=fake` (tests, the API container) `app/ai/fake.py` stands in: its embeddings come from the pixels, so tests use `make_scene(seed, variant=...)` for "same scene" and "different scene", and a `CP_TEST_LABEL` value in the image picks the classification.
- **Moving reports between issues.** Take `linking.lock_families(...)` and then `linking.lock_issues(...)` in that order, recount with `linking.refresh_counts`, and call `priority.recompute` on every issue touched.
