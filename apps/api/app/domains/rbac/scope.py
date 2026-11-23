"""Department and jurisdiction scoping (PRD FR-006).

A role grant with no jurisdiction applies to the whole tenant. A grant scoped
to a jurisdiction covers that jurisdiction and everything beneath it: an
operator scoped to a zone sees all of the zone's wards. Scope functions
return None for "unrestricted" and a set of IDs otherwise; an empty set means
no access at all.

These queries run under RLS, so the tree walk can never step into another
tenant's jurisdictions even if a foreign ID is passed in.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import ColumnElement, bindparam, false, text, true
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

# UNION (not UNION ALL) de-duplicates as it goes, so a malformed cycle in the
# tree terminates instead of recursing forever.
_SUBTREE_SQL = text(
    """
    WITH RECURSIVE subtree AS (
        SELECT id FROM jurisdictions WHERE id = ANY(:roots)
        UNION
        SELECT child.id
        FROM jurisdictions AS child
        JOIN subtree ON child.parent_id = subtree.id
    )
    SELECT id FROM subtree
    """
).bindparams(bindparam("roots", type_=ARRAY(UUID(as_uuid=True))))


async def jurisdiction_subtree(session: AsyncSession, roots: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The given jurisdictions plus all of their descendants."""
    root_list = list(set(roots))
    if not root_list:
        return set()
    rows = await session.execute(_SUBTREE_SQL, {"roots": root_list})
    return {row[0] for row in rows}


async def accessible_jurisdiction_ids(
    session: AsyncSession, principal: Principal, permission: Permission
) -> set[uuid.UUID] | None:
    grants = principal.grants_for(permission)
    if not grants:
        return set()
    if any(grant.jurisdiction_id is None for grant in grants):
        return None
    return await jurisdiction_subtree(
        session, (g.jurisdiction_id for g in grants if g.jurisdiction_id is not None)
    )


def accessible_department_ids(
    principal: Principal, permission: Permission
) -> set[uuid.UUID] | None:
    grants = principal.grants_for(permission)
    if not grants:
        return set()
    if any(grant.department_id is None for grant in grants):
        return None
    return {g.department_id for g in grants if g.department_id is not None}


def scope_filter(
    column: ColumnElement[uuid.UUID] | InstrumentedAttribute[uuid.UUID | None],
    scope: set[uuid.UUID] | None,
) -> ColumnElement[bool]:
    """A WHERE clause restricting `column` to a scope from the functions above."""
    if scope is None:
        return true()
    if not scope:
        return false()
    return column.in_(scope)
