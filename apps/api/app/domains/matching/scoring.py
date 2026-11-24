"""Duplicate-match scoring and the decision rule (contract D.2), as pure
functions: no database, no clock, so every threshold edge can be tested.

The database side (app/domains/matching/service.py) gathers each
candidate's raw measurements; this module turns them into signals, a
combined score and a decision, and renders the signals JSON stored with
every match decision (D.3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domains.config.schemas import MatchingConfig

# A pHash Hamming distance this small means the same photo (recompressed,
# resized or re-uploaded), whatever the embeddings say.
SAME_PHOTO_MAX_DISTANCE = 6
CATEGORY_SAME = 1.0
CATEGORY_SIBLING = 0.5


class Outcome(StrEnum):
    AUTO_LINK = "auto_link"
    REVIEW = "review"
    NEW_ISSUE = "new_issue"


class VisualReason(StrEnum):
    """Why a candidate has no visual signal (null `reason` = it has one)."""

    AI_UNAVAILABLE = "ai_unavailable"  # embeddings missing: matched in fallback mode
    NO_PHOTOS = "no_photos"  # the new report has no photos
    CANDIDATE_NO_PHOTOS = "candidate_no_photos"  # nothing to compare on the issue's side


@dataclass(frozen=True, slots=True)
class Measurements:
    """What the database measured for one candidate issue."""

    distance_m: float
    radius_m: float
    age_days: float
    window_days: float
    category: float  # CATEGORY_SAME or CATEGORY_SIBLING
    best_cosine: float | None  # max over photo pairs; None when nothing to compare
    min_phash_distance: int | None
    visual_reason: VisualReason | None = None


@dataclass(frozen=True, slots=True)
class Signals:
    distance_m: float
    radius_m: float
    geo: float
    visual: float | None
    same_photo: bool
    category: float
    time: float
    age_days: float
    reason: VisualReason | None


@dataclass(frozen=True, slots=True)
class Scored[K]:
    key: K
    signals: Signals
    score: float


@dataclass(frozen=True, slots=True)
class Decision[K]:
    outcome: Outcome
    # Best first. `chosen` is the one to link to (auto-link only).
    ranked: list[Scored[K]]
    chosen: Scored[K] | None


def geo_signal(distance_m: float, radius_m: float) -> float:
    return math.exp(-max(0.0, distance_m) / radius_m)


def time_signal(age_days: float, window_days: float) -> float:
    return math.exp(-max(0.0, age_days) / window_days)


def visual_signal(
    best_cosine: float | None, min_phash_distance: int | None
) -> tuple[float | None, bool]:
    """(visual, same_photo). A near-identical pHash wins over the cosine."""
    if min_phash_distance is not None and min_phash_distance <= SAME_PHOTO_MAX_DISTANCE:
        return 1.0, True
    if best_cosine is None:
        return None, False
    return min(1.0, max(0.0, best_cosine)), False


def signals_for(measured: Measurements, *, fallback: bool) -> Signals:
    if fallback:
        visual, same_photo, reason = None, False, VisualReason.AI_UNAVAILABLE
    else:
        visual, same_photo = visual_signal(measured.best_cosine, measured.min_phash_distance)
        reason = measured.visual_reason if visual is None else None
        if visual is None and reason is None:
            reason = VisualReason.CANDIDATE_NO_PHOTOS
    return Signals(
        distance_m=measured.distance_m,
        radius_m=measured.radius_m,
        geo=geo_signal(measured.distance_m, measured.radius_m),
        visual=visual,
        same_photo=same_photo,
        category=measured.category,
        time=time_signal(measured.age_days, measured.window_days),
        age_days=measured.age_days,
        reason=reason,
    )


def combined_score(signals: Signals, config: MatchingConfig) -> float:
    """Weighted sum of the signals, re-normalised over the remaining
    weights when there is no visual signal."""
    w = config.weights
    parts = [(w.geo, signals.geo), (w.category, signals.category), (w.time, signals.time)]
    if signals.visual is not None:
        parts.append((w.visual, signals.visual))
    total_weight = sum(weight for weight, _ in parts)
    if total_weight <= 0:
        return 0.0
    score = sum(weight * value for weight, value in parts) / total_weight
    return min(1.0, max(0.0, score))


def can_auto_link(scored: Scored[Any], config: MatchingConfig) -> bool:
    """Auto-link needs a high score *and* strong visual evidence *and* the
    point inside the radius. Never on distance alone (AC-05)."""
    t = config.thresholds
    visual = scored.signals.visual
    return (
        config.auto_link_enabled
        and scored.score >= t.auto
        and visual is not None
        and visual >= t.visual_min
        and scored.signals.distance_m <= scored.signals.radius_m
    )


def decide[K](
    candidates: Sequence[tuple[K, Measurements]], config: MatchingConfig, *, fallback: bool
) -> Decision[K]:
    """Score every candidate and pick auto-link, review or new issue.

    * Auto-link: the best candidate that passes `can_auto_link`.
    * Review: the best score reaches the review threshold, or any score
      reaches the automatic one but failed the other checks.
    * Fallback (no visual signal at all, AI unavailable): never auto-link;
      review when any score reaches `fallback_review_threshold`.
    * Otherwise a new issue.
    """
    scored: list[Scored[K]] = []
    for key, measured in candidates:
        signals = signals_for(measured, fallback=fallback)
        scored.append(Scored(key=key, signals=signals, score=combined_score(signals, config)))
    ranked = sorted(scored, key=lambda s: (-s.score, s.signals.distance_m))
    if not ranked:
        return Decision(Outcome.NEW_ISSUE, ranked, None)
    best = ranked[0]
    if fallback:
        if best.score >= config.fallback_review_threshold:
            return Decision(Outcome.REVIEW, ranked, None)
        return Decision(Outcome.NEW_ISSUE, ranked, None)

    linkable = [s for s in ranked if can_auto_link(s, config)]
    if linkable:
        return Decision(Outcome.AUTO_LINK, ranked, linkable[0])
    if best.score >= config.thresholds.review or best.score >= config.thresholds.auto:
        return Decision(Outcome.REVIEW, ranked, None)
    return Decision(Outcome.NEW_ISSUE, ranked, None)


def signals_json(scored: Scored[Any], config: MatchingConfig, *, fallback: bool) -> dict[str, Any]:
    """The explanation stored with each match decision (contract D.3)."""
    s = scored.signals
    thresholds: dict[str, float] = {
        "auto": config.thresholds.auto,
        "review": config.thresholds.review,
        "visual_min": config.thresholds.visual_min,
    }
    if fallback:
        thresholds["fallback_review"] = config.fallback_review_threshold
    return {
        "distance_m": round(s.distance_m, 1),
        "radius_m": s.radius_m,
        "geo": round(s.geo, 4),
        "visual": None if s.visual is None else round(s.visual, 4),
        "same_photo": s.same_photo,
        "category": s.category,
        "time": round(s.time, 4),
        "age_days": round(s.age_days, 2),
        "weights": config.weights.model_dump(),
        "thresholds": thresholds,
        "reason": s.reason.value if s.reason else None,
    }
