"""The pure Phase 3 rules: work-order transitions and the FR-073 default
verification rule."""

from __future__ import annotations

import pytest

from app.domains.operations.models import VerificationOutcome as V
from app.domains.operations.models import WorkOrderState as S
from app.domains.operations.states import Action, Decision, decide, next_state


@pytest.mark.parametrize(
    ("state", "action", "expected"),
    [
        (S.PENDING_ACCEPTANCE, Action.ACCEPT, S.ACCEPTED),
        (S.PENDING_ACCEPTANCE, Action.START, None),
        (S.ACCEPTED, Action.START, S.IN_PROGRESS),
        (S.ACCEPTED, Action.DECLINE, S.DECLINED),
        (S.IN_PROGRESS, Action.DECLINE, None),
        (S.IN_PROGRESS, Action.REQUEST_CLOSURE, S.COMPLETION_REQUESTED),
        (S.ACCEPTED, Action.REQUEST_CLOSURE, None),
        (S.COMPLETION_REQUESTED, Action.APPROVE, S.DONE),
        (S.COMPLETION_REQUESTED, Action.REJECT, S.IN_PROGRESS),
        (S.COMPLETION_REQUESTED, Action.CANCEL, S.CANCELLED),
        (S.DONE, Action.CANCEL, None),
        (S.DECLINED, Action.ACCEPT, None),
    ],
)
def test_work_order_transitions(state: S, action: Action, expected: S | None) -> None:
    assert next_state(state, action) == expected


@pytest.mark.parametrize(
    ("outcomes", "requires_approval", "expected"),
    [
        ([], False, Decision.WAIT),
        ([V.RESOLVED], False, Decision.WAIT),  # one account never decides alone
        ([V.RESOLVED, V.RESOLVED], False, Decision.RESOLVE),
        ([V.RESOLVED, V.RESOLVED], True, Decision.WAIT),  # only a supervisor resolves
        ([V.UNRESOLVED], False, Decision.SEND_BACK),
        ([V.UNRESOLVED], True, Decision.SEND_BACK),
        ([V.RESOLVED, V.RESOLVED, V.UNRESOLVED], False, Decision.SEND_BACK),
    ],
)
def test_default_verification_rule(
    outcomes: list[V], requires_approval: bool, expected: Decision
) -> None:
    assert (
        decide(outcomes, requires_approval=requires_approval, confirmations_required=2) == expected
    )
