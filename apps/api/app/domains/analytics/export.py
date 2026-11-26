"""CSV export of the issues behind the dashboard (P5-05, AN-002).

The export uses the same `Scope` as every dashboard figure, so the file a
manager downloads and the numbers they saw agree, and the caller's
jurisdiction scope narrows it exactly as it narrows the charts.

**What is deliberately not in the file.** There is no reporter column: no id,
no phone number, no name, no free-text description and no coordinate. Those
are the fields that identify a citizen, and an export is the easiest way for
them to leave the building. Ward, category and counts are aggregates that
carry the analytical value. A permission check alone is not privacy
filtering; the column list is.

Every export is audited with the filters and the row count, so who pulled
which slice of the city's data is answerable later.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.analytics.service import IST, Scope
from app.domains.audit import service as audit
from app.domains.rbac.principal import Principal

# A period is already capped at a year by Scope, so this only bites on a
# pathologically dense city. It exists so one request cannot hold an
# unbounded result set in memory.
EXPORT_MAX_ROWS = 20_000

COLUMNS = (
    "reference",
    "created_at",
    "category",
    "ward",
    "status",
    "severity",
    "priority",
    "due_at",
    "resolved_at",
    "resolution_hours",
    "report_count",
    "unique_reporter_count",
    "support_count",
    "sla_breached",
)

# Spreadsheet programs treat a leading one of these as the start of a
# formula, so a category named `=HYPERLINK(...)` would become executable in
# the file it is exported into. Quoting the cell keeps it text.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r", "\n")

_ROWS = """
    SELECT i.reference,
           i.created_at,
           coalesce(c.name_i18n->>'en', c.code) AS category,
           j.name AS ward,
           i.status,
           i.severity,
           coalesce(i.priority_override_band, i.priority_band) AS priority,
           i.due_at,
           coalesce(r.first_resolved_at, i.resolved_at) AS resolved_at,
           i.report_count,
           i.unique_reporter_count,
           i.support_count,
           i.breached_at IS NOT NULL AS sla_breached
    FROM civic_issues i
    JOIN categories c ON c.id = i.category_id
    LEFT JOIN jurisdictions j ON j.id = i.ward_id
    -- The same definition of "resolved" the dashboards use (docs/metrics.md):
    -- the first timeline event that moved the issue to `resolved`, not whatever
    -- the column happens to hold. The export has to agree with the figures.
    LEFT JOIN LATERAL (
        SELECT min(e.created_at) AS first_resolved_at
        FROM issue_events e
        WHERE e.issue_id = i.id AND e.to_status = 'resolved'
    ) r ON TRUE
    WHERE {where}
    ORDER BY i.created_at DESC, i.id DESC
    LIMIT :limit
"""


@dataclass(frozen=True, slots=True)
class Export:
    content: str
    filename: str
    rows: int
    truncated: bool


def cell(value: Any) -> str:
    """One CSV cell: text, never a formula."""
    text_ = "" if value is None else str(value)
    return f"'{text_}" if text_.startswith(_FORMULA_LEAD) else text_


def _ist(value: datetime | None) -> str:
    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M") if value else ""


def _hours(created: datetime, resolved: datetime | None) -> str:
    if resolved is None:
        return ""
    return f"{(resolved - created).total_seconds() / 3600:.1f}"


def _filename(start: date, end: date) -> str:
    return f"civicpulse-issues-{start.isoformat()}-to-{end.isoformat()}.csv"


async def issue_export(db: AsyncSession, scope: Scope, principal: Principal) -> Export:
    statement = text(_ROWS.format(where=scope.issues()))
    rows = (await db.execute(statement, {**scope.params(), "limit": EXPORT_MAX_ROWS + 1})).all()
    truncated = len(rows) > EXPORT_MAX_ROWS
    rows = rows[:EXPORT_MAX_ROWS]

    buffer = io.StringIO()
    # Excel on Windows ignores a UTF-8 CSV without a BOM, and this is a
    # download, so the BOM is the pragmatic choice rather than a nitpick.
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(
            [
                cell(row.reference),
                _ist(row.created_at),
                cell(row.category),
                cell(row.ward),
                cell(row.status),
                cell(row.severity),
                cell(row.priority),
                _ist(row.due_at),
                _ist(row.resolved_at),
                _hours(row.created_at, row.resolved_at),
                cell(row.report_count),
                cell(row.unique_reporter_count),
                cell(row.support_count),
                "yes" if row.sla_breached else "no",
            ]
        )

    await audit.record(
        db,
        action="analytics.export",
        entity_type="analytics_export",
        actor=principal,
        after={
            "from": scope.start.isoformat(),
            "to": scope.end.isoformat(),
            "category_id": str(scope.category_id) if scope.category_id else None,
            "ward_id": str(scope.ward_id) if scope.ward_id else None,
            "status": list(scope.statuses),
            "rows": len(rows),
            "truncated": truncated,
            "columns": list(COLUMNS),
        },
    )

    return Export(
        content=buffer.getvalue(),
        filename=_filename(scope.start, scope.end),
        rows=len(rows),
        truncated=truncated,
    )
