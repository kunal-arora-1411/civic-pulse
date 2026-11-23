"""Permissions, and which roles grant them.

Permissions live in code, not in the database: they change with the code that
checks them, they are reviewed in pull requests, and there is no admin screen
that can quietly grant `audit:read` to everyone. Phase 0 only checks a few of
them; the rest are declared now so the frontend and later phases share one
vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from app.domains.rbac.roles import Role


class Permission(StrEnum):
    # Citizens
    REPORT_CREATE = "report:create"
    REPORT_READ_OWN = "report:read_own"
    ISSUE_COMMENT = "issue:comment"
    ISSUE_VERIFY = "issue:verify"
    # Verified community contributors
    ISSUE_CONFIRM = "issue:confirm"
    # Operations
    REPORT_READ = "report:read"
    ISSUE_READ = "issue:read"
    ISSUE_TRIAGE = "issue:triage"
    ISSUE_UPDATE = "issue:update"
    ISSUE_MERGE = "issue:merge"
    ISSUE_ASSIGN = "issue:assign"
    ISSUE_SET_PRIORITY = "issue:set_priority"
    ISSUE_APPROVE_CLOSURE = "issue:approve_closure"
    WORKORDER_READ_ASSIGNED = "workorder:read_assigned"
    WORKORDER_UPDATE = "workorder:update"
    EVIDENCE_UPLOAD = "evidence:upload"
    ANALYTICS_READ = "analytics:read"
    # Administration
    CONFIG_READ = "config:read"
    CONFIG_MANAGE = "config:manage"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    # Platform
    TENANT_MANAGE = "tenant:manage"


P = Permission

_CITIZEN = frozenset({P.REPORT_CREATE, P.REPORT_READ_OWN, P.ISSUE_COMMENT, P.ISSUE_VERIFY})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.CITIZEN: _CITIZEN,
    Role.COMMUNITY_CONTRIBUTOR: _CITIZEN | {P.ISSUE_CONFIRM},
    Role.OPERATOR: frozenset(
        {
            P.REPORT_READ,
            P.ISSUE_READ,
            P.ISSUE_TRIAGE,
            P.ISSUE_UPDATE,
            P.ISSUE_MERGE,
            P.CONFIG_READ,
        }
    ),
    Role.SUPERVISOR: frozenset(
        {
            P.REPORT_READ,
            P.ISSUE_READ,
            P.ISSUE_UPDATE,
            P.ISSUE_ASSIGN,
            P.ISSUE_SET_PRIORITY,
            P.ISSUE_APPROVE_CLOSURE,
            P.ANALYTICS_READ,
            P.CONFIG_READ,
        }
    ),
    Role.FIELD_WORKER: frozenset(
        {P.WORKORDER_READ_ASSIGNED, P.WORKORDER_UPDATE, P.EVIDENCE_UPLOAD}
    ),
    Role.MUNICIPAL_ADMIN: frozenset(
        {
            P.REPORT_READ,
            P.ISSUE_READ,
            P.ANALYTICS_READ,
            P.CONFIG_READ,
            P.CONFIG_MANAGE,
            P.USER_MANAGE,
            P.AUDIT_READ,
        }
    ),
    # Deliberately no tenant data permissions: the PRD rules out routine
    # platform access to citizen content.
    Role.PLATFORM_ADMIN: frozenset({P.TENANT_MANAGE}),
}

PUBLIC_PERMISSIONS: frozenset[Permission] = (
    ROLE_PERMISSIONS[Role.CITIZEN] | ROLE_PERMISSIONS[Role.COMMUNITY_CONTRIBUTOR]
)
"""Permissions a non-staff user can hold. Everything else is a staff
permission, which REQUIRE_STAFF_MFA gates behind a verified second factor."""


def permissions_for(roles: Iterable[Role]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def is_staff_permission(permission: Permission) -> bool:
    return permission not in PUBLIC_PERMISSIONS
