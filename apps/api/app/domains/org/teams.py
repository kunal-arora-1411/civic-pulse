"""Teams: admin CRUD and which teams can take an issue (FR-061)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import PageParams, paginate, sort_clauses
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.org.models import (
    Department,
    Jurisdiction,
    Team,
    TeamCategory,
    TeamJurisdiction,
    TeamMember,
    TeamRole,
)
from app.domains.org.schemas import (
    DepartmentRef,
    EligibleTeam,
    Schedule,
    TeamCreate,
    TeamMemberIn,
    TeamMemberOut,
    TeamOut,
    TeamRef,
    TeamUpdate,
    UserRef,
)
from app.domains.rbac.models import UserRole
from app.domains.rbac.principal import Principal
from app.domains.rbac.roles import STAFF_ROLES
from app.domains.users.models import User

SORTS = {"name": Team.name, "created_at": Team.created_at}

# The ward and its ancestors, with how far up each is (0 = the ward).
_ANCESTORS_SQL = text(
    """
    WITH RECURSIVE up AS (
        SELECT id, parent_id, 0 AS depth FROM jurisdictions WHERE id = :ward
        UNION
        SELECT j.id, j.parent_id, up.depth + 1
        FROM jurisdictions AS j JOIN up ON j.id = up.parent_id
        WHERE up.depth < 20
    )
    SELECT id, depth FROM up
    """
).bindparams(bindparam("ward", type_=UUID(as_uuid=True)))


async def _members(
    db: AsyncSession, team_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TeamMemberOut]]:
    rows = await db.execute(
        select(TeamMember.team_id, TeamMember.team_role, User.id, User.display_name)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id.in_(team_ids))
        .order_by(TeamMember.team_role, User.display_name, User.id)
    )
    out: dict[uuid.UUID, list[TeamMemberOut]] = defaultdict(list)
    for team_id, role, user_id, name in rows:
        out[team_id].append(
            TeamMemberOut(user=UserRef(id=user_id, display_name=name), team_role=TeamRole(role))
        )
    return out


async def _links(
    db: AsyncSession, column: Any, team_column: Any, team_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for team_id, value in await db.execute(
        select(team_column, column).where(team_column.in_(team_ids)).order_by(column)
    ):
        out[team_id].append(value)
    return out


async def _to_out(db: AsyncSession, rows: list[tuple[Team, Department]]) -> list[TeamOut]:
    ids = [team.id for team, _ in rows]
    members = await _members(db, ids)
    areas = await _links(db, TeamJurisdiction.jurisdiction_id, TeamJurisdiction.team_id, ids)
    categories = await _links(db, TeamCategory.category_id, TeamCategory.team_id, ids)
    return [
        TeamOut(
            id=team.id,
            department=DepartmentRef(id=dept.id, code=dept.code, name=dept.name),
            name=team.name,
            is_active=team.is_active,
            members=members[team.id],
            jurisdiction_ids=areas[team.id],
            category_ids=categories[team.id],
            schedule=Schedule.model_validate(team.schedule) if team.schedule else None,
            created_at=team.created_at,
            updated_at=team.updated_at,
        )
        for team, dept in rows
    ]


def _select():
    return select(Team, Department).join(Department, Department.id == Team.department_id)


async def list_teams(
    db: AsyncSession,
    params: PageParams,
    *,
    department_id: uuid.UUID | None,
    is_active: bool | None,
    sort: str | None,
) -> tuple[list[TeamOut], int]:
    stmt = _select()
    if department_id is not None:
        stmt = stmt.where(Team.department_id == department_id)
    if is_active is not None:
        stmt = stmt.where(Team.is_active.is_(is_active))
    stmt = stmt.order_by(*sort_clauses(sort, SORTS, default="name", tiebreaker=Team.id))
    rows, total = await paginate(db, stmt, params)
    return await _to_out(db, [(r[0], r[1]) for r in rows]), total


async def get_team(db: AsyncSession, team_id: uuid.UUID) -> TeamOut:
    row = (await db.execute(_select().where(Team.id == team_id))).one_or_none()
    if row is None:
        raise NotFound()
    return (await _to_out(db, [(row[0], row[1])]))[0]


async def _missing(db: AsyncSession, column: Any, ids: list[uuid.UUID]) -> list[str]:
    if not ids:
        return []
    found = set(await db.scalars(select(column).where(column.in_(ids))))
    return [str(i) for i in ids if i not in found]


async def _check(
    db: AsyncSession,
    *,
    department_id: uuid.UUID | None = None,
    members: list[TeamMemberIn] | None = None,
    jurisdiction_ids: list[uuid.UUID] | None = None,
    category_ids: list[uuid.UUID] | None = None,
) -> None:
    """Everything referenced exists in this tenant (RLS hides other tenants),
    and members are active staff."""
    errors: list[dict[str, Any]] = []
    if department_id is not None and await _missing(db, Department.id, [department_id]):
        errors.append({"loc": ["body", "department_id"], "msg": "Unknown department."})
    if members:
        user_ids = [m.user_id for m in members]
        staff = set(
            await db.scalars(
                select(User.id)
                .join(UserRole, UserRole.user_id == User.id)
                .where(
                    User.id.in_(user_ids),
                    User.is_active.is_(True),
                    UserRole.role.in_(list(STAFF_ROLES)),
                )
            )
        )
        for index, user_id in enumerate(user_ids):
            if user_id not in staff:
                errors.append(
                    {
                        "loc": ["body", "members", index, "user_id"],
                        "msg": "Not an active staff user.",
                    }
                )
    for field, column, ids in (
        ("jurisdiction_ids", Jurisdiction.id, jurisdiction_ids),
        ("category_ids", Category.id, category_ids),
    ):
        for missing in await _missing(db, column, ids or []):
            errors.append({"loc": ["body", field], "msg": f"Unknown id {missing}."})
    if errors:
        raise ValidationFailed(details={"errors": errors})


async def _replace_links(
    db: AsyncSession,
    team: Team,
    *,
    members: list[TeamMemberIn] | None,
    jurisdiction_ids: list[uuid.UUID] | None,
    category_ids: list[uuid.UUID] | None,
) -> None:
    if members is not None:
        await db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
        db.add_all(
            TeamMember(
                tenant_id=team.tenant_id, team_id=team.id, user_id=m.user_id, team_role=m.team_role
            )
            for m in members
        )
    if jurisdiction_ids is not None:
        await db.execute(delete(TeamJurisdiction).where(TeamJurisdiction.team_id == team.id))
        db.add_all(
            TeamJurisdiction(tenant_id=team.tenant_id, team_id=team.id, jurisdiction_id=j)
            for j in jurisdiction_ids
        )
    if category_ids is not None:
        await db.execute(delete(TeamCategory).where(TeamCategory.team_id == team.id))
        db.add_all(
            TeamCategory(tenant_id=team.tenant_id, team_id=team.id, category_id=c)
            for c in category_ids
        )
    await db.flush()


async def _name_taken(
    db: AsyncSession, department_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> bool:
    stmt = select(Team.id).where(
        Team.department_id == department_id, func.lower(Team.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(Team.id != exclude)
    return await db.scalar(stmt) is not None


async def create_team(db: AsyncSession, actor: Principal, body: TeamCreate) -> TeamOut:
    assert actor.tenant_id is not None
    await _check(
        db,
        department_id=body.department_id,
        members=body.members,
        jurisdiction_ids=body.jurisdiction_ids,
        category_ids=body.category_ids,
    )
    if await _name_taken(db, body.department_id, body.name):
        raise Conflict("This department already has a team with that name.")
    team = Team(
        tenant_id=actor.tenant_id,
        department_id=body.department_id,
        name=body.name,
        schedule=body.schedule.model_dump(mode="json") if body.schedule else None,
    )
    db.add(team)
    await db.flush()
    await _replace_links(
        db,
        team,
        members=body.members,
        jurisdiction_ids=body.jurisdiction_ids,
        category_ids=body.category_ids,
    )
    out = await get_team(db, team.id)
    await audit.record(
        db,
        action="team.created",
        entity_type="team",
        entity_id=team.id,
        actor=actor,
        after=out.model_dump(mode="json"),
    )
    return out


async def update_team(
    db: AsyncSession, actor: Principal, team_id: uuid.UUID, body: TeamUpdate
) -> TeamOut:
    from app.domains.operations.models import OPEN_WORK_ORDER_STATES, IssueAssignment, WorkOrder

    team = await db.scalar(select(Team).where(Team.id == team_id).with_for_update())
    if team is None:
        raise NotFound()
    before = await get_team(db, team.id)
    await _check(
        db,
        members=body.members,
        jurisdiction_ids=body.jurisdiction_ids,
        category_ids=body.category_ids,
    )
    if body.name is not None and body.name != team.name:
        if await _name_taken(db, team.department_id, body.name, exclude=team.id):
            raise Conflict("This department already has a team with that name.")
        team.name = body.name
    if body.is_active is False and team.is_active:
        open_work = await db.scalar(
            select(func.count())
            .select_from(WorkOrder)
            .join(IssueAssignment, IssueAssignment.id == WorkOrder.assignment_id)
            .where(IssueAssignment.team_id == team.id, WorkOrder.state.in_(OPEN_WORK_ORDER_STATES))
        )
        if open_work:
            raise Conflict(
                "Reassign this team's open work orders first.",
                code="team_has_open_work",
                details={"open_work_orders": open_work},
            )
    if body.is_active is not None:
        team.is_active = body.is_active
    if "schedule" in body.model_fields_set:
        team.schedule = body.schedule.model_dump(mode="json") if body.schedule else None
    await _replace_links(
        db,
        team,
        members=body.members,
        jurisdiction_ids=body.jurisdiction_ids,
        category_ids=body.category_ids,
    )
    db.expire(team, ["updated_at"])
    out = await get_team(db, team.id)
    await audit.record(
        db,
        action="team.updated",
        entity_type="team",
        entity_id=team.id,
        actor=actor,
        before=before.model_dump(mode="json"),
        after=out.model_dump(mode="json"),
    )
    return out


async def coverage_depth(
    db: AsyncSession, category_id: uuid.UUID, ward_id: uuid.UUID | None
) -> dict[uuid.UUID, int]:
    """Active teams that handle `category_id` and cover `ward_id`, each with
    how far above the ward its nearest covering jurisdiction is (0 = the
    ward itself). An issue with no ward has no eligible team."""
    if ward_id is None:
        return {}
    ancestors = {row[0]: row[1] for row in await db.execute(_ANCESTORS_SQL, {"ward": ward_id})}
    if not ancestors:
        return {}
    rows = await db.execute(
        select(TeamJurisdiction.team_id, TeamJurisdiction.jurisdiction_id)
        .join(Team, Team.id == TeamJurisdiction.team_id)
        .join(TeamCategory, TeamCategory.team_id == Team.id)
        .where(
            Team.is_active.is_(True),
            TeamCategory.category_id == category_id,
            TeamJurisdiction.jurisdiction_id.in_(list(ancestors)),
        )
    )
    depth: dict[uuid.UUID, int] = {}
    for team_id, jurisdiction_id in rows:
        d = ancestors[jurisdiction_id]
        depth[team_id] = min(d, depth.get(team_id, d))
    return depth


async def eligible_teams(
    db: AsyncSession, category_id: uuid.UUID, ward_id: uuid.UUID | None
) -> list[EligibleTeam]:
    """Most local first, then by name."""
    depth = await coverage_depth(db, category_id, ward_id)
    if not depth:
        return []
    rows = list((await db.execute(_select().where(Team.id.in_(list(depth))))).all())
    rows.sort(key=lambda r: (depth[r[0].id], r[0].name.lower(), str(r[0].id)))
    members = await _members(db, [r[0].id for r in rows])
    return [
        EligibleTeam(
            team=TeamRef(id=team.id, name=team.name),
            department=DepartmentRef(id=dept.id, code=dept.code, name=dept.name),
            members=members[team.id],
        )
        for team, dept in rows
    ]
