# ruff: noqa: S608  (SQL is assembled from fixed fragments; every value is a bound parameter)
"""Read-only analytics, computed from the definitions in docs/metrics.md.

Queries run in the caller's tenant session, so row-level security limits
every figure to the tenant. Each metric is one SQL template with a `{b}`
placeholder for its bucket expression: a constant for the period total, an
IST day or week for series. That keeps one definition per metric however
it is sliced.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.domains.analytics.schemas import (
    Activity,
    ActivityCell,
    Bin,
    ByCategory,
    ByStatus,
    ByWard,
    CategoryRow,
    Filters,
    Hotspot,
    Hotspots,
    Interval,
    Kpi,
    MatchingQuality,
    Overview,
    Period,
    Point,
    ResolutionTimes,
    StatusCount,
    Trend,
    TrendPoint,
    WardRef,
    WardRow,
)
from app.domains.categories.schemas import CategoryRef
from app.domains.workflow.statuses import IssueStatus

IST = ZoneInfo("Asia/Kolkata")
MAX_DAYS = 366
DEFAULT_DAYS = 30
OPEN_EXCLUDED = ("resolved", "closed", "rejected")
# Resolution-time histogram edges, in hours: a day, two, three, a week,
# two weeks, a month, then everything longer.
BIN_EDGES: tuple[float, ...] = (0, 24, 48, 72, 168, 336, 720)

Bucket = Literal["day", "week"] | None


def today_ist() -> date:
    return datetime.now(IST).date()


@dataclass(frozen=True, slots=True)
class Scope:
    """The filters shared by every endpoint. `end` is inclusive."""

    start: date
    end: date
    category_id: uuid.UUID | None = None
    ward_id: uuid.UUID | None = None
    statuses: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        start: date | None,
        end: date | None,
        category_id: uuid.UUID | None,
        ward_id: uuid.UUID | None,
        statuses: Sequence[IssueStatus] | None,
    ) -> Scope:
        end = end or today_ist()
        start = start or end - timedelta(days=DEFAULT_DAYS - 1)
        if start > end:
            raise ValidationFailed("`from` must not be after `to`.")
        if (end - start).days + 1 > MAX_DAYS:
            raise ValidationFailed(f"The period may span at most {MAX_DAYS} days.")
        return cls(
            start=start,
            end=end,
            category_id=category_id,
            ward_id=ward_id,
            statuses=tuple(s.value for s in statuses or ()),
        )

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> Scope:
        return replace(
            self,
            start=self.start - timedelta(days=self.days),
            end=self.start - timedelta(days=1),
        )

    def params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "t0": datetime.combine(self.start, time(), tzinfo=IST),
            "t1": datetime.combine(self.end + timedelta(days=1), time(), tzinfo=IST),
        }
        if self.category_id:
            params["cat"] = self.category_id
        if self.ward_id:
            params["ward"] = self.ward_id
        if self.statuses:
            params["statuses"] = list(self.statuses)
        return params

    def issues(self, alias: str = "i", *, timed: bool = True) -> str:
        """Surviving issues created in the period, with the filters."""
        parts = [f"{alias}.merged_into_id IS NULL"]
        if timed:
            parts.append(f"{alias}.created_at >= :t0 AND {alias}.created_at < :t1")
        if self.category_id:
            parts.append(f"{alias}.category_id = :cat")
        if self.ward_id:
            parts.append(f"{alias}.ward_id = :ward")
        if self.statuses:
            parts.append(f"{alias}.status = ANY(:statuses)")
        return " AND ".join(parts)

    def reports(self, alias: str = "r") -> str:
        """Non-withdrawn reports filed in the period, with the filters. A
        status filter keeps reports whose issue is in one of the states."""
        parts = [
            f"{alias}.status <> 'withdrawn'",
            f"{alias}.created_at >= :t0 AND {alias}.created_at < :t1",
        ]
        if self.category_id:
            parts.append(f"{alias}.category_id = :cat")
        if self.ward_id:
            parts.append(f"{alias}.ward_id = :ward")
        if self.statuses:
            parts.append(
                f"EXISTS (SELECT 1 FROM civic_issues fi WHERE fi.id = {alias}.issue_id"
                " AND fi.status = ANY(:statuses))"
            )
        return " AND ".join(parts)

    def filters(self) -> Filters:
        prev = self.previous()
        return Filters(
            period=Period(start=self.start, end=self.end),
            previous=Period(start=prev.start, end=prev.end),
            category_id=self.category_id,
            ward_id=self.ward_id,
            status=[IssueStatus(s) for s in self.statuses],
        )


def bucket_sql(expr: str, bucket: Bucket) -> str:
    local = f"({expr} AT TIME ZONE 'Asia/Kolkata')"
    if bucket == "day":
        return f"{local}::date"
    if bucket == "week":
        return f"date_trunc('week', {local})::date"
    return "NULL::date"


def buckets(scope: Scope, bucket: Literal["day", "week"]) -> list[date]:
    if bucket == "day":
        return [scope.start + timedelta(days=n) for n in range(scope.days)]
    first = scope.start - timedelta(days=scope.start.weekday())
    out: list[date] = []
    while first <= scope.end:
        out.append(first)
        first += timedelta(days=7)
    return out


# --- metric templates (docs/metrics.md) ---------------------------------------------------
#
# Status moves are read from any timeline event with a `to_status`: Phase 3
# moves carry their own event types (`closure_approved`, `reopened`, ...)
# rather than `status_changed`.

FIRST_MOVE = """
    SELECT i.id, i.created_at AS created, i.ward_id,
           min(e.created_at) AS at,
           extract(epoch FROM min(e.created_at) - i.created_at) / 3600.0 AS hours
    FROM civic_issues i
    JOIN issue_events e ON e.issue_id = i.id AND {move}
    WHERE {where}
    GROUP BY i.id, i.created_at, i.ward_id
"""
RESOLVED_MOVE = "e.to_status = 'resolved'"
ACK_MOVE = "e.from_status = 'reported' AND e.to_status IS NOT NULL AND e.to_status <> 'reported'"


def _resolution_cte(scope: Scope, *, timed: bool = True) -> str:
    where = f"{scope.issues(timed=timed)} AND i.status <> 'rejected'"
    return FIRST_MOVE.format(move=RESOLVED_MOVE, where=where)


Template = Callable[[Scope, Bucket], str]


def _reports(scope: Scope, b: Bucket) -> str:
    return (
        f"SELECT {bucket_sql('r.created_at', b)}, count(*)::float FROM reports r "
        f"WHERE {scope.reports()} GROUP BY 1"
    )


def _issues(scope: Scope, b: Bucket) -> str:
    return (
        f"SELECT {bucket_sql('i.created_at', b)}, count(*)::float FROM civic_issues i "
        f"WHERE {scope.issues()} GROUP BY 1"
    )


def _unique_reporters(scope: Scope, b: Bucket) -> str:
    return (
        f"SELECT {bucket_sql('r.created_at', b)}, count(DISTINCT r.reporter_id)::float "
        f"FROM reports r WHERE {scope.reports()} GROUP BY 1"
    )


def _median_hours(cte: str, b: Bucket) -> str:
    return (
        f"WITH d AS ({cte}) SELECT {bucket_sql('d.created', b)}, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY d.hours) FROM d GROUP BY 1"
    )


def _resolution_time(scope: Scope, b: Bucket) -> str:
    return _median_hours(_resolution_cte(scope), b)


def _acknowledgement_time(scope: Scope, b: Bucket) -> str:
    return _median_hours(FIRST_MOVE.format(move=ACK_MOVE, where=scope.issues()), b)


def _duplicate_rate(scope: Scope, b: Bucket) -> str:
    return (
        f"SELECT {bucket_sql('r.created_at', b)}, "
        "count(*) FILTER (WHERE r.matching_status = 'linked')::float"
        " / NULLIF(count(*) FILTER (WHERE r.matching_status IN ('linked', 'new_issue')), 0) "
        f"FROM reports r WHERE {scope.reports()} GROUP BY 1"
    )


REVIEWED = (
    "EXISTS (SELECT 1 FROM match_decisions m WHERE m.report_id = r.id"
    " AND m.decision IN ('sent_to_review', 'chosen_by_reviewer', 'not_chosen'))"
)
AUTO_LINKED = (
    "EXISTS (SELECT 1 FROM match_decisions m WHERE m.report_id = r.id"
    " AND m.decision = 'auto_linked')"
)


def _review_rate(scope: Scope, b: Bucket) -> str:
    return (
        f"SELECT {bucket_sql('r.created_at', b)}, "
        f"count(*) FILTER (WHERE {REVIEWED})::float / NULLIF(count(*), 0) "
        f"FROM reports r WHERE {scope.reports()} GROUP BY 1"
    )


def _resolved_first(scope: Scope) -> str:
    """Issues whose first resolution falls in the period."""
    return (
        f"SELECT * FROM ({_resolution_cte(scope, timed=False)}) x WHERE x.at >= :t0 AND x.at < :t1"
    )


def _reopen_rate(scope: Scope, b: Bucket) -> str:
    return (
        f"WITH d AS ({_resolved_first(scope)}) SELECT {bucket_sql('d.at', b)}, "
        "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM issue_events e WHERE e.issue_id = d.id"
        " AND e.to_status = 'reopened' AND e.created_at > d.at))::float"
        " / NULLIF(count(*), 0) FROM d GROUP BY 1"
    )


def _resolved(scope: Scope, b: Bucket) -> str:
    return (
        f"WITH d AS ({_resolved_first(scope)}) "
        f"SELECT {bucket_sql('d.at', b)}, count(*)::float FROM d GROUP BY 1"
    )


KPIS: tuple[tuple[str, Literal["count", "hours", "ratio"], Template], ...] = (
    ("reports", "count", _reports),
    ("issues", "count", _issues),
    ("unique_reporters", "count", _unique_reporters),
    ("resolution_time", "hours", _resolution_time),
    ("acknowledgement_time", "hours", _acknowledgement_time),
    ("duplicate_rate", "ratio", _duplicate_rate),
    ("review_rate", "ratio", _review_rate),
    ("reopen_rate", "ratio", _reopen_rate),
)


async def _series(db: AsyncSession, scope: Scope, sql: str) -> dict[date | None, float | None]:
    rows = (await db.execute(text(sql), scope.params())).all()
    return {row[0]: (None if row[1] is None else float(row[1])) for row in rows}


async def _total(db: AsyncSession, scope: Scope, template: Template, unit: str) -> float | None:
    values = await _series(db, scope, template(scope, None))
    value = values.get(None)
    return (value or 0.0) if unit == "count" else value


def spark_bucket(scope: Scope) -> Literal["day", "week"]:
    return "day" if scope.days <= 45 else "week"


async def overview(db: AsyncSession, scope: Scope) -> Overview:
    prev = scope.previous()
    bucket = spark_bucket(scope)
    keys = buckets(scope, bucket)
    kpis: list[Kpi] = []
    for metric, unit, template in KPIS:
        series = await _series(db, scope, template(scope, bucket))
        default = 0.0 if unit == "count" else None
        kpis.append(
            Kpi(
                metric=metric,
                unit=unit,
                value=await _total(db, scope, template, unit),
                previous=await _total(db, prev, template, unit),
                sparkline=[Point(bucket=k, value=series.get(k, default)) for k in keys],
            )
        )
    return Overview(filters=scope.filters(), kpis=kpis)


async def trend(db: AsyncSession, scope: Scope, interval: Interval) -> Trend:
    reports = await _series(db, scope, _reports(scope, interval))
    issues = await _series(db, scope, _issues(scope, interval))
    resolved = await _series(db, scope, _resolved(scope, interval))
    points = [
        TrendPoint(
            bucket=k,
            reports=int(reports.get(k) or 0),
            issues=int(issues.get(k) or 0),
            resolved=int(resolved.get(k) or 0),
        )
        for k in buckets(scope, interval)
    ]
    return Trend(
        metrics=["reports", "issues", "resolved"],
        interval=interval,
        filters=scope.filters(),
        points=points,
    )


def _status_order(items: list[StatusCount]) -> list[StatusCount]:
    order = {s.value: n for n, s in enumerate(IssueStatus)}
    return sorted(items, key=lambda item: order[item.status.value])


async def by_status(db: AsyncSession, scope: Scope) -> ByStatus:
    rows = (
        await db.execute(
            text(
                f"SELECT i.status, count(*) FROM civic_issues i WHERE {scope.issues()} GROUP BY 1"
            ),
            scope.params(),
        )
    ).all()
    items = _status_order([StatusCount(status=IssueStatus(s), count=n) for s, n in rows])
    return ByStatus(
        metric="issues_by_status",
        filters=scope.filters(),
        total=sum(i.count for i in items),
        items=items,
    )


async def by_category(db: AsyncSession, scope: Scope) -> ByCategory:
    rows = (
        await db.execute(
            text(
                "SELECT c.id, c.code, c.name_i18n, c.icon, i.status, count(*) "
                "FROM civic_issues i JOIN categories c ON c.id = i.category_id "
                f"WHERE {scope.issues()} GROUP BY 1, 2, 3, 4, 5"
            ),
            scope.params(),
        )
    ).all()
    grouped: dict[uuid.UUID, CategoryRow] = {}
    for cid, code, names, icon, status, n in rows:
        row = grouped.setdefault(
            cid,
            CategoryRow(
                category=CategoryRef(id=cid, code=code, name_i18n=names, icon=icon),
                total=0,
                statuses=[],
            ),
        )
        row.total += n
        row.statuses.append(StatusCount(status=IssueStatus(status), count=n))
    items = sorted(grouped.values(), key=lambda r: (-r.total, r.category.code))
    for item in items:
        item.statuses = _status_order(item.statuses)
    return ByCategory(metric="issues_by_category", filters=scope.filters(), items=items)


async def by_ward(db: AsyncSession, scope: Scope) -> ByWard:
    params = scope.params()
    closed = ", ".join(f"'{s}'" for s in OPEN_EXCLUDED)
    rows = (
        await db.execute(
            text(
                "SELECT j.id, j.code, j.name, count(*),"
                f" count(*) FILTER (WHERE i.status NOT IN ({closed})),"
                " count(*) FILTER (WHERE i.status IN ('resolved', 'closed')) "
                "FROM civic_issues i LEFT JOIN jurisdictions j ON j.id = i.ward_id "
                f"WHERE {scope.issues()} GROUP BY 1, 2, 3"
            ),
            params,
        )
    ).all()
    medians = dict(
        (
            await db.execute(
                text(
                    f"WITH d AS ({_resolution_cte(scope)}) SELECT d.ward_id,"
                    " percentile_cont(0.5) WITHIN GROUP (ORDER BY d.hours) FROM d GROUP BY 1"
                ),
                params,
            )
        )
        .tuples()
        .all()
    )
    items = [
        WardRow(
            ward=WardRef(id=wid, code=code, name=name) if wid else None,
            issues=n,
            open=open_,
            resolved=resolved,
            median_resolution_hours=(None if medians.get(wid) is None else float(medians[wid])),
        )
        for wid, code, name, n, open_, resolved in rows
    ]
    items.sort(key=lambda r: (-r.issues, r.ward.name if r.ward else "~"))
    return ByWard(
        metrics=["issues_by_ward", "resolution_time"], filters=scope.filters(), items=items
    )


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


async def resolution_times(db: AsyncSession, scope: Scope) -> ResolutionTimes:
    hours = sorted(
        float(h)
        for (h,) in (
            await db.execute(
                text(f"WITH d AS ({_resolution_cte(scope)}) SELECT d.hours FROM d"),
                scope.params(),
            )
        ).all()
    )
    bins: list[Bin] = []
    for n, lower in enumerate(BIN_EDGES):
        upper = BIN_EDGES[n + 1] if n + 1 < len(BIN_EDGES) else None
        count = sum(1 for h in hours if h >= lower and (upper is None or h < upper))
        bins.append(Bin(lower_hours=lower, upper_hours=upper, count=count))
    return ResolutionTimes(
        metric="resolution_time",
        filters=scope.filters(),
        count=len(hours),
        mean_hours=sum(hours) / len(hours) if hours else None,
        median_hours=_percentile(hours, 0.5),
        p90_hours=_percentile(hours, 0.9),
        bins=bins,
    )


async def matching_quality(db: AsyncSession, scope: Scope) -> MatchingQuality:
    params = scope.params()
    row = (
        await db.execute(
            text(
                "SELECT count(*),"
                " count(*) FILTER (WHERE r.matching_status IN ('linked', 'new_issue')),"
                " count(*) FILTER (WHERE r.matching_status = 'linked'),"
                f" count(*) FILTER (WHERE {AUTO_LINKED}),"
                f" count(*) FILTER (WHERE {REVIEWED}) "
                f"FROM reports r WHERE {scope.reports()}"
            ),
            params,
        )
    ).one()
    total, decided, linked, auto, reviewed = (int(v) for v in row)
    feedback = (
        await db.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE m.feedback = 'incorrect') "
                "FROM match_decisions m JOIN reports r ON r.id = m.report_id "
                f"WHERE m.feedback IS NOT NULL AND {scope.reports()}"
            ),
            params,
        )
    ).one()
    given, incorrect = int(feedback[0]), int(feedback[1])

    def ratio(a: int, b: int) -> float | None:
        return a / b if b else None

    return MatchingQuality(
        metrics=["auto_link_rate", "review_rate", "duplicate_rate", "correction_rate"],
        filters=scope.filters(),
        decided_reports=decided,
        auto_link_rate=ratio(auto, decided),
        review_rate=ratio(reviewed, total),
        duplicate_rate=ratio(linked, decided),
        correction_rate=ratio(incorrect, given),
        feedback_count=given,
    )


async def hotspots(db: AsyncSession, scope: Scope, resolution: int) -> Hotspots:
    closed = ", ".join(f"'{s}'" for s in OPEN_EXCLUDED)
    rows = (
        await db.execute(
            text(
                "WITH c AS ("
                " SELECT h3_lat_lng_to_cell(point(ST_X(i.location), ST_Y(i.location)), :res)"
                " AS cell, count(*) AS n,"
                f" count(*) FILTER (WHERE i.status NOT IN ({closed})) AS open"
                f" FROM civic_issues i WHERE {scope.issues()} GROUP BY 1"
                " ORDER BY 2 DESC LIMIT 400) "
                "SELECT c.cell::text, (h3_cell_to_lat_lng(c.cell))[0],"
                " (h3_cell_to_lat_lng(c.cell))[1], c.n, c.open FROM c ORDER BY c.n DESC"
            ),
            {**scope.params(), "res": resolution},
        )
    ).all()
    return Hotspots(
        metric="hotspots",
        filters=scope.filters(),
        resolution=resolution,
        items=[
            Hotspot(cell=cell, lng=float(lng), lat=float(lat), issues=n, open=open_)
            for cell, lng, lat, n, open_ in rows
        ],
    )


async def activity(db: AsyncSession, scope: Scope) -> Activity:
    local = "(r.created_at AT TIME ZONE 'Asia/Kolkata')"
    rows = (
        await db.execute(
            text(
                f"SELECT extract(isodow FROM {local})::int - 1, extract(hour FROM {local})::int,"
                f" count(*) FROM reports r WHERE {scope.reports()} GROUP BY 1, 2"
            ),
            scope.params(),
        )
    ).all()
    return Activity(
        metric="report_activity",
        filters=scope.filters(),
        items=[ActivityCell(weekday=d, hour=h, count=n) for d, h, n in rows],
    )
