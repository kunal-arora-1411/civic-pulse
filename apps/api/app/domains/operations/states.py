"""Pure rules: the work-order state machine and the default verification
rule (FR-073). No I/O, so both are tested as plain tables."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from app.domains.operations.models import VerificationOutcome
from app.domains.operations.models import WorkOrderState as S


class Action(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"
    START = "start"
    PROGRESS = "progress"
    REQUEST_CLOSURE = "request_closure"
    APPROVE = "approve"  # the supervisor approved the closure
    REJECT = "reject"  # closure rejected (supervisor or citizen)
    CANCEL = "cancel"  # the issue was reassigned


_OPEN = (S.PENDING_ACCEPTANCE, S.ACCEPTED, S.IN_PROGRESS, S.COMPLETION_REQUESTED)

# (state, action) -> next state. docs/api/phase-3-contract.md §3.
_NEXT: dict[tuple[S, Action], S] = {
    (S.PENDING_ACCEPTANCE, Action.ACCEPT): S.ACCEPTED,
    (S.PENDING_ACCEPTANCE, Action.DECLINE): S.DECLINED,
    (S.ACCEPTED, Action.DECLINE): S.DECLINED,
    (S.ACCEPTED, Action.START): S.IN_PROGRESS,
    (S.ACCEPTED, Action.PROGRESS): S.ACCEPTED,
    (S.IN_PROGRESS, Action.PROGRESS): S.IN_PROGRESS,
    (S.IN_PROGRESS, Action.REQUEST_CLOSURE): S.COMPLETION_REQUESTED,
    (S.COMPLETION_REQUESTED, Action.APPROVE): S.DONE,
    (S.COMPLETION_REQUESTED, Action.REJECT): S.IN_PROGRESS,
    **{(state, Action.CANCEL): S.CANCELLED for state in _OPEN},
}


def next_state(state: S, action: Action) -> S | None:
    """The state after `action`, or None when it isn't allowed from `state`."""
    return _NEXT.get((state, action))


class Decision(StrEnum):
    WAIT = "wait"  # nothing changes yet
    RESOLVE = "resolve"  # pending_verification -> resolved
    SEND_BACK = "send_back"  # an eligible citizen says it isn't fixed


def decide(
    outcomes: Iterable[VerificationOutcome],
    *,
    requires_approval: bool,
    confirmations_required: int,
) -> Decision:
    """The default verification rule (PRD FR-073), applied after each answer.

    `outcomes` holds one answer per distinct eligible citizen for the current
    closure round. C3.1's configurable rules engine replaces this function;
    the callers and the state changes stay.
    """
    # TODO(you): implement the FR-073 default rule. See the request below.
    raise NotImplementedError
