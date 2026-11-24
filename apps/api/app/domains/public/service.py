"""Public resolution tracking: read-only views of a tenant's issues.

Privacy (PRD FR-051, §12.2): exact points never leave the database. Every
location is replaced by the centre of its H3 cell at PUBLIC_H3_RESOLUTION
(edges of about 175 m on average), so nearby issues share a point and no
single report can be traced to a doorstep. Photos are the processed public
copies, which exist only after faces have been blurred; address text,
reporter identities and internal notes are not exposed at all.

Rejected issues and issues whose every report was withdrawn are not shown.
Merged issues are kept addressable (their page points at the survivor) but
drop out of lists and the map.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.core.storage import ObjectStorage
from app.domains.categories.models import Category
from app.domains.categories.service import to_ref
from app.domains.issues.models import CivicIssue
from app.domains.issues.schemas import PointGeometry
from app.domains.media.models import MediaAsset, MediaStatus
from app.domains.media.service import thumb_url
from app.domains.org.models import Jurisdiction, JurisdictionKind
from app.domains.public.schemas import (
    GeneralisedPoint,
    PublicFeature,
    PublicFeatureCollection,
    PublicFeatureProperties,
    PublicIssueDetail,
    PublicIssueItem,
    PublicPhoto,
    Scorecard,
    WardScore,
)
from app.domains.reports import service as reports
from app.domains.reports.models import Report, ReportStatus
from app.domains.reports.schemas import WardRef
from app.domains.workflow.statuses import IssueStatus

PUBLIC_H3_RESOLUTION = 9
PUBLIC_PRECISION_M = 175
FEATURE_CAP = 2000
MAX_PHOTOS = 6
RESOLVED = (IssueStatus.RESOLVED.value, IssueStatus.CLOSED.value)
NOT_OPEN = (*RESOLVED, IssueStatus.REJECTED.value)

_ward = aliased(Jurisdiction)
_cover = aliased(MediaAsset)


def _cell_centre() -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    """(lng, lat) of the centre of the issue's H3 cell, computed in SQL."""
    point = func.point(func.ST_X(CivicIssue.location), func.ST_Y(CivicIssue.location))
    centre = func.geometry(
        func.h3_cell_to_lat_lng(func.h3_lat_lng_to_cell(point, PUBLIC_H3_RESOLUTION))
    )
    return func.ST_X(centre), func.ST_Y(centre)


def _visible() -> list[ColumnElement[bool]]:
    return [
        CivicIssue.merged_into_id.is_(None),
        CivicIssue.status != IssueStatus.REJECTED,
        CivicIssue.report_count > 0,
    ]


def _select():  # the inferred Select[...] row type is the useful annotation
    lng, lat = _cell_centre()
    return (
        select(CivicIssue, lng, lat, Category, _ward.name, _cover.status, _cover.thumb_key)
        .join(Category, Category.id == CivicIssue.category_id)
        .outerjoin(_ward, _ward.id == CivicIssue.ward_id)
        .outerjoin(_cover, _cover.id == CivicIssue.cover_media_id)
    )


def _item_fields(storage: ObjectStorage, row: Any, now: datetime) -> dict[str, Any]:
    issue, lng, lat, category, ward_name, cover_status, cover_thumb = row
    return {
        "id": issue.id,
        "reference": issue.reference,
        "status": IssueStatus(issue.status),
        "category": to_ref(category),
        "ward": WardRef(id=issue.ward_id, name=ward_name) if issue.ward_id and ward_name else None,
        "location": GeneralisedPoint(
            lat=round(float(lat), 6), lng=round(float(lng), 6), precision_m=PUBLIC_PRECISION_M
        ),
        "report_count": issue.report_count,
        "support_count": issue.support_count,
        "thumb_url": thumb_url(storage, cover_status, cover_thumb),
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "resolved_at": issue.resolved_at,
        "age_days": round((now - issue.created_at).total_seconds() / 86400, 1),
    }


_SORTS: dict[str, list[Any]] = {
    "-created_at": [CivicIssue.created_at.desc()],
    "created_at": [CivicIssue.created_at.asc()],
    "-updated_at": [CivicIssue.updated_at.desc()],
    "-support_count": [CivicIssue.support_count.desc(), CivicIssue.created_at.desc()],
    "-report_count": [CivicIssue.report_count.desc(), CivicIssue.created_at.desc()],
}
SORTS = tuple(_SORTS)


def _filtered(
    stmt: Any,
    *,
    statuses: list[IssueStatus] | None,
    category_id: uuid.UUID | None,
    ward_id: uuid.UUID | None,
) -> Any:
    stmt = stmt.where(*_visible())
    if statuses:
        stmt = stmt.where(CivicIssue.status.in_([s.value for s in statuses]))
    if category_id:
        stmt = stmt.where(CivicIssue.category_id == category_id)
    if ward_id:
        stmt = stmt.where(CivicIssue.ward_id == ward_id)
    return stmt


async def list_issues(
    db: AsyncSession,
    storage: ObjectStorage,
    page: PageParams,
    *,
    statuses: list[IssueStatus] | None = None,
    category_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    sort: str = "-created_at",
) -> tuple[list[PublicIssueItem], int]:
    stmt = _filtered(_select(), statuses=statuses, category_id=category_id, ward_id=ward_id)
    stmt = stmt.order_by(*_SORTS.get(sort, _SORTS["-created_at"]), CivicIssue.id)
    rows, total = await paginate(db, stmt, page)
    now = datetime.now(UTC)
    return [PublicIssueItem(**_item_fields(storage, row, now)) for row in rows], total


async def geojson(
    db: AsyncSession,
    *,
    statuses: list[IssueStatus] | None = None,
    category_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
) -> PublicFeatureCollection:
    lng, lat = _cell_centre()
    stmt = (
        select(
            CivicIssue.id,
            CivicIssue.reference,
            CivicIssue.status,
            Category.code,
            CivicIssue.report_count,
            CivicIssue.support_count,
            lng,
            lat,
        )
        .join(Category, Category.id == CivicIssue.category_id)
        .order_by(CivicIssue.created_at.desc(), CivicIssue.id.desc())
        .limit(FEATURE_CAP + 1)
    )
    stmt = _filtered(stmt, statuses=statuses, category_id=category_id, ward_id=ward_id)
    rows: list[Any] = list((await db.execute(stmt)).all())
    return PublicFeatureCollection(
        features=[
            PublicFeature(
                id=issue_id,
                geometry=PointGeometry(coordinates=(round(float(x), 6), round(float(y), 6))),
                properties=PublicFeatureProperties(
                    id=issue_id,
                    reference=reference,
                    status=IssueStatus(status),
                    category_code=code,
                    report_count=report_count,
                    support_count=support_count,
                ),
            )
            for issue_id, reference, status, code, report_count, support_count, x, y in rows[
                :FEATURE_CAP
            ]
        ],
        truncated=len(rows) > FEATURE_CAP,
    )


def _photos(storage: ObjectStorage, assets: list[MediaAsset]) -> list[PublicPhoto]:
    """Only ready assets: their public copies exist and are face-blurred."""
    photos: list[PublicPhoto] = []
    for asset in assets:
        thumb = thumb_url(storage, asset.status, asset.thumb_key)
        display = thumb_url(storage, asset.status, asset.display_key)
        if thumb and display:
            photos.append(PublicPhoto(thumb_url=thumb, display_url=display))
    return photos[:MAX_PHOTOS]


async def get_issue(
    db: AsyncSession, storage: ObjectStorage, issue_id: uuid.UUID
) -> PublicIssueDetail:
    row = (
        await db.execute(
            _select().where(CivicIssue.id == issue_id, CivicIssue.status != IssueStatus.REJECTED)
        )
    ).one_or_none()
    if row is None:
        raise NotFound()
    issue: CivicIssue = row[0]
    merged_into = None
    if issue.merged_into_id is not None:
        merged_into = await db.scalar(
            select(CivicIssue.reference).where(CivicIssue.id == issue.merged_into_id)
        )
    elif issue.report_count == 0:
        raise NotFound()
    before = list(
        await db.scalars(
            select(MediaAsset)
            .join(Report, Report.id == MediaAsset.report_id)
            .where(
                and_(
                    Report.issue_id == issue.id,
                    Report.status == ReportStatus.ACCEPTED,
                    MediaAsset.status == MediaStatus.READY,
                )
            )
            .order_by(Report.created_at, MediaAsset.position)
        )
    )
    closure = await reports.latest_closure(db, issue)
    after = await reports.after_photos(db, closure.work_order_id) if closure else []
    return PublicIssueDetail(
        **_item_fields(storage, row, datetime.now(UTC)),
        timeline=await reports.public_timeline(db, issue.id),
        before_photos=_photos(storage, before),
        after_photos=_photos(storage, after),
        merged_into=merged_into,
    )


async def scorecard(db: AsyncSession) -> Scorecard:
    resolved = and_(CivicIssue.status.in_(RESOLVED), CivicIssue.resolved_at.is_not(None))
    days = func.extract("epoch", CivicIssue.resolved_at - CivicIssue.created_at) / 86400
    rows = (
        await db.execute(
            select(
                Jurisdiction.id,
                Jurisdiction.name,
                func.count(CivicIssue.id).filter(CivicIssue.status.not_in(NOT_OPEN)),
                func.count(CivicIssue.id).filter(resolved),
                func.percentile_cont(0.5).within_group(days).filter(resolved),
            )
            .outerjoin(
                CivicIssue,
                and_(CivicIssue.ward_id == Jurisdiction.id, *_visible()),
            )
            .where(Jurisdiction.kind == JurisdictionKind.WARD)
            .group_by(Jurisdiction.id, Jurisdiction.name)
            .order_by(Jurisdiction.name, Jurisdiction.id)
        )
    ).all()
    return Scorecard(
        wards=[
            WardScore(
                ward=WardRef(id=ward_id, name=name),
                open_count=int(open_count),
                resolved_count=int(resolved_count),
                median_resolution_days=round(float(median), 1) if median is not None else None,
            )
            for ward_id, name, open_count, resolved_count, median in rows
        ]
    )
