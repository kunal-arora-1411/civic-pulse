"""Submitting reports and building the report views."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.errors import MfaRequired, NotFound, ValidationFailed
from app.core.pagination import PageParams, paginate
from app.core.storage import ObjectStorage
from app.domains.ai import classifications
from app.domains.ai.models import Classification
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.service import to_ref, validate_details
from app.domains.geo import service as geo
from app.domains.issues.models import (
    CivicIssue,
    EventType,
    IssueEvent,
    ReferenceKind,
    Visibility,
)
from app.domains.issues.references import allocate
from app.domains.matching import views as match_views
from app.domains.media.models import MediaAsset, MediaPurpose, MediaStatus
from app.domains.media.service import thumb_url, to_media_out
from app.domains.org.models import Jurisdiction
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.scope import accessible_jurisdiction_ids
from app.domains.reports.errors import EvidenceRequired, InvalidMedia, OutOfJurisdiction
from app.domains.reports.models import (
    CategorySource,
    LocationSource,
    MatchingStatus,
    Report,
    ReportStatus,
)
from app.domains.reports.schemas import (
    IssueRef,
    LocationOut,
    MyReportIssue,
    MyReportItem,
    PublicTimelineEvent,
    ReportCreate,
    ReporterOut,
    ReporterWithContactOut,
    ReportIssue,
    ReportOwnerView,
    ReportStaffView,
    WardRef,
)
from app.domains.users.models import User
from app.domains.workflow.statuses import IssueStatus

# Phase 1 deployment policy: at least one photo or a description this long,
# checked after the category's own photo rule.
MIN_DESCRIPTION_WITHOUT_PHOTO = 10
_USABLE_MEDIA = (MediaStatus.PROCESSING, MediaStatus.READY)


# --- submission ------------------------------------------------------------------------


async def _active_category(db: AsyncSession, category_id: uuid.UUID) -> Category:
    category = await db.scalar(
        select(Category).where(Category.id == category_id, Category.is_active.is_(True))
    )
    if category is None:
        raise ValidationFailed(
            "Unknown category.",
            details={
                "errors": [
                    {
                        "loc": ["body", "category_id"],
                        "msg": "Unknown or inactive category.",
                        "type": "invalid_value",
                    }
                ]
            },
        )
    return category


async def _claim_media(
    db: AsyncSession, principal: Principal, media_ids: Sequence[uuid.UUID]
) -> list[MediaAsset]:
    """Lock and check the media to attach, returned in the order given.

    Locking (in a fixed order, so two submissions can't deadlock) means two
    concurrent reports can't both attach the same photo.
    """
    if not media_ids:
        return []
    rows = await db.scalars(
        select(MediaAsset)
        .where(MediaAsset.id.in_(media_ids))
        .order_by(MediaAsset.id)
        .with_for_update()
    )
    found = {asset.id: asset for asset in rows}
    invalid: list[dict[str, str]] = []
    for media_id in media_ids:
        asset = found.get(media_id)
        if asset is None or asset.owner_id != principal.user_id:
            # Someone else's upload is indistinguishable from a missing one.
            invalid.append({"id": str(media_id), "reason": "not_found"})
        elif asset.purpose != MediaPurpose.REPORT_EVIDENCE:
            invalid.append({"id": str(media_id), "reason": "wrong_purpose"})
        elif asset.status not in _USABLE_MEDIA:
            reason = "failed" if asset.status == MediaStatus.FAILED else "not_completed"
            invalid.append({"id": str(media_id), "reason": reason})
        elif asset.report_id is not None:
            invalid.append({"id": str(media_id), "reason": "already_attached"})
    if invalid:
        raise InvalidMedia(details={"media": invalid})
    return [found[media_id] for media_id in media_ids]


async def create_report(db: AsyncSession, principal: Principal, body: ReportCreate) -> uuid.UUID:
    """Validate and store a report in one transaction; returns its id.

    The report has no issue yet (`matching_status = pending`): the caller
    queues duplicate matching once this has committed, and matching links
    it to an issue, sends it to review or starts a new issue.
    """
    tenant_id = principal.tenant_id
    assert tenant_id is not None

    category = await _active_category(db, body.category_id)

    placement = await geo.place(db, body.location.lng, body.location.lat)
    if not placement.in_jurisdiction:
        raise OutOfJurisdiction(details={"lat": body.location.lat, "lng": body.location.lng})

    photos = len(body.media_ids)
    if not category.min_photos <= photos <= category.max_photos:
        raise EvidenceRequired(
            f"This category needs {category.min_photos} to {category.max_photos} photos.",
            details={
                "min_photos": category.min_photos,
                "max_photos": category.max_photos,
                "received": photos,
            },
        )

    media = await _claim_media(db, principal, body.media_ids)
    details = validate_details(category.fields, body.details)

    if photos == 0 and len(body.description or "") < MIN_DESCRIPTION_WITHOUT_PHOTO:
        raise EvidenceRequired(
            "Add a photo, or describe the problem in at least "
            f"{MIN_DESCRIPTION_WITHOUT_PHOTO} characters.",
            details={
                "min_photos": 1,
                "min_description_length": MIN_DESCRIPTION_WITHOUT_PHOTO,
                "received": photos,
            },
        )

    category_source = await _category_source(db, principal, body, category)

    # Everything is valid. The reference last: its counter row stays locked
    # until this transaction commits.
    report_reference = await allocate(db, tenant_id, ReferenceKind.REPORT)
    location = WKTElement(f"POINT({body.location.lng} {body.location.lat})", srid=4326)
    ward_id = placement.ward.id if placement.ward else None
    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        reference=report_reference,
        reporter_id=principal.user_id,
        category_id=category.id,
        # No issue yet: duplicate matching decides after this commits.
        issue_id=None,
        matching_status=MatchingStatus.PENDING,
        status=ReportStatus.ACCEPTED,
        description=body.description,
        details=details,
        location=location,
        location_accuracy_m=body.location.accuracy_m,
        location_source=body.location.source,
        address_text=body.address_text,
        ward_id=ward_id,
        client_created_at=body.client_created_at,
        classification_id=body.classification_id,
        category_source=category_source,
    )
    db.add(report)
    await db.flush()

    for position, asset in enumerate(media):
        asset.report_id = report.id
        asset.position = position
    await db.flush()

    await audit.record(
        db,
        action="report.created",
        entity_type="report",
        entity_id=report.id,
        actor=principal,
        after={
            "reference": report.reference,
            "category": category.code,
            "category_source": category_source.value,
            "classification_id": str(body.classification_id) if body.classification_id else None,
            "ward_id": str(ward_id) if ward_id else None,
            "location_source": body.location.source.value,
            "media_ids": [str(m.id) for m in media],
            "matching_status": report.matching_status,
        },
    )
    return report.id


async def _category_source(
    db: AsyncSession, principal: Principal, body: ReportCreate, category: Category
) -> CategorySource:
    """`ai_accepted` when the citizen kept the top suggestion, `ai_corrected`
    when they chose another category (a label for FR-021), `citizen` when
    no suggestion was available."""
    if body.classification_id is None:
        return CategorySource.CITIZEN
    classification = await db.scalar(
        select(Classification).where(Classification.id == body.classification_id)
    )
    if classification is None or classification.requested_by != principal.user_id:
        raise ValidationFailed(
            "Unknown classification.",
            details={
                "errors": [
                    {
                        "loc": ["body", "classification_id"],
                        "msg": "Unknown classification.",
                        "type": "invalid_value",
                    }
                ]
            },
        )
    suggestions = await classifications.suggestions_for(db, classification)
    if not suggestions:
        return CategorySource.CITIZEN
    if suggestions[0].category_id == category.id:
        return CategorySource.AI_ACCEPTED
    return CategorySource.AI_CORRECTED


# --- views -----------------------------------------------------------------------------


@dataclass(slots=True)
class ReportRow:
    report: Report
    lng: float
    lat: float
    category: Category
    ward_name: str | None
    issue: CivicIssue | None


async def fetch_report_rows(
    db: AsyncSession, *where: ColumnElement[bool], order_oldest_first: bool = True
) -> list[ReportRow]:
    ward = aliased(Jurisdiction)
    stmt = (
        select(
            Report,
            func.ST_X(Report.location),
            func.ST_Y(Report.location),
            Category,
            ward.name,
            CivicIssue,
        )
        .join(Category, Category.id == Report.category_id)
        .outerjoin(ward, ward.id == Report.ward_id)
        .outerjoin(CivicIssue, CivicIssue.id == Report.issue_id)
        .where(*where)
        .order_by(Report.created_at if order_oldest_first else Report.created_at.desc(), Report.id)
    )
    return [
        ReportRow(report=r, lng=float(x), lat=float(y), category=c, ward_name=w, issue=i)
        for r, x, y, c, w, i in (await db.execute(stmt)).all()
    ]


async def media_for_reports(
    db: AsyncSession, report_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MediaAsset]]:
    grouped: dict[uuid.UUID, list[MediaAsset]] = defaultdict(list)
    if not report_ids:
        return grouped
    rows = await db.scalars(
        select(MediaAsset)
        .where(MediaAsset.report_id.in_(report_ids))
        .order_by(MediaAsset.report_id, MediaAsset.position)
    )
    for asset in rows:
        assert asset.report_id is not None
        grouped[asset.report_id].append(asset)
    return grouped


async def public_timeline(db: AsyncSession, issue_id: uuid.UUID) -> list[PublicTimelineEvent]:
    rows = await db.scalars(
        select(IssueEvent)
        .where(IssueEvent.issue_id == issue_id, IssueEvent.visibility == Visibility.PUBLIC)
        .order_by(IssueEvent.created_at, IssueEvent.id)
    )
    return [
        PublicTimelineEvent(
            at=event.created_at,
            type=EventType(event.type),
            from_status=IssueStatus(event.from_status) if event.from_status else None,
            to_status=IssueStatus(event.to_status) if event.to_status else None,
            public_note=event.public_note,
        )
        for event in rows
    ]


def base_fields(
    row: ReportRow, media: list[MediaAsset], storage: ObjectStorage, *, staff: bool
) -> dict[str, Any]:
    report = row.report
    return {
        "id": report.id,
        "reference": report.reference,
        "created_at": report.created_at,
        "category": to_ref(row.category),
        "description": report.description,
        "details": report.details,
        "location": LocationOut(
            lat=row.lat,
            lng=row.lng,
            accuracy_m=report.location_accuracy_m,
            source=LocationSource(report.location_source),
        ),
        "address_text": report.address_text,
        "ward": WardRef(id=report.ward_id, name=row.ward_name)
        if report.ward_id and row.ward_name
        else None,
        "media": [to_media_out(storage, m, staff=staff) for m in media],
        "status": ReportStatus(report.status),
        "matching_status": MatchingStatus(report.matching_status),
    }


async def owner_view(db: AsyncSession, storage: ObjectStorage, row: ReportRow) -> ReportOwnerView:
    media = await media_for_reports(db, [row.report.id])
    issue = None
    if row.issue is not None:
        issue = ReportIssue(
            id=row.issue.id,
            reference=row.issue.reference,
            status=IssueStatus(row.issue.status),
            report_count=row.issue.report_count,
            unique_reporter_count=row.issue.unique_reporter_count,
            timeline=await public_timeline(db, row.issue.id),
        )
    return ReportOwnerView(
        **base_fields(row, media[row.report.id], storage, staff=False), issue=issue
    )


async def get_owner_view(
    db: AsyncSession, storage: ObjectStorage, report_id: uuid.UUID
) -> ReportOwnerView | None:
    rows = await fetch_report_rows(db, Report.id == report_id)
    return await owner_view(db, storage, rows[0]) if rows else None


async def staff_views(
    db: AsyncSession, storage: ObjectStorage, rows: Sequence[ReportRow], *, with_contact: bool
) -> list[ReportStaffView]:
    """Staff report views. Reporter contact details only when `with_contact`
    (callers holding `user:manage`); otherwise just id and display name."""
    if not rows:
        return []
    media = await media_for_reports(db, [row.report.id for row in rows])
    matches = await match_views.summaries(db, [row.report.id for row in rows])
    decisions = await match_views.decisions(db, [row.report.id for row in rows])
    reporter_ids = {row.report.reporter_id for row in rows}
    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User.id, User.display_name, User.phone, User.email).where(
                    User.id.in_(reporter_ids)
                )
            )
        ).all()
    }
    views: list[ReportStaffView] = []
    for row in rows:
        user = users.get(row.report.reporter_id)
        reporter: ReporterOut
        if user is not None and with_contact:
            reporter = ReporterWithContactOut(
                id=user.id, display_name=user.display_name, phone=user.phone, email=user.email
            )
        else:
            reporter = ReporterOut(
                id=row.report.reporter_id, display_name=user.display_name if user else None
            )
        views.append(
            ReportStaffView(
                **base_fields(row, media[row.report.id], storage, staff=True),
                reporter=reporter,
                client_created_at=row.report.client_created_at,
                category_source=CategorySource(row.report.category_source),
                match=matches.get(row.report.id),
                match_decisions=decisions.get(row.report.id, []),
                issue=IssueRef(
                    id=row.issue.id,
                    reference=row.issue.reference,
                    status=IssueStatus(row.issue.status),
                )
                if row.issue
                else None,
            )
        )
    return views


def in_scope(scope: set[uuid.UUID] | None, ward_id: uuid.UUID | None) -> bool:
    """Whether a jurisdiction scope (None = whole tenant) covers a ward.

    Something with no ward is only visible to tenant-wide staff.
    """
    if scope is None:
        return True
    return ward_id is not None and ward_id in scope


async def get_report_view(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, report_id: uuid.UUID
) -> ReportOwnerView | ReportStaffView:
    """The owner's view for the reporter; the staff view for `report:read`
    within scope; 404 for everyone else, so nothing about the report leaks."""
    rows = await fetch_report_rows(db, Report.id == report_id)
    if not rows:
        raise NotFound()
    row = rows[0]
    if row.report.reporter_id == principal.user_id:
        return await owner_view(db, storage, row)
    if not principal.has(Permission.REPORT_READ):
        raise NotFound()
    scope = await accessible_jurisdiction_ids(db, principal, Permission.REPORT_READ)
    if not in_scope(scope, row.report.ward_id):
        raise NotFound()
    enforce_staff_mfa(principal)
    (view,) = await staff_views(
        db, storage, [row], with_contact=principal.has(Permission.USER_MANAGE)
    )
    return view


def enforce_staff_mfa(principal: Principal) -> None:
    """The REQUIRE_STAFF_MFA gate, for staff paths not guarded by `require`."""
    if get_settings().staff_mfa_required and not principal.mfa_verified:
        raise MfaRequired()


MY_REPORT_SORT = (Report.created_at.desc(), Report.id.desc())


async def list_mine(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    params: PageParams,
    *,
    statuses: Sequence[IssueStatus],
) -> tuple[list[MyReportItem], int]:
    cover = aliased(MediaAsset)
    stmt = (
        select(
            Report, Category, CivicIssue.reference, CivicIssue.status, cover.status, cover.thumb_key
        )
        .join(Category, Category.id == Report.category_id)
        .outerjoin(CivicIssue, CivicIssue.id == Report.issue_id)
        .outerjoin(cover, and_(cover.report_id == Report.id, cover.position == 0))
        .where(Report.reporter_id == principal.user_id)
        .order_by(*MY_REPORT_SORT)
    )
    if statuses:
        stmt = stmt.where(CivicIssue.status.in_([s.value for s in statuses]))
    rows, total = await paginate(db, stmt, params)
    items = [
        MyReportItem(
            id=report.id,
            reference=report.reference,
            created_at=report.created_at,
            category=to_ref(category),
            thumb_url=thumb_url(storage, media_status, thumb_key),
            address_text=report.address_text,
            matching_status=MatchingStatus(report.matching_status),
            issue=MyReportIssue(reference=issue_ref, status=IssueStatus(issue_status))
            if issue_ref
            else None,
        )
        for report, category, issue_ref, issue_status, media_status, thumb_key in rows
    ]
    return items, total
