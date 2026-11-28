# Working notes for this repo

Facts that cost time to rediscover, not a replacement for `README.md`.

## Toolchain on this machine

- **`uv` is not installed.** The docs say `uv run …` everywhere; on this machine run
  `apps/api/.venv/bin/python -m pytest` (and `-m ruff`, `-m pyright`) instead.
- **`pyright` needs an explicit interpreter.** Without `uv` it resolves imports
  against the wrong Python and reports ~200 bogus `reportMissingImports` errors for
  `pytest`. Run it as:
  ```sh
  cd apps/api && .venv/bin/python -m pyright --pythonpath .venv/bin/python
  ```
  With the path it is clean.
- **Postgres runs in Docker** (`civicpulse-db-1`, `localhost:5432`, user
  `civicpulse`/`civicpulse`, app role `civicpulse_app`/`civicpulse_app`). The test
  suite creates and drops `civicpulse_test` itself; `civicpulse_test_migrations` is
  used by `tests/test_migrations.py`.
- Running a script by hand needs the full settings env or pydantic rejects the
  config — including `S3_ACCESS_KEY` / `S3_SECRET_KEY`, which are easy to miss. Copy
  the block from `tests/conftest.py`.

## The audit hash chain (A6.3)

- The framing exists **twice**: `audit_framing_v1` in SQL (migration `0017`) and
  `app/domains/audit/chain.py`. `tests/fixtures/audit_chain_v1.json` pins both.
  If that fixture changes, read the diff by hand — regenerating it blindly defeats
  the point.
- `scripts/bench_audit_append.py --baseline` briefly drops the chain columns'
  `NOT NULL`s and disables the append trigger. **Only run it against a scratch
  database.**
