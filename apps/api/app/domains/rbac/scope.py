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
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, bindparam, false, or_, text, true
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


# A subcategory without a department of its own inherits its parent's.
_DEPARTMENT_CATEGORIES_SQL = text(
    """
    SELECT c.id
    FROM categories AS c
    LEFT JOIN categories AS p ON p.id = c.parent_id
    WHERE coalesce(c.default_department_id, p.default_department_id) = ANY(:departments)
    """
).bindparams(bindparam("departments", type_=ARRAY(UUID(as_uuid=True))))


async def department_categories(
    session: AsyncSession, departments: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Categories whose default department is one of `departments`."""
    department_list = list(set(departments))
    if not department_list:
        return set()
    rows = await session.execute(_DEPARTMENT_CATEGORIES_SQL, {"departments": department_list})
    return {row[0] for row in rows}


@dataclass(frozen=True, slots=True)
class AccessRule:
    """What one role grant covers: wards and categories (None: all)."""

    wards: frozenset[uuid.UUID] | None
    categories: frozenset[uuid.UUID] | None

    def allows(self, ward_id: uuid.UUID | None, category_id: uuid.UUID | None) -> bool:
        if self.wards is not None and ward_id not in self.wards:
            return False
        return self.categories is None or category_id in self.categories


# None: the whole tenant. A tuple: the union of its rules (empty: nothing).
IssueAccess = tuple[AccessRule, ...] | None


async def issue_access(
    session: AsyncSession, principal: Principal, permission: Permission
) -> IssueAccess:
    """Which issues the caller may act on with `permission`.

    Each grant is its own rule (jurisdiction AND department), and the rules
    are OR-ed, so a ward-scoped operator who is also a Roads supervisor
    city-wide sees everything in the ward plus Roads issues everywhere.
    A grant with a department covers the categories whose default
    department it is; an issue with no category is only visible to grants
    without a department.
    """
    rules: list[AccessRule] = []
    for grant in principal.grants_for(permission):
        wards = (
            None
            if grant.jurisdiction_id is None
            else frozenset(await jurisdiction_subtree(session, [grant.jurisdiction_id]))
        )
        categories = (
            None
            if grant.department_id is None
            else frozenset(await department_categories(session, [grant.department_id]))
        )
        if wards is None and categories is None:
            return None
        rules.append(AccessRule(wards, categories))
    return tuple(rules)


def access_allows(
    access: IssueAccess, ward_id: uuid.UUID | None, category_id: uuid.UUID | None
) -> bool:
    if access is None:
        return True
    return any(rule.allows(ward_id, category_id) for rule in access)


def access_filter(
    ward: ColumnElement[uuid.UUID] | InstrumentedAttribute[uuid.UUID | None],
    category: ColumnElement[uuid.UUID] | InstrumentedAttribute[uuid.UUID | None],
    access: IssueAccess,
) -> ColumnElement[bool]:
    """A WHERE clause restricting rows to an `issue_access` result."""
    if access is None:
        return true()
    clauses: list[ColumnElement[bool]] = []
    for rule in access:
        parts: list[ColumnElement[bool]] = []
        for column, ids in ((ward, rule.wards), (category, rule.categories)):
            if ids is not None:
                parts.append(column.in_(ids) if ids else false())
        clauses.append(and_(*parts))
    return or_(*clauses) if clauses else false()


def access_sql(
    access: IssueAccess, ward: str, category: str, params: dict[str, object], prefix: str = "acc"
) -> str:
    """`access_filter` as a raw SQL fragment, adding its bound values to
    `params`. Column names are trusted; IDs are always bound."""
    if access is None:
        return "TRUE"
    clauses: list[str] = []
    for n, rule in enumerate(access):
        parts: list[str] = []
        for column, ids, tag in ((ward, rule.wards, "w"), (category, rule.categories, "c")):
            if ids is not None:
                key = f"{prefix}_{tag}{n}"
                params[key] = list(ids)
                parts.append(f"{column} = ANY(:{key})")
        clauses.append("(" + (" AND ".join(parts) or "TRUE") + ")")
    return "(" + " OR ".join(clauses) + ")" if clauses else "FALSE"


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
