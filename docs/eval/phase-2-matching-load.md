# Phase 2: duplicate matching under a burst of reports

**Status: method and tests in place; the real-stack numbers are not recorded yet** (the run was blocked by the development machine's Docker engine, see `docs/STATUS.md`). Fill in the table below from the first green run of the `load` project.

## What is being shown

FR-036: when many people report the same problem at the same moment, exactly one issue comes out of it, with every report and every reporter counted once. Matching runs on the AI worker and decides each report inside a transaction holding an advisory lock per (tenant, category family), re-reading the candidates under the lock (contract D.1), so the order in which simultaneous reports are decided doesn't matter.

Two tests cover it:

| Test | Stack | Size | What it proves |
|---|---|---|---|
| `apps/api/tests/test_matching.py::test_simultaneous_identical_reports_make_exactly_one_issue` | Real Postgres, fake model, `process_report` called concurrently in one process | 10 (three times) and 50 | The lock and the re-check: one `new_issue`, the rest `auto_link`, counts and `report_linked` events exact |
| `e2e/tests/load.spec.ts` (Playwright project `load`) | The whole compose stack with the real AI worker (CLIP on CPU) | 50 (`E2E_LOAD_REPORTS`) | The same through the real pipeline: 50 citizens each upload the same photo, then all submit within a few hundred milliseconds, 0–1.6 m apart |

## Method (end to end)

1. 50 fresh citizens sign in and upload the photo `e2e/fixtures/pothole-villeray.jpg` (setup, not timed).
2. All 50 `POST /reports` are sent at once. Each report's latency runs from its `201` response to the first poll (every 250 ms) that shows a matching decision. It covers the queue wait on the AI worker (one task at a time), embedding the photo, the face check, and the matching transaction.
3. The test asserts one `new_issue`, 49 `linked`, one issue id, and `report_count` and `unique_reporter_count` of 50, then prints and attaches the timings (`matching-latency.json`).

Run it on a seeded stack (README, "Running the e2e suite"):

```sh
pnpm --filter @civicpulse/e2e exec playwright test --project=load --no-deps
```

## Results

| Date | Machine | Reports | All submitted | All decided | p50 | p90 | p95 | max | Outcome |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| — | — | 50 | — | — | — | — | — | — | not run yet |

## What to expect

The AI worker processes one task at a time, and each report brings an `analyze_media` (embedding about 40–55 ms on a desktop CPU, face check about 70 ms, pHash 3 ms; [baseline](phase-2-baseline.md#latency-and-footprint)) and a `match_report`. Latency therefore grows roughly linearly through a burst: the last report waits for everything queued before it. The fallback deadline is two minutes, so a burst would have to keep the worker busy for that long before any report was matched without the visual signal; even then nothing would be linked wrongly, only sent to review.
