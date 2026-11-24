# CivicPulse metrics (AN-004)

One definition per metric, so the dashboard, exports and reports all agree.
SQL is written against the current schema (`apps/api/app/domains/*/models.py`).
Where a timestamp the metric needs does not exist yet, the entry says
**pending Phase 3/4 schema** rather than inventing a column.

## Common rules

- **Tenant scope.** Queries run as `civicpulse_app`, so RLS already limits
  rows to the current tenant. Platform-wide figures need `system_session()`.
- **Day buckets** use Asia/Kolkata:
  `(created_at AT TIME ZONE 'Asia/Kolkata')::date`. A report filed at
  2026-11-23 20:00 UTC counts on 2026-11-24 (01:30 IST).
- **Period filter** is half-open on IST calendar days: `:from` and `:to` are
  IST midnights converted to timestamptz
  (`'2026-11-01'::timestamp AT TIME ZONE 'Asia/Kolkata'`).
- **Withdrawn reports** (`reports.status = 'withdrawn'`) are excluded from all
  counts unless a metric says otherwise.
- **Merged issues** (`civic_issues.merged_into_id IS NOT NULL`) are excluded
  from issue counts and durations; their reports count against the surviving
  issue through `reports.issue_id`.
- **Rejected issues** (`status = 'rejected'`) count as issues created but are
  excluded from resolution time, SLA compliance and reopen rate.
- Timestamps used: `reports.created_at`, `civic_issues.created_at`
  (both from `TimestampMixin`), `issue_events.created_at` with
  `type = 'status_changed'` plus `from_status`/`to_status`, and
  `match_decisions.created_at` / `decided_at`.

## Reports

Count of reports filed in the period, excluding withdrawn.

```sql
SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date AS day, count(*) AS reports
FROM reports
WHERE status <> 'withdrawn'
  AND created_at >= :from AND created_at < :to
GROUP BY 1 ORDER BY 1;
```

Example: 12 reports filed on 24 Nov IST, 1 later withdrawn: 11.

## Issues

Count of civic issues created in the period, excluding issues merged into
another. Rejected issues are included (they were real intake).

```sql
SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date AS day, count(*) AS issues
FROM civic_issues
WHERE merged_into_id IS NULL
  AND created_at >= :from AND created_at < :to
GROUP BY 1 ORDER BY 1;
```

Example: 8 issues created, 1 merged into another: 7.

## Reports per issue

Non-withdrawn reports attached to surviving issues created in the period,
divided by the number of those issues. Reports still `pending` or `review`
(no `issue_id`) are not counted. Uses report rows rather than the
denormalised `civic_issues.report_count`, so withdrawn reports are excluded
consistently.

```sql
SELECT count(r.id)::numeric / NULLIF(count(DISTINCT i.id), 0) AS reports_per_issue
FROM civic_issues i
JOIN reports r ON r.issue_id = i.id AND r.status <> 'withdrawn'
WHERE i.merged_into_id IS NULL
  AND i.created_at >= :from AND i.created_at < :to;
```

Example: 7 issues holding 11 reports: 1.57.

## Unique reporters

Distinct `reporter_id` across non-withdrawn reports in the period.

```sql
SELECT count(DISTINCT reporter_id) AS unique_reporters
FROM reports
WHERE status <> 'withdrawn' AND created_at >= :from AND created_at < :to;
```

Example: 11 reports from 9 citizens: 9.

## Acknowledgement time (mean, median)

Time from `civic_issues.created_at` to the first `status_changed` event out
of `reported` (to `under_review`, `verified` or `rejected`). Issues not yet
acknowledged are excluded from the averages and shown separately as a
backlog count. Merged issues excluded.

```sql
WITH ack AS (
  SELECT i.id, min(e.created_at) - i.created_at AS dur
  FROM civic_issues i
  JOIN issue_events e ON e.issue_id = i.id
   AND e.type = 'status_changed' AND e.from_status = 'reported'
  WHERE i.merged_into_id IS NULL
    AND i.created_at >= :from AND i.created_at < :to
  GROUP BY i.id, i.created_at
)
SELECT avg(dur) AS mean,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM dur)) AS median_seconds
FROM ack;
```

Example: three issues acknowledged in 2 h, 4 h and 12 h: mean 6 h, median 4 h.

## Assignment time (mean, median)

Time from `civic_issues.created_at` to the first `status_changed` event with
`to_status = 'assigned'`. Same exclusions as acknowledgement. The status
event exists today; who it was assigned to (assignment records, department,
field worker) is **pending Phase 3/4 schema**.

Same query as acknowledgement, with the join condition
`e.to_status = 'assigned'` in place of `e.from_status = 'reported'`.

Example: assigned after 1 d and 3 d: mean 2 d, median 2 d.

## Resolution time (mean, median)

Time from `civic_issues.created_at` to the first `status_changed` event with
`to_status = 'resolved'`. Rejected and merged issues are excluded. If an
issue is reopened and resolved again, the **first** resolution is used (the
reopen shows up in the reopen rate instead). A dedicated `resolved_at`
column is **pending Phase 3/4 schema**; until then the event log is the
source.

Same query as acknowledgement, with `e.to_status = 'resolved'` and
`AND i.status <> 'rejected'`.

Example: resolved in 2 d, 5 d and 20 d: mean 9 d, median 5 d.

## SLA compliance

Share of resolved issues whose first resolution is on or before their SLA
due time. SLA targets per category/priority and a per-issue due time are
**pending Phase 3/4 schema**; no SLA table exists in the current models.
Definition once available:

```
SLA compliance = resolved issues with first resolved event <= due time
               / resolved issues            (rejected and merged excluded)
```

Open issues already past due are reported as a separate "open breaches"
count, not in the ratio. Example: 40 resolved, 34 on time: 85%.

## Duplicate rate

Share of decided, non-withdrawn reports that joined an existing issue rather
than starting one: `matching_status = 'linked'` over
`matching_status IN ('linked', 'new_issue')`. Pending and in-review reports
are excluded until decided.

```sql
SELECT count(*) FILTER (WHERE matching_status = 'linked')::numeric
     / NULLIF(count(*) FILTER (WHERE matching_status IN ('linked', 'new_issue')), 0)
       AS duplicate_rate
FROM reports
WHERE status <> 'withdrawn' AND created_at >= :from AND created_at < :to;
```

Example: 11 decided reports, 4 linked: 36%.

## Review rate

Share of non-withdrawn reports whose matching went to a human: at least one
`match_decisions` row with `decision IN ('sent_to_review',
'chosen_by_reviewer', 'not_chosen')`. Auto-linked reports and reports with no
candidate are not reviewed.

```sql
SELECT count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM match_decisions m
         WHERE m.report_id = r.id
           AND m.decision IN ('sent_to_review', 'chosen_by_reviewer', 'not_chosen')
       ))::numeric / NULLIF(count(*), 0) AS review_rate
FROM reports r
WHERE r.status <> 'withdrawn' AND r.created_at >= :from AND r.created_at < :to;
```

Example: 11 reports, 3 went to review: 27%.

## Reopen rate

Share of issues first resolved in the period that later have a
`status_changed` event with `to_status = 'reopened'`. Merged issues excluded.
Reopen windows and citizen-initiated reopening are Phase 4 rules; the status
already exists in the vocabulary.

```sql
WITH resolved AS (
  SELECT e.issue_id, min(e.created_at) AS at
  FROM issue_events e
  JOIN civic_issues i ON i.id = e.issue_id
  WHERE e.type = 'status_changed' AND e.to_status = 'resolved'
    AND i.merged_into_id IS NULL
  GROUP BY e.issue_id
  HAVING min(e.created_at) >= :from AND min(e.created_at) < :to
)
SELECT count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM issue_events e
         WHERE e.issue_id = r.issue_id AND e.type = 'status_changed'
           AND e.to_status = 'reopened' AND e.created_at > r.at
       ))::numeric / NULLIF(count(*), 0) AS reopen_rate
FROM resolved r;
```

Example: 20 issues resolved in November, 2 reopened: 10%.
