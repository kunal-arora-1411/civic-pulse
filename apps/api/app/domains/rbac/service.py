"""Validating role assignments made by tenant administrators."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.domains.org.models import Department, Jurisdiction
from app.domains.rbac.roles import PUBLIC_ROLES, Role
from app.domains.users.schemas import RoleAssignment


async def validate_assignments(
    db: AsyncSession, assignments: Sequence[RoleAssignment]
) -> list[RoleAssignment]:
    """Check and de-duplicate role assignments for the current tenant.

    Department and jurisdiction IDs are looked up under RLS, so another
    tenant's IDs are indistinguishable from IDs that don't exist.
    """
    errors: list[dict[str, object]] = []
    unique: dict[tuple[Role, uuid.UUID | None, uuid.UUID | None], RoleAssignment] = {}

    department_ids = {a.department_id for a in assignments if a.department_id}
    jurisdiction_ids = {a.jurisdiction_id for a in assignments if a.jurisdiction_id}
    known_departments = set(
        (await db.scalars(select(Department.id).where(Department.id.in_(department_ids)))).all()
        if department_ids
        else []
    )
    known_jurisdictions = set(
        (
            await db.scalars(select(Jurisdiction.id).where(Jurisdiction.id.in_(jurisdiction_ids)))
        ).all()
        if jurisdiction_ids
        else []
    )

    for index, assignment in enumerate(assignments):
        loc = ["body", "roles", index]
        if assignment.role is Role.PLATFORM_ADMIN:
            errors.append({"loc": [*loc, "role"], "msg": "This role can't be assigned here."})
        if assignment.role in PUBLIC_ROLES and (
            assignment.department_id or assignment.jurisdiction_id
        ):
            errors.append({"loc": loc, "msg": "Only staff roles can be scoped."})
        if assignment.department_id and assignment.department_id not in known_departments:
            errors.append({"loc": [*loc, "department_id"], "msg": "Unknown department."})
        if assignment.jurisdiction_id and assignment.jurisdiction_id not in known_jurisdictions:
            errors.append({"loc": [*loc, "jurisdiction_id"], "msg": "Unknown jurisdiction."})
        key = (assignment.role, assignment.department_id, assignment.jurisdiction_id)
        unique.setdefault(key, assignment)

    if errors:
        raise ValidationFailed("Some role assignments are invalid.", details={"errors": errors})
    return list(unique.values())
