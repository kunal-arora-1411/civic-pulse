"""The pure matcher: signals, the combined score, and the decision at every
threshold edge (contract D.2)."""

from __future__ import annotations

import math

import pytest

from app.domains.config.schemas import MatchingConfig, MatchingWeights
from app.domains.matching.scoring import (
    CATEGORY_SAME,
    CATEGORY_SIBLING,
    Measurements,
    Outcome,
    VisualReason,
    combined_score,
    decide,
    geo_signal,
    signals_for,
    signals_json,
    time_signal,
    visual_signal,
)

DEFAULT = MatchingConfig()
# With all the weight on one signal the score *is* that signal, which puts
# a candidate exactly on a threshold without floating-point guesswork.
VISUAL_ONLY = MatchingConfig(weights=MatchingWeights(geo=0, visual=1, category=0, time=0))
GEO_ONLY = MatchingConfig(weights=MatchingWeights(geo=1, visual=0, category=0, time=0))


def measured(
    *,
    distance_m: float = 0.0,
    radius_m: float = 30.0,
    age_days: float = 0.0,
    window_days: float = 30.0,
    category: float = CATEGORY_SAME,
    cosine: float | None = None,
    phash: int | None = None,
    reason: VisualReason | None = None,
) -> Measurements:
    return Measurements(
        distance_m=distance_m,
        radius_m=radius_m,
        age_days=age_days,
        window_days=window_days,
        category=category,
        best_cosine=cosine,
        min_phash_distance=phash,
        visual_reason=reason,
    )


def outcome(
    m: Measurements, config: MatchingConfig = DEFAULT, *, fallback: bool = False
) -> Outcome:
    return decide([("issue", m)], config, fallback=fallback).outcome


# --- signals ------------------------------------------------------------------------------


def test_geo_and_time_decay_exponentially() -> None:
    assert geo_signal(0, 30) == 1.0
    assert geo_signal(30, 30) == pytest.approx(math.exp(-1))
    assert geo_signal(18.4, 30) == pytest.approx(0.54154, abs=1e-5)
    assert time_signal(0, 30) == 1.0
    assert time_signal(2.1, 30) == pytest.approx(0.9324, abs=1e-4)
    assert time_signal(-1, 30) == 1.0  # a clock skew never boosts the signal


def test_visual_is_the_clamped_cosine_unless_the_photo_is_the_same() -> None:
    assert visual_signal(0.91, 20) == (0.91, False)
    assert visual_signal(-0.2, None) == (0.0, False)
    assert visual_signal(1.0000002, None) == (1.0, False)
    assert visual_signal(None, None) == (None, False)
    # pHash within 6 bits: the same photo, whatever the cosine says.
    assert visual_signal(0.3, 6) == (1.0, True)
    assert visual_signal(0.3, 7) == (0.3, False)
    assert visual_signal(None, 0) == (1.0, True)


def test_score_renormalises_without_the_visual_signal() -> None:
    near = signals_for(measured(cosine=None, reason=VisualReason.NO_PHOTOS), fallback=False)
    assert near.visual is None
    assert near.reason is VisualReason.NO_PHOTOS
    assert combined_score(near, DEFAULT) == pytest.approx(1.0)

    s = signals_for(measured(distance_m=30, age_days=30, category=CATEGORY_SIBLING), fallback=False)
    expected = (0.4 * math.exp(-1) + 0.1 * 0.5 + 0.1 * math.exp(-1)) / 0.6
    assert combined_score(s, DEFAULT) == pytest.approx(expected)


def test_score_uses_every_weight_with_a_visual_signal() -> None:
    s = signals_for(measured(distance_m=18.4, age_days=2.1, cosine=0.91), fallback=False)
    expected = 0.4 * math.exp(-18.4 / 30) + 0.4 * 0.91 + 0.1 * 1.0 + 0.1 * math.exp(-2.1 / 30)
    assert combined_score(s, DEFAULT) == pytest.approx(expected)


def test_a_candidate_without_photos_says_so() -> None:
    s = signals_for(measured(cosine=None), fallback=False)
    assert s.reason is VisualReason.CANDIDATE_NO_PHOTOS


# --- decision edges ------------------------------------------------------------------------


def test_auto_link_threshold_is_inclusive() -> None:
    assert outcome(measured(cosine=0.85), VISUAL_ONLY) is Outcome.AUTO_LINK
    assert outcome(measured(cosine=0.8499999), VISUAL_ONLY) is Outcome.REVIEW


def test_review_threshold_is_inclusive() -> None:
    # Score = visual here, and visual below visual_min can't auto-link.
    assert outcome(measured(cosine=0.60), VISUAL_ONLY) is Outcome.REVIEW
    assert outcome(measured(cosine=0.5999999), VISUAL_ONLY) is Outcome.NEW_ISSUE


def test_visual_minimum_is_inclusive_for_auto_link() -> None:
    # Score = geo = 1.0 here, so only the visual check decides.
    assert outcome(measured(cosine=0.80), GEO_ONLY) is Outcome.AUTO_LINK
    # A high score that fails the visual check goes to review, never new.
    assert outcome(measured(cosine=0.7999999), GEO_ONLY) is Outcome.REVIEW


def test_never_auto_link_on_distance_alone() -> None:
    # Same spot, same category, just reported: a perfect score, no photos.
    same_spot = measured(cosine=None, reason=VisualReason.NO_PHOTOS)
    decision = decide([("issue", same_spot)], DEFAULT, fallback=False)
    assert decision.ranked[0].score == pytest.approx(1.0)
    assert decision.outcome is Outcome.REVIEW
    # Visually different: never linked. On the very spot a person looks at
    # it; ten metres away it is simply a new issue.
    assert outcome(measured(cosine=0.05, age_days=3)) is Outcome.REVIEW
    assert outcome(measured(distance_m=10, cosine=0.05, age_days=3)) is Outcome.NEW_ISSUE


def test_outside_the_radius_never_auto_links() -> None:
    far = measured(distance_m=31, radius_m=30, cosine=1.0)
    assert outcome(far, VISUAL_ONLY) is Outcome.REVIEW
    edge = measured(distance_m=30, radius_m=30, cosine=1.0)
    assert outcome(edge, VISUAL_ONLY) is Outcome.AUTO_LINK


def test_auto_link_can_be_switched_off() -> None:
    off = MatchingConfig(auto_link_enabled=False)
    assert outcome(measured(cosine=1.0), off) is Outcome.REVIEW


def test_the_best_linkable_candidate_is_chosen() -> None:
    # "a" scores higher but has no photos; "b" is visually confirmed.
    decision = decide(
        [
            ("a", measured(distance_m=0, cosine=None)),
            ("b", measured(distance_m=3, cosine=0.95)),
            ("c", measured(distance_m=25, cosine=0.1)),
        ],
        DEFAULT,
        fallback=False,
    )
    assert decision.outcome is Outcome.AUTO_LINK
    assert decision.chosen is not None
    assert decision.chosen.key == "b"
    assert [s.key for s in decision.ranked] == ["a", "b", "c"]


def test_no_candidates_means_a_new_issue() -> None:
    decision = decide([], DEFAULT, fallback=False)
    assert (decision.outcome, decision.ranked, decision.chosen) == (Outcome.NEW_ISSUE, [], None)


# --- fallback (AI unavailable) ------------------------------------------------------------


def test_fallback_never_auto_links_and_reviews_from_point_four() -> None:
    identical = measured(cosine=1.0, phash=0)
    decision = decide([("issue", identical)], DEFAULT, fallback=True)
    assert decision.outcome is Outcome.REVIEW
    assert decision.ranked[0].signals.visual is None
    assert decision.ranked[0].signals.reason is VisualReason.AI_UNAVAILABLE

    # Score without visual = geo here (weights 1/0/0/0 -> geo only).
    geo_only = MatchingConfig(weights=MatchingWeights(geo=1, visual=0, category=0, time=0))
    at_edge = measured(distance_m=-30 * math.log(0.40))
    assert outcome(at_edge, geo_only, fallback=True) is Outcome.REVIEW
    below = measured(distance_m=-30 * math.log(0.3999))
    assert outcome(below, geo_only, fallback=True) is Outcome.NEW_ISSUE


def test_fallback_review_threshold_is_configurable() -> None:
    strict = MatchingConfig(fallback_review_threshold=0.99)
    assert outcome(measured(distance_m=5), strict, fallback=True) is Outcome.NEW_ISSUE


# --- the stored explanation ----------------------------------------------------------------


def test_signals_json_has_the_contract_shape() -> None:
    decision = decide(
        [("i", measured(distance_m=18.4, age_days=2.1, cosine=0.91))], DEFAULT, fallback=False
    )
    body = signals_json(decision.ranked[0], DEFAULT, fallback=False)
    assert body == {
        "distance_m": 18.4,
        "radius_m": 30.0,
        "geo": 0.5415,
        "visual": 0.91,
        "same_photo": False,
        "category": 1.0,
        "time": 0.9324,
        "age_days": 2.1,
        "weights": {"geo": 0.4, "visual": 0.4, "category": 0.1, "time": 0.1},
        "thresholds": {"auto": 0.85, "review": 0.6, "visual_min": 0.8},
        "reason": None,
    }
    fallback = decide([("i", measured())], DEFAULT, fallback=True)
    body = signals_json(fallback.ranked[0], DEFAULT, fallback=True)
    assert body["visual"] is None
    assert body["reason"] == "ai_unavailable"
    assert body["thresholds"]["fallback_review"] == 0.4
