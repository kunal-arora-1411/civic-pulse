# Audit chain recovery (A6.3)

The audit log is append-only and hash-chained, one chain per tenant plus one for
platform events. Each row's hash covers the row before it, and every hour the
head of each chain is sealed into a checkpoint signed with a key held outside the
database. Verification can therefore find a row that was changed, a row that was
deleted from the middle, and a tail that was truncated.

**A broken chain is an incident, not an outage.** It is deliberately not part of
`/ready`: taking the API out of the load balancer because the audit trail was
tampered with would stop the city accepting reports, which is the worse outcome.
Do not page on "the API is down" for this; page on the finding.

## Symptom

Any of:

- `GET /api/v1/admin/audit-chain` returns `"healthy": false`
- an `audit.chain.broken` line in the logs, at `ERROR`
- a nightly verification run with `status: "failed"`
- the CLI exits `1`

`healthy` is false when the newest checkpoint's signature does not verify, the
last verification failed, or the head has fallen behind a checkpoint that was
signed. Each of those means rows moved or vanished after they were sealed.

## Triage (10 minutes)

```sh
cd apps/api
uv run python -m scripts.verify_audit_chain --tenant <slug> --mode independent --checkpoints
```

Exit `0` passed, `1` broken, `2` usage error or no database. `--all-tenants`
walks every chain and the platform chain; `--platform` walks only the
tenant-less chain, which needs the RLS bypass and so is CLI-only.

Read the reported `chain_seq` and `reason`:

| `reason` | What it means | First thing to check |
|---|---|---|
| `hash` | A row's contents were changed after it was written | Who had schema-owner or superuser access at that time (DBA, leaked migration credential, an operator who disabled the trigger) |
| `link` | Rows were inserted out of order, or a `hash`/`prev_hash` was rewritten | Same, plus any restore or manual `INSERT` |
| `gap` | A row was deleted | A restore from an older backup, or a `DELETE` run with the trigger disabled |
| `chain head` | The head row disagrees with the log | A rewritten `audit_chain_heads` row |
| `checkpoint signature` | The HMAC does not verify | Treat as key compromise until proven otherwise: wrong `AUDIT_ANCHOR_KEY`, a rotated key missing from `AUDIT_ANCHOR_PREVIOUS_KEYS`, or forgery |
| `checkpoint row` | A signed sequence is gone or changed | Truncation — the tail was removed below a sealed checkpoint |

Then cross-check the sequence against the application logs by `request_id`. The
CLI prints only `action`, `entity_type` and `occurred_at`; fetch the payload
yourself, deliberately, and remember it may hold personal data (PRD §12.2).

```sql
SELECT * FROM audit_events WHERE chain_seq BETWEEN 1185 AND 1189 ORDER BY chain_seq;
```

## Do

1. **Preserve the evidence first.** Copy the rows around the break to a file
   outside the database and record its hash:
   ```sh
   psql "$DATABASE_URL" -c "COPY (SELECT * FROM audit_events WHERE chain_seq \
     BETWEEN 1185 AND 1189) TO STDOUT WITH CSV HEADER" > audit-1185-1189.csv
   sha256sum audit-1185-1189.csv
   ```
2. Record the verification run id, the CLI output and the timestamps in the
   incident.
3. Report it to the municipal admin as a **data-integrity incident**, not a bug.
4. If the signature failed, rotate the anchor key (below) once you know which key
   signed the affected checkpoints.

## Never

- **Never `UPDATE` or `DELETE` the row to "fix" the chain.** The break is the
  finding. Editing the row destroys the evidence and creates a second break.
- **Never disable `audit_chain_assign` to restore service** without a written
  incident decision. A failed chain append fails the audited write, by design; a
  disabled trigger starts a permanent, detectable break at that sequence and
  turns an incident into an audit hole.
- **Never regenerate the golden fixture** (`tests/fixtures/audit_chain_v1.json`)
  to make a failing framing test pass. A change there means the framing changed,
  which means every existing chain needs a versioned migration.
- **Never `alembic downgrade` below `0017`** to "reset" a chain. It drops the
  chain and, once checkpoints exist, destroys evidence.

## Rotating the anchor key

The key signs checkpoints; it never enters the database.

1. Generate a new secret: `openssl rand -hex 32`.
2. Move the current secret into `AUDIT_ANCHOR_PREVIOUS_KEYS` as `{"k1": "<old>"}`,
   set `AUDIT_ANCHOR_KEY_ID=k2` and `AUDIT_ANCHOR_KEY=<new>`, and deploy.
3. Check the status endpoint: `signature_valid` must stay `true` for the older
   checkpoints, which are verified with the key named in their `key_id`.
4. Wait one hourly seal and confirm the new checkpoint carries `key_id: "k2"`,
   then drop `k1` from `AUDIT_ANCHOR_PREVIOUS_KEYS`.

A checkpoint whose `key_id` is no longer in settings cannot be verified, and will
report `signature_valid: false` for ever — so retire old keys only when you no
longer need to prove those seals.

## If the nightly job stops sealing

`audit-checkpoint` runs hourly from Celery Beat. If the newest checkpoint is more
than a few hours old while the head has moved:

- Did the range since the last checkpoint verify? A chain that fails to verify is
  **not sealed**, by design, so the evidence freezes at the last good state. Check
  the logs for `audit.chain.sealing_skipped`.
- Is `AUDIT_ANCHOR_KEY` set? Without it the job logs and skips rather than sealing
  unsigned.
- Otherwise run it by hand:
  ```sh
  docker compose -f infra/docker-compose.yml exec worker \
    celery -A app.worker call civicpulse.audit.checkpoint
  ```
