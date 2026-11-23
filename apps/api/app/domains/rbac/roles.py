"""Role names. Kept apart from permissions so models can import them cheaply."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    CITIZEN = "citizen"
    COMMUNITY_CONTRIBUTOR = "community_contributor"
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    FIELD_WORKER = "field_worker"
    MUNICIPAL_ADMIN = "municipal_admin"
    PLATFORM_ADMIN = "platform_admin"


PUBLIC_ROLES: frozenset[Role] = frozenset({Role.CITIZEN, Role.COMMUNITY_CONTRIBUTOR})
STAFF_ROLES: frozenset[Role] = frozenset(Role) - PUBLIC_ROLES
