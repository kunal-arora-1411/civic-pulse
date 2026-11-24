"""Civic issues for staff: the queue, the map, the detail page."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, case, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate, sort_clauses
from app.core.storage import ObjectStorage
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.service import to_ref
from app.domains.issues.errors import InvalidTransition, ReasonRequired, VersionConflict
from app.domains.issues.filters import IssueFilters
from app.domains.issues.models import (
    CivicIssue,
    EventType,
    IssueEvent,
    SeveritySource,
    Visibility,
)
from app.domains.issues.schemas import (
    AllowedTransition,
    EventActor,
    IssueDetail,
    IssueFeature,
    IssueFeatureCollection,
    IssueFeatureProperties,
    IssueListItem,
    PointGeometry,
    PointOut,
    PriorityDetailOut,
    PriorityFactorOut,
    PriorityOut,
    SeverityOut,
    StatusChange,
    TimelineEvent,
)
from app.domains.media.models import MediaAsset
from app.domains.media.service import thumb_url
from app.domains.org.models import Jurisdiction
from app.domains.priority import service as priority
from app.domains.priority.rules import BAND_ORDER, PriorityBand, SeverityLevel
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.roles import Role
from app.domains.rbac.scope import accessible_jurisdiction_ids, jurisdiction_subtree, scope_filter
from app.domains.reports import service as reports
from app.domains.reports.models import Report
from app.domains.reports.schemas import WardRef
from app.domains.users.models import User
from app.domains.workflow import service as workflow
from app.domains.workflow.statuses import IssueStatus

GEOJSON_FEATURE_CAP = 5000

SORTS = {
    "created_at": CivicIssue.created_at,
    "updated_at": CivicIssue.updated_at,
    "report_count": CivicIssue.report_count,
}
DEFAULT_SORT = "-priority"
# For validation and the error message only; `_order` handles `priority`.
SORTS_WITH_PRIORITY = {**SORTS, "priority": CivicIssue.priority_score}

# The band staff see: a manual override wins over the computed band.
EFFECTIVE_BAND = func.coalesce(CivicIssue.priority_override_band, CivicIssue.priority_band)
_BAND_RANK = case(BAND_ORDER, value=EFFECTIVE_BAND, else_=-1)

_ward = aliased(Jurisdiction)
_cover = aliased(MediaAsset)

_PREFIX_SQL = text(
    "SELECT coalesce(string_agg(quote_literal(lexeme) || ':*', ' & '), '') "
    "FROM unnest(to_tsvector('simple', :q))"
)


async def issue_scope(db: AsyncSession, principal: Principal) -> set[uuid.UUID] | None:
    """Wards the caller may see issues in (None: the whole tenant)."""
    return await accessible_jurisdiction_ids(db, principal, Permission.ISSUE_READ)


async def _prefix_query(db: AsyncSession, q: str) -> str:
    """A tsquery string matching every word of `q` by prefix.

    Postgres does the tokenising (so Hindi words split the same way as in
    the indexed document) and the quoting, so user input never reaches
    to_tsquery's syntax unescaped.
    """
    value = await db.scalar(_PREFIX_SQL, {"q": q})
    return value or ""


def _search(q: str, tsquery: str) -> ColumnElement[bool]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    report_ref = exists().where(
        Report.issue_id == CivicIssue.id, Report.reference.ilike(pattern, escape="\\")
    )
    conditions: list[ColumnElement[bool]] = [
        CivicIssue.reference.ilike(pattern, escape="\\"),
        report_ref,
    ]
    if tsquery:
        conditions.append(CivicIssue.search_document.op("@@")(func.to_tsquery("simple", tsquery)))
    return or_(*conditions)


async def _apply_filters[*Ts](
    db: AsyncSession, stmt: Select[*Ts], principal: Principal, filters: IssueFilters
) -> Select[*Ts]:
    scope = await issue_scope(db, principal)
    # RLS already limits rows to the tenant. Saying so explicitly lets the
    # planner use the (tenant_id, ...) indexes, which the policy's
    # "OR bypass" form hides from it (see ADR 0002).
    stmt = stmt.where(
        CivicIssue.tenant_id == principal.tenant_id,
        scope_filter(CivicIssue.ward_id, scope),
        # Merged issues are tombstones: readable by id, never listed.
        CivicIssue.merged_into_id.is_(None),
    )
    if filters.severities:
        stmt = stmt.where(CivicIssue.severity.in_([s.value for s in filters.severities]))
    if filters.priority_bands:
        stmt = stmt.where(EFFECTIVE_BAND.in_([b.value for b in filters.priority_bands]))
    if filters.statuses:
        stmt = stmt.where(CivicIssue.status.in_([s.value for s in filters.statuses]))
    if filters.category_ids:
        stmt = stmt.where(CivicIssue.category_id.in_(filters.category_ids))
    if filters.ward_ids:
        stmt = stmt.where(CivicIssue.ward_id.in_(filters.ward_ids))
    if filters.created_from:
        stmt = stmt.where(CivicIssue.created_at >= filters.created_from)
    if filters.created_before:
        stmt = stmt.where(CivicIssue.created_at < filters.created_before)
    if filters.bbox:
        envelope = func.ST_MakeEnvelope(*filters.bbox, 4326)
        stmt = stmt.where(func.ST_Intersects(CivicIssue.location, envelope))
    if filters.q:
        stmt = stmt.where(_search(filters.q, await _prefix_query(db, filters.q)))
    return stmt


def _list_select():  # the inferred Select[...] row type is the useful annotation
    return (
        select(
            CivicIssue,
            func.ST_X(CivicIssue.location),
            func.ST_Y(CivicIssue.location),
            Category,
            _ward.name,
            _cover.status,
            _cover.thumb_key,
        )
        .join(Category, Category.id == CivicIssue.category_id)
        .outerjoin(_ward, _ward.id == CivicIssue.ward_id)
        .outerjoin(_cover, _cover.id == CivicIssue.cover_media_id)
    )


def severity_out(issue: CivicIssue) -> SeverityOut:
    return SeverityOut(
        level=SeverityLevel(issue.severity),
        source=SeveritySource(issue.severity_source),
        reason=issue.severity_reason,
    )


def priority_out(issue: CivicIssue) -> PriorityOut | None:
    if issue.priority_score is None or issue.priority_band is None:
        return None
    computed = PriorityBand(issue.priority_band)
    override = PriorityBand(issue.priority_override_band) if issue.priority_override_band else None
    return PriorityOut(
        score=float(issue.priority_score),
        band=override or computed,
        computed_band=computed,
        overridden=override is not None,
        override_reason=issue.priority_override_reason,
    )


def priority_detail_out(issue: CivicIssue) -> PriorityDetailOut | None:
    summary = priority_out(issue)
    if summary is None:
        return None
    factors = [PriorityFactorOut.model_validate(f) for f in issue.priority_factors or []]
    return PriorityDetailOut(**summary.model_dump(), factors=factors)


def _list_item(storage: ObjectStorage, row: Any) -> IssueListItem:
    issue, x, y, category, ward_name, cover_status, cover_thumb = row
    return IssueListItem(
        id=issue.id,
        reference=issue.reference,
        status=IssueStatus(issue.status),
        category=to_ref(category),
        location=PointOut(lat=float(y), lng=float(x)),
        address_text=issue.address_text,
        ward=WardRef(id=issue.ward_id, name=ward_name) if issue.ward_id and ward_name else None,
        report_count=issue.report_count,
        unique_reporter_count=issue.unique_reporter_count,
        severity=severity_out(issue),
        priority=priority_out(issue),
        thumb_url=thumb_url(storage, cover_status, cover_thumb),
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        version=issue.version,
    )


def _order(sort: str | None) -> list[Any]:
    """`priority` sorts by the effective band, then the score, with issues
    not computed yet last either way. Everything else uses the generic helper."""
    value = (sort or DEFAULT_SORT).strip()
    if value.lstrip("-+") != "priority":
        return sort_clauses(
            value, SORTS_WITH_PRIORITY, default=DEFAULT_SORT, tiebreaker=CivicIssue.id
        )
    if value.startswith("-"):
        return [
            _BAND_RANK.desc(),
            CivicIssue.priority_score.desc().nulls_last(),
            CivicIssue.created_at.desc(),
            CivicIssue.id.desc(),
        ]
    return [
        _BAND_RANK.asc(),
        CivicIssue.priority_score.asc().nulls_last(),
        CivicIssue.created_at.asc(),
        CivicIssue.id.asc(),
    ]


async def list_issues(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    params: PageParams,
    filters: IssueFilters,
    *,
    sort: str | None,
) -> tuple[list[IssueListItem], int]:
    stmt = await _apply_filters(db, _list_select(), principal, filters)
    stmt = stmt.order_by(*_order(sort))
    rows, total = await paginate(db, stmt, params)
    return [_list_item(storage, row) for row in rows], total


async def issues_geojson(
    db: AsyncSession, principal: Principal, filters: IssueFilters
) -> IssueFeatureCollection:
    stmt = (
        select(
            CivicIssue.id,
            CivicIssue.reference,
            CivicIssue.status,
            Category.code,
            CivicIssue.report_count,
            func.ST_X(CivicIssue.location),
            func.ST_Y(CivicIssue.location),
            CivicIssue.severity,
            EFFECTIVE_BAND,
        )
        .join(Category, Category.id == CivicIssue.category_id)
        .order_by(CivicIssue.created_at.desc(), CivicIssue.id.desc())
        .limit(GEOJSON_FEATURE_CAP + 1)
    )
    stmt = await _apply_filters(db, stmt, principal, filters)
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > GEOJSON_FEATURE_CAP
    features = [
        IssueFeature(
            id=issue_id,
            geometry=PointGeometry(coordinates=(float(x), float(y))),
            properties=IssueFeatureProperties(
                id=issue_id,
                reference=reference,
                status=IssueStatus(status),
                category_code=code,
                report_count=report_count,
                severity=SeverityLevel(severity),
                priority_band=PriorityBand(band) if band else None,
            ),
        )
        for issue_id, reference, status, code, report_count, x, y, severity, band in rows[
            :GEOJSON_FEATURE_CAP
        ]
    ]
    return IssueFeatureCollection(features=features, truncated=truncated)


async def get_in_scope(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, *, for_update: bool = False
) -> CivicIssue:
    """The issue, if it exists in this tenant and the caller's scope; else 404.

    Out of scope is deliberately the same 404 as missing, so nothing about
    the issue's existence leaks.
    """
    stmt = select(CivicIssue).where(CivicIssue.id == issue_id)
    if for_update:
        stmt = stmt.with_for_update()
    issue = await db.scalar(stmt)
    if issue is None:
        raise NotFound()
    scope = await issue_scope(db, principal)
    if not reports.in_scope(scope, issue.ward_id):
        raise NotFound()
    return issue


async def roles_for_ward(
    db: AsyncSession, principal: Principal, ward_id: uuid.UUID | None
) -> set[Role]:
    """The caller's roles that apply at this ward.

    A grant scoped to a zone applies to the zone's wards; an unscoped grant
    applies everywhere. An operator for Zone North who is also a supervisor
    for Zone South acts as a supervisor only in the south.
    """
    roles: set[Role] = set()
    for grant in principal.grants:
        if grant.jurisdiction_id is None:
            roles.add(grant.role)
            continue
        if ward_id is None:
            continue
        if ward_id in await jurisdiction_subtree(db, [grant.jurisdiction_id]):
            roles.add(grant.role)
    return roles


async def allowed_transitions(
    db: AsyncSession, principal: Principal, issue: CivicIssue
) -> list[AllowedTransition]:
    if issue.merged_into_id is not None:
        return []  # a merged issue is frozen; act on the one it was merged into
    roles = await roles_for_ward(db, principal, issue.ward_id)
    return [
        AllowedTransition(to_status=IssueStatus(t.to_status), requires_reason=t.requires_reason)
        for t in await workflow.transitions_from(db, issue.status)
        if workflow.permits(t, roles)
    ]


async def _timeline(db: AsyncSession, issue_id: uuid.UUID) -> list[TimelineEvent]:
    rows = await db.execute(
        select(IssueEvent, User.display_name)
        .outerjoin(User, User.id == IssueEvent.actor_id)
        .where(IssueEvent.issue_id == issue_id)
        .order_by(IssueEvent.created_at, IssueEvent.id)
    )
    return [
        TimelineEvent(
            id=event.id,
            at=event.created_at,
            type=EventType(event.type),
            from_status=IssueStatus(event.from_status) if event.from_status else None,
            to_status=IssueStatus(event.to_status) if event.to_status else None,
            reason=event.reason,
            public_note=event.public_note,
            visibility=Visibility(event.visibility),
            actor=EventActor(id=event.actor_id, display_name=name) if event.actor_id else None,
        )
        for event, name in rows
    ]


async def change_status(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, change: StatusChange
) -> None:
    """Move an issue along the tenant's workflow (PRD FR-052 to FR-054).

    The row is locked first, so the version check and the update can't
    interleave with another change: of two concurrent requests holding the
    same version, one wins and the other gets 409 with the new version.
    Every change writes a timeline event and an audit event and bumps the
    version.
    """
    issue = await get_in_scope(db, principal, issue_id, for_update=True)
    if change.version != issue.version:
        raise VersionConflict(details={"version": issue.version})

    allowed = await allowed_transitions(db, principal, issue)
    target = next((t for t in allowed if t.to_status == change.to_status), None)
    if target is None:
        raise InvalidTransition(
            details={
                "from_status": issue.status,
                "to_status": change.to_status.value,
                "allowed_transitions": [t.model_dump(mode="json") for t in allowed],
            }
        )
    if target.requires_reason and not change.reason:
        raise ReasonRequired(details={"to_status": change.to_status.value})

    before = {"status": issue.status, "version": issue.version}
    issue.status = change.to_status.value
    issue.version += 1
    issue.status_changed_at = datetime.now(UTC)
    db.add(
        IssueEvent(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            type=EventType.STATUS_CHANGED,
            from_status=before["status"],
            to_status=issue.status,
            reason=change.reason,
            public_note=change.public_note,
            # The move itself is public; its reason stays internal because
            # the citizen view never includes reasons.
            visibility=Visibility.PUBLIC,
            actor_id=principal.user_id,
        )
    )
    await db.flush()
    await priority.recompute(db, issue.id)
    await audit.record(
        db,
        action="issue.status_changed",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        before=before,
        after={
            "status": issue.status,
            "version": issue.version,
            "reason": change.reason,
            "public_note": change.public_note,
        },
    )


async def get_detail(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, issue_id: uuid.UUID
) -> IssueDetail:
    issue = await get_in_scope(db, principal, issue_id)
    row = (await db.execute(_list_select().where(CivicIssue.id == issue.id))).one()
    report_rows = await reports.fetch_report_rows(db, Report.issue_id == issue.id)
    return IssueDetail(
        **_list_item(storage, row).model_dump(exclude={"priority"}),
        priority=priority_detail_out(issue),
        reports=await reports.staff_views(
            db, storage, report_rows, with_contact=principal.has(Permission.USER_MANAGE)
        ),
        timeline=await _timeline(db, issue.id),
        allowed_transitions=await allowed_transitions(db, principal, issue),
    )
