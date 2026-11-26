"""Which notifications go out on which external channel, per person.

The in-app inbox always gets every notification; these choices only cover
email, SMS and Web Push. The matrix follows the PRD's event table (§15.1):
each kind can only go out on the channels listed for it there, and starts
switched on for all of them except review-task email, which would mail every
operator for every uncertain report.

Only choices a person saved are stored; everything else is the default here,
so a new kind or channel needs no data migration.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.domains.notifications.models import (
    DeliveryChannel,
    NotificationKind,
    NotificationPreference,
)
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

K = NotificationKind
C = DeliveryChannel

# kind -> {channel: on by default}
DEFAULTS: dict[NotificationKind, dict[DeliveryChannel, bool]] = {
    K.REPORT_NEW_ISSUE: {C.EMAIL: True, C.SMS: True},
    K.REPORT_LINKED: {C.PUSH: True, C.SMS: True},
    K.ISSUE_STATUS: {C.PUSH: True, C.EMAIL: True, C.SMS: True},
    K.REVIEW_TASK: {C.PUSH: True, C.EMAIL: False},
    K.ASSIGNMENT: {C.PUSH: True, C.EMAIL: True},
    K.SLA_BREACH: {C.PUSH: True, C.EMAIL: True},
}

CITIZEN_KINDS = (K.REPORT_NEW_ISSUE, K.REPORT_LINKED, K.ISSUE_STATUS)
STAFF_KINDS = (K.REVIEW_TASK, K.ASSIGNMENT, K.SLA_BREACH)


def allowed(kind: str, channel: str) -> bool:
    try:
        return DeliveryChannel(channel) in DEFAULTS[NotificationKind(kind)]
    except ValueError:
        return False


def default(kind: str, channel: str) -> bool:
    try:
        return DEFAULTS[NotificationKind(kind)].get(DeliveryChannel(channel), False)
    except ValueError:
        return False


def kinds_for(principal: Principal) -> list[NotificationKind]:
    """The kinds this person can receive, so the settings page offers only those."""
    kinds: list[NotificationKind] = []
    if principal.has(Permission.REPORT_CREATE):
        kinds += CITIZEN_KINDS
    if principal.has(Permission.ISSUE_READ):
        kinds += STAFF_KINDS
    return kinds


async def saved(
    db: AsyncSession | AsyncConnection, user_id: uuid.UUID
) -> dict[tuple[str, str], bool]:
    rows = await db.execute(
        select(
            NotificationPreference.kind,
            NotificationPreference.channel,
            NotificationPreference.enabled,
        ).where(NotificationPreference.user_id == user_id)
    )
    return {(kind, channel): enabled for kind, channel, enabled in rows.all()}


async def enabled(
    db: AsyncSession | AsyncConnection, user_id: uuid.UUID, kind: str, channel: str
) -> bool:
    """Whether this person wants this kind on this channel."""
    if not allowed(kind, channel):
        return False
    choice = (await saved(db, user_id)).get((kind, channel))
    return default(kind, channel) if choice is None else choice


def effective(
    kinds: Iterable[NotificationKind], choices: dict[tuple[str, str], bool]
) -> list[tuple[NotificationKind, DeliveryChannel, bool]]:
    out: list[tuple[NotificationKind, DeliveryChannel, bool]] = []
    for kind in kinds:
        for channel, on in DEFAULTS[kind].items():
            out.append((kind, channel, choices.get((kind.value, channel.value), on)))
    return out
