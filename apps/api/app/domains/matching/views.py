"""Reading match decisions back for report and issue views."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.issues.models import CivicIssue
from app.domains.matching.models import Decision, Feedback, MatchDecision
from app.domains.matching.schemas import (
    CandidateIssueRef,
    DecisionActor,
    MatchDecisionOut,
    MatchSummary,
)
from app.domains.users.models import User

# Which decision explains where a report ended up: the link that was made,
# else the best-ranked candidate considered.
_DECIDING = case(
    (MatchDecision.decision.in_([Decision.AUTO_LINKED, Decision.CHOSEN_BY_REVIEWER]), 0),
    else_=1,
)


async def summaries(
    db: AsyncSession, report_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MatchSummary]:
    if not report_ids:
        return {}
    rows = await db.scalars(
        select(MatchDecision)
        .where(MatchDecision.report_id.in_(report_ids))
        .order_by(MatchDecision.report_id, _DECIDING, MatchDecision.rank)
    )
    out: dict[uuid.UUID, MatchSummary] = {}
    for row in rows:
        out.setdefault(
            row.report_id,
            MatchSummary(
                match_decision_id=row.id,
                decision=Decision(row.decision),
                score=row.score,
                signals=row.signals,
            ),
        )
    return out


def to_out(row: MatchDecision, reference: str, decider: str | None) -> MatchDecisionOut:
    return MatchDecisionOut(
        id=row.id,
        report_id=row.report_id,
        candidate_issue_id=row.candidate_issue_id,
        candidate_issue=CandidateIssueRef(id=row.candidate_issue_id, reference=reference),
        rank=row.rank,
        score=row.score,
        signals=row.signals,
        decision=Decision(row.decision),
        model_id=row.model_id,
        decided_by=DecisionActor(id=row.decided_by, display_name=decider)
        if row.decided_by
        else None,
        decided_at=row.decided_at,
        feedback=Feedback(row.feedback) if row.feedback else None,
        feedback_note=row.feedback_note,
        feedback_at=row.feedback_at,
    )


async def decisions(
    db: AsyncSession, report_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MatchDecisionOut]]:
    """Every decision for these reports, best-ranked first per report."""
    grouped: dict[uuid.UUID, list[MatchDecisionOut]] = defaultdict(list)
    if not report_ids:
        return grouped
    rows = await db.execute(
        select(MatchDecision, CivicIssue.reference, User.display_name)
        .join(CivicIssue, CivicIssue.id == MatchDecision.candidate_issue_id)
        .outerjoin(User, User.id == MatchDecision.decided_by)
        .where(MatchDecision.report_id.in_(report_ids))
        .order_by(MatchDecision.report_id, MatchDecision.rank)
    )
    for row, reference, decider in rows:
        grouped[row.report_id].append(to_out(row, reference, decider))
    return grouped
