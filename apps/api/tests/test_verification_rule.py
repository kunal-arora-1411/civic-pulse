"""The default verification rule (FR-073) as a plain table."""

from __future__ import annotations

import pytest

from app.domains.operations.models import VerificationOutcome as V
from app.domains.operations.states import Decision, decide

R, U = V.RESOLVED, V.UNRESOLVED


@pytest.mark.parametrize(
    ("outcomes", "requires_approval", "required", "expected"),
    [
        ([], False, 2, Decision.WAIT),
        ([R], False, 2, Decision.WAIT),
        ([R, R], False, 2, Decision.RESOLVE),
        ([R, R, R], False, 2, Decision.RESOLVE),
        ([U], False, 2, Decision.SEND_BACK),
        ([R, R, U], False, 2, Decision.SEND_BACK),
        ([R, R], True, 2, Decision.WAIT),
        ([U], True, 2, Decision.SEND_BACK),
        ([R], False, 1, Decision.RESOLVE),
        ([], False, 0, Decision.WAIT),
    ],
)
def test_decide(
    outcomes: list[V], requires_approval: bool, required: int, expected: Decision
) -> None:
    assert (
        decide(outcomes, requires_approval=requires_approval, confirmations_required=required)
        == expected
    )
