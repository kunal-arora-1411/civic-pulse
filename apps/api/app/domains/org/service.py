from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.core.pagination import PageParams, paginate, sort_clauses
from app.domains.audit import service as audit
from app.domains.org.models import Department, Jurisdiction, JurisdictionKind
from app.domains.org.schemas import DepartmentCreate, DepartmentOut, JurisdictionOut
from app.domains.rbac.principal import Principal

DEPARTMENT_SORTS = {
    "name": Department.name,
    "code": Department.code,
    "created_at": Department.created_at,
}
JURISDICTION_SORTS = {"name": Jurisdiction.name, "code": Jurisdiction.code}


async def list_departments(
    db: AsyncSession, params: PageParams, *, is_active: bool | None, sort: str | None
) -> tuple[list[DepartmentOut], int]:
    stmt = select(Department)
    if is_active is not None:
        stmt = stmt.where(Department.is_active.is_(is_active))
    stmt = stmt.order_by(
        *sort_clauses(sort, DEPARTMENT_SORTS, default="name", tiebreaker=Department.id)
    )
    rows, total = await paginate(db, stmt, params)
    return [DepartmentOut.model_validate(row[0]) for row in rows], total


async def create_department(
    db: AsyncSession, actor: Principal, body: DepartmentCreate
) -> DepartmentOut:
    assert actor.tenant_id is not None
    exists = await db.scalar(select(Department.id).where(Department.code == body.code))
    if exists is not None:
        raise Conflict("A department with this code already exists.", details={"code": body.code})
    department = Department(tenant_id=actor.tenant_id, name=body.name, code=body.code)
    db.add(department)
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race with a concurrent create
        raise Conflict("A department with this code already exists.") from exc
    out = DepartmentOut.model_validate(department)
    await audit.record(
        db,
        action="department.created",
        entity_type="department",
        entity_id=department.id,
        actor=actor,
        after=out.model_dump(mode="json"),
    )
    return out


async def list_jurisdictions(
    db: AsyncSession,
    params: PageParams,
    *,
    kind: JurisdictionKind | None,
    parent_id: uuid.UUID | None,
    include_geometry: bool,
    sort: str | None,
) -> tuple[list[JurisdictionOut], int]:
    geometry = func.ST_AsGeoJSON(Jurisdiction.geom, 6) if include_geometry else None
    columns = [
        Jurisdiction.id,
        Jurisdiction.parent_id,
        Jurisdiction.kind,
        Jurisdiction.name,
        Jurisdiction.code,
    ]
    stmt = select(*columns, geometry) if geometry is not None else select(*columns)
    if kind is not None:
        stmt = stmt.where(Jurisdiction.kind == kind)
    if parent_id is not None:
        stmt = stmt.where(Jurisdiction.parent_id == parent_id)
    stmt = stmt.order_by(
        *sort_clauses(sort, JURISDICTION_SORTS, default="code", tiebreaker=Jurisdiction.id)
    )
    rows, total = await paginate(db, stmt, params)
    items = [
        JurisdictionOut(
            id=row[0],
            parent_id=row[1],
            kind=row[2],
            name=row[3],
            code=row[4],
            geometry=json.loads(row[5]) if include_geometry and row[5] else None,
        )
        for row in rows
    ]
    return items, total
