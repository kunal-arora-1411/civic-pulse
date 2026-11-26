# Phase 2: duplicate matching under a burst of reports

**Result:** 50 simultaneous reports of one pothole became exactly one issue with 50 reports from 50 people. Every report was decided within 36 s of being sent, on a GitHub Actions runner with the real CLIP model. Recorded from the `load` project's output in CI; rerun it after changes to the AI worker or the matching transaction.

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
| 2026-11-26 | GitHub Actions `ubuntu-latest`, CI run 45847767612 | 50 | 1.6 s | 37.0 s | 34.0 s | 35.1 s | 35.3 s | 35.4 s | 1 issue, 50 reports, 50 reporters; 1 `new_issue`, 49 `linked` |

## Reading it

Latency here is mostly queueing: the AI worker takes one task at a time, and 50 photos plus 50 matches went through it in about 35 s, roughly 0.35 s of worker time per report on the runner's CPU. p50 and max are close together, which suggests that most decisions came at the end of the burst, after the photos queued ahead of them had been analysed (the setup uploads every photo before any report is sent). A citizen sees "Checking for similar reports" for that long. It stays well inside the two-minute fallback deadline, so every report kept the visual signal and none went to review. A burst several times larger, or a slower CPU, would get close to that deadline; the answer then is a second AI worker process (the advisory lock already makes concurrent matching safe), not a shorter deadline.

## What to expect

The AI worker processes one task at a time, and each report brings an `analyze_media` (embedding about 40–55 ms on a desktop CPU, face check about 70 ms, pHash 3 ms; [baseline](phase-2-baseline.md#latency-and-footprint)) and a `match_report`. Latency therefore grows roughly linearly through a burst: the last report waits for everything queued before it. The fallback deadline is two minutes, so a burst would have to keep the worker busy for that long before any report was matched without the visual signal; even then nothing would be linked wrongly, only sent to review.
