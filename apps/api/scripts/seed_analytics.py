"""Analytics development seed: ~90 days of varied history for Demo City.

Called from scripts/seed.py after the Phase 1 and Phase 2 seeds, so the
analytics dashboard has something realistic to show. Everything is
SYNTHETIC. Compared to the Phase 1 issues these:

* span the last 90 days, busier on weekdays and at commute hours;
* lean towards some wards and categories, and cluster around a few
  street corners so hotspots stand out;
* move through the whole lifecycle (assigned, in progress, awaiting
  check, resolved, closed, reopened), using the Phase 3 event types, with
  resolution times that vary by category;
* carry duplicate reports, linked automatically or by a reviewer, with
  match decisions and some reviewer feedback, so the AI quality rates
  are not empty.

No photos: the dashboard doesn't need them, and processing hundreds of
images would make the seed slow. Addresses start with "Analytics Street"
so these rows are easy to tell apart from the Phase 1 issues.

Idempotent: every issue, report and decision has a deterministic id and an
issue that exists is skipped along with everything that belongs to it.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import system_session
from app.domains.issues.models import CivicIssue, EventType, IssueEvent, ReferenceKind, Visibility
from app.domains.issues.references import allocate
from app.domains.matching.models import Decision, Feedback, MatchDecision
from app.domains.reports.models import MatchingStatus, Report, ReportStatus
from app.domains.workflow.statuses import IssueStatus
from scripts import seed_phase1 as phase1

ISSUE_COUNT = 360
DAYS = 90
ADDRESS_PREFIX = "Analytics Street"

# Relative weights: ward 1 is the busiest, potholes the most common.
WARD_WEIGHTS = (0.38, 0.27, 0.21, 0.14)
CATEGORY_WEIGHTS = {
    "pothole": 0.32,
    "waste": 0.26,
    "waterlogging": 0.16,
    "streetlight": 0.15,
    "drainage": 0.11,
}
# Typical hours from report to resolution, per category (log-normal median).
RESOLUTION_MEDIAN_H = {
    "pothole": 96.0,
    "waste": 30.0,
    "waterlogging": 60.0,
    "streetlight": 70.0,
    "drainage": 140.0,
}
# Reports per hour of the IST day: peaks at the morning and evening commute.
HOUR_WEIGHTS = (
    1, 1, 1, 1, 1, 2, 4, 7, 10, 11, 9, 8,
    7, 7, 6, 6, 7, 9, 11, 10, 8, 5, 3, 2,
)  # fmt: skip
WEEKDAY_WEIGHTS = (1.2, 1.1, 1.0, 1.0, 1.05, 0.8, 0.65)  # Monday first
IST_OFFSET = timedelta(hours=5, minutes=30)

# The lifecycle, in order, with the event type each move is recorded as.
PATH: list[tuple[IssueStatus, EventType]] = [
    (IssueStatus.UNDER_REVIEW, EventType.STATUS_CHANGED),
    (IssueStatus.VERIFIED, EventType.STATUS_CHANGED),
    (IssueStatus.ASSIGNED, EventType.ASSIGNED),
    (IssueStatus.IN_PROGRESS, EventType.WORK_STARTED),
    (IssueStatus.PENDING_VERIFICATION, EventType.CLOSURE_REQUESTED),
    (IssueStatus.RESOLVED, EventType.CLOSURE_APPROVED),
    (IssueStatus.CLOSED, EventType.CLOSED),
]


@dataclass
class Planned:
    index: int
    category: str
    ward: int
    lng: float
    lat: float
    created_at: datetime
    # (to_status, event type, at), in order
    moves: list[tuple[IssueStatus, EventType, datetime]] = field(default_factory=list)
    resolved_at: datetime | None = None
    # (reporter index, hours after creation, decision, feedback)
    duplicates: list[tuple[int, float, Decision, Feedback | None]] = field(default_factory=list)
    reviewed_new: bool = False

    @property
    def status(self) -> IssueStatus:
        return self.moves[-1][0] if self.moves else IssueStatus.REPORTED


def _seed_id(kind: str, index: int) -> uuid.UUID:
    return phase1.seed_id(f"analytics/{kind}", index)


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _created_at(rng: random.Random, now: datetime) -> datetime:
    # More reports lately: weight days towards the recent end.
    while True:
        age = rng.triangular(0, DAYS, 0)
        day = (now + IST_OFFSET - timedelta(days=age)).date()
        if rng.random() < WEEKDAY_WEIGHTS[day.weekday()] / max(WEEKDAY_WEIGHTS):
            break
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
    local = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=UTC)
    at = local - IST_OFFSET
    return min(at, now - timedelta(minutes=30))


def _moves(
    rng: random.Random, category: str, created: datetime, now: datetime
) -> tuple[list[tuple[IssueStatus, EventType, datetime]], datetime | None]:
    """Walk the lifecycle until the next step would land in the future."""
    if rng.random() < 0.06:
        at = created + timedelta(hours=rng.uniform(1, 30))
        if at < now:
            return [(IssueStatus.REJECTED, EventType.STATUS_CHANGED, at)], None
        return [], None
    total = rng.lognormvariate(0, 0.7) * RESOLUTION_MEDIAN_H[category]
    # Share of the time to resolution each step takes.
    shares = (0.05, 0.1, 0.15, 0.35, 0.35)
    stops_early = rng.random() < 0.12  # some work simply hasn't moved on yet
    moves: list[tuple[IssueStatus, EventType, datetime]] = []
    resolved_at: datetime | None = None
    at = created
    for step, (status, event) in enumerate(PATH):
        if step < len(shares):
            at = at + timedelta(hours=total * shares[step])
        else:  # closing comes days after resolution
            at = at + timedelta(hours=rng.uniform(24, 120))
        if at >= now or (stops_early and step >= 3 and rng.random() < 0.5):
            break
        moves.append((status, event, at))
        if status is IssueStatus.RESOLVED:
            resolved_at = at
            if rng.random() < 0.07:  # the citizen says it isn't fixed
                reopened = at + timedelta(hours=rng.uniform(6, 72))
                if reopened < now:
                    moves.append((IssueStatus.REOPENED, EventType.REOPENED, reopened))
                break
    return moves, resolved_at


def plan(wards: dict[uuid.UUID, tuple[float, float, float, float]]) -> list[Planned]:
    boxes = list(wards.values())
    now = datetime.now(UTC)
    # Three street corners per ward where problems keep coming back.
    corners: list[list[tuple[float, float]]] = []
    for number, (min_lng, min_lat, max_lng, max_lat) in enumerate(boxes):
        rng = random.Random(f"analytics/corners/{number}")  # noqa: S311
        corners.append(
            [
                (
                    rng.uniform(min_lng + 0.006, max_lng - 0.006),
                    rng.uniform(min_lat + 0.006, max_lat - 0.006),
                )
                for _ in range(3)
            ]
        )
    planned: list[Planned] = []
    for index in range(ISSUE_COUNT):
        # Deterministic per index (synthetic data, not security).
        rng = random.Random(f"analytics/{index}")  # noqa: S311
        category = _pick(rng, CATEGORY_WEIGHTS)
        ward = rng.choices(range(len(boxes)), weights=WARD_WEIGHTS[: len(boxes)])[0]
        min_lng, min_lat, max_lng, max_lat = boxes[ward]
        if rng.random() < 0.55:
            c_lng, c_lat = rng.choice(corners[ward])
            lng = min(max(rng.gauss(c_lng, 0.0025), min_lng + 0.0005), max_lng - 0.0005)
            lat = min(max(rng.gauss(c_lat, 0.0025), min_lat + 0.0005), max_lat - 0.0005)
        else:
            lng = rng.uniform(min_lng + 0.001, max_lng - 0.001)
            lat = rng.uniform(min_lat + 0.001, max_lat - 0.001)
        created = _created_at(rng, now)
        moves, resolved_at = _moves(rng, category, created, now)
        issue = Planned(
            index=index,
            category=category,
            ward=ward,
            lng=round(lng, 6),
            lat=round(lat, 6),
            created_at=created,
            moves=moves,
            resolved_at=resolved_at,
        )
        if rng.random() < 0.3:
            for _ in range(rng.choice((1, 1, 1, 2, 2, 3))):
                hours = rng.uniform(0.5, 48)
                if created + timedelta(hours=hours) >= now:
                    continue
                auto = rng.random() < 0.72
                decision = Decision.AUTO_LINKED if auto else Decision.CHOSEN_BY_REVIEWER
                feedback = None
                if auto and rng.random() < 0.45:
                    feedback = Feedback.INCORRECT if rng.random() < 0.1 else Feedback.CORRECT
                issue.duplicates.append((rng.randrange(3), hours, decision, feedback))
        # Some new issues were first suspected to be duplicates of an older one.
        issue.reviewed_new = index > 10 and rng.random() < 0.08
        planned.append(issue)
    return planned


async def _add_report(
    db: AsyncSession,
    common: dict[str, Any],
    index: int,
    n: int,
    reporter: uuid.UUID,
    at: datetime,
    matching: MatchingStatus,
) -> uuid.UUID:
    report_id = _seed_id(f"report/{n}", index)
    db.add(
        Report(
            id=report_id,
            reference=await allocate(db, common["tenant_id"], ReferenceKind.REPORT),
            reporter_id=reporter,
            matching_status=matching,
            created_at=at,
            updated_at=at,
            **common,
        )
    )
    await db.flush()
    return report_id


async def seed_history(
    *,
    tenant_id: uuid.UUID,
    categories: dict[str, uuid.UUID],
    wards: dict[uuid.UUID, tuple[float, float, float, float]],
    reporters: list[uuid.UUID],
    operator_id: uuid.UUID,
) -> int:
    planned = plan(wards)
    ward_ids = list(wards)
    async with system_session(reason="development seed: analytics history") as db:
        existing = set(
            (
                await db.scalars(
                    select(CivicIssue.id).where(
                        CivicIssue.id.in_([_seed_id("issue", p.index) for p in planned])
                    )
                )
            ).all()
        )
        for issue in planned:
            issue_id = _seed_id("issue", issue.index)
            if issue_id in existing:
                continue
            location = WKTElement(f"POINT({issue.lng} {issue.lat})", srid=4326)
            ward_id = ward_ids[issue.ward]
            address = f"{ADDRESS_PREFIX} {issue.index + 1}, Ward {issue.ward + 1} (synthetic)"
            primary = issue.index % len(reporters)
            people = {primary, *(d[0] for d in issue.duplicates)}
            last = issue.moves[-1][2] if issue.moves else issue.created_at
            db.add(
                CivicIssue(
                    id=issue_id,
                    tenant_id=tenant_id,
                    reference=await allocate(db, tenant_id, ReferenceKind.ISSUE),
                    category_id=categories[issue.category],
                    status=issue.status,
                    location=location,
                    address_text=address,
                    ward_id=ward_id,
                    report_count=1 + len(issue.duplicates),
                    unique_reporter_count=len(people),
                    version=1 + len(issue.moves),
                    status_changed_at=last,
                    resolved_at=issue.resolved_at,
                    created_at=issue.created_at,
                    updated_at=last,
                )
            )
            await db.flush()
            common = {
                "tenant_id": tenant_id,
                "category_id": categories[issue.category],
                "issue_id": issue_id,
                "location": location,
                "address_text": address,
                "ward_id": ward_id,
                "details": {},
                "status": ReportStatus.ACCEPTED,
                "location_accuracy_m": 12.0,
                "location_source": "gps",
                "description": phase1.DESCRIPTIONS[issue.category][issue.index % 2],
            }
            report_id = await _add_report(
                db,
                common,
                issue.index,
                0,
                reporters[primary],
                issue.created_at,
                MatchingStatus.NEW_ISSUE,
            )
            db.add(
                IssueEvent(
                    tenant_id=tenant_id,
                    issue_id=issue_id,
                    report_id=report_id,
                    type=EventType.CREATED,
                    to_status=IssueStatus.REPORTED,
                    visibility=Visibility.PUBLIC,
                    actor_id=reporters[primary],
                    created_at=issue.created_at,
                )
            )
            if issue.reviewed_new:
                # A reviewer looked at an older issue nearby and said no.
                db.add(
                    MatchDecision(
                        id=_seed_id("decision/new", issue.index),
                        tenant_id=tenant_id,
                        report_id=report_id,
                        candidate_issue_id=_seed_id("issue", issue.index - 1),
                        rank=1,
                        score=0.71,
                        signals={"synthetic": True},
                        decision=Decision.NOT_CHOSEN,
                        decided_by=operator_id,
                        created_at=issue.created_at,
                        decided_at=issue.created_at + timedelta(hours=2),
                    )
                )
            previous = IssueStatus.REPORTED
            for status, event, at in issue.moves:
                db.add(
                    IssueEvent(
                        tenant_id=tenant_id,
                        issue_id=issue_id,
                        type=event,
                        from_status=previous,
                        to_status=status,
                        reason="Synthetic rejection: duplicate of a private complaint."
                        if status is IssueStatus.REJECTED
                        else None,
                        visibility=Visibility.PUBLIC,
                        actor_id=operator_id,
                        created_at=at,
                    )
                )
                previous = status
            for n, (reporter, hours, decision, feedback) in enumerate(issue.duplicates, start=1):
                at = issue.created_at + timedelta(hours=hours)
                dup_id = await _add_report(
                    db, common, issue.index, n, reporters[reporter], at, MatchingStatus.LINKED
                )
                auto = decision is Decision.AUTO_LINKED
                db.add(
                    MatchDecision(
                        id=_seed_id(f"decision/{n}", issue.index),
                        tenant_id=tenant_id,
                        report_id=dup_id,
                        candidate_issue_id=issue_id,
                        rank=1,
                        score=0.93 if auto else 0.76,
                        signals={"synthetic": True},
                        decision=decision,
                        decided_by=None if auto else operator_id,
                        created_at=at,
                        decided_at=at if auto else at + timedelta(hours=3),
                        feedback=feedback,
                        feedback_by=operator_id if feedback else None,
                        feedback_at=at + timedelta(days=1) if feedback else None,
                    )
                )
                db.add(
                    IssueEvent(
                        tenant_id=tenant_id,
                        issue_id=issue_id,
                        report_id=dup_id,
                        type=EventType.REPORT_LINKED,
                        visibility=Visibility.PUBLIC,
                        created_at=at,
                    )
                )
            await db.flush()
    return len(planned)
