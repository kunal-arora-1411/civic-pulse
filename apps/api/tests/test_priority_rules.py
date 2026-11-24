"""Severity and priority rules as pure functions (contract E and F)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.domains.config.schemas import PriorityBands, PriorityConfig
from app.domains.priority.rules import (
    PriorityBand,
    PriorityInputs,
    SeverityInputs,
    SeverityLevel,
    SeverityRules,
    band_for,
    compute_priority,
    compute_severity,
    reporters_factor,
)

L = SeverityLevel
RULES = SeverityRules.model_validate(
    {
        "base": "medium",
        "field_rules": [
            {"field": "size", "equals": "large", "set": "high"},
            {"field": "size", "equals": "small", "set": "low"},
            {"field": "cover_missing", "equals": True, "set": "critical"},
        ],
        "near_places": [
            {"kinds": ["school", "hospital"], "within_m": 150, "raise_by": 1},
            {"kinds": ["school"], "within_m": 50, "raise_by": 2},
        ],
        "report_count_raise": [
            {"unique_reporters_gte": 5, "raise_by": 1},
            {"unique_reporters_gte": 20, "raise_by": 2},
        ],
    }
)


def severity(
    details: list[dict] | None = None,
    places: dict[str, float] | None = None,
    reporters: int = 1,
    rules: SeverityRules = RULES,
) -> SeverityLevel:
    inputs = SeverityInputs(
        details=details or [{}], nearest_place_m=places or {}, unique_reporters=reporters
    )
    return compute_severity(rules, inputs).level


# --- severity -----------------------------------------------------------------------------


def test_base_level_without_matching_rules() -> None:
    assert severity() is L.MEDIUM
    assert severity(rules=SeverityRules()) is L.MEDIUM
    assert severity(rules=SeverityRules(base=L.LOW)) is L.LOW


def test_field_rules_replace_the_base_and_the_highest_wins() -> None:
    assert severity([{"size": "large"}]) is L.HIGH
    assert severity([{"size": "small"}]) is L.LOW  # "set" can lower it too
    # Two reports disagree: the highest matching rule wins.
    assert severity([{"size": "small"}, {"size": "large"}]) is L.HIGH
    assert severity([{"size": "large", "cover_missing": True}]) is L.CRITICAL
    assert severity([{"size": "enormous"}]) is L.MEDIUM


def test_booleans_only_match_booleans() -> None:
    assert severity([{"cover_missing": 1}]) is L.MEDIUM
    assert severity([{"cover_missing": False}]) is L.MEDIUM
    rules = SeverityRules.model_validate(
        {"field_rules": [{"field": "lights_out", "equals": 1, "set": "high"}]}
    )
    assert severity([{"lights_out": True}], rules=rules) is L.MEDIUM
    assert severity([{"lights_out": 1}], rules=rules) is L.HIGH


def test_near_places_raise_by_the_largest_matching_tier() -> None:
    assert severity(places={"hospital": 150}) is L.HIGH  # within is inclusive
    assert severity(places={"hospital": 151}) is L.MEDIUM
    assert severity(places={"school": 40}) is L.CRITICAL  # the 50 m tier: +2, not +3
    assert severity(places={"market": 10}) is L.MEDIUM


def test_reporter_raises_use_the_largest_tier_and_add_to_place_raises() -> None:
    assert severity(reporters=4) is L.MEDIUM
    assert severity(reporters=5) is L.HIGH
    assert severity(reporters=20) is L.CRITICAL
    assert severity(places={"hospital": 100}, reporters=5) is L.CRITICAL


def test_raises_are_capped_at_critical_and_explained() -> None:
    inputs = SeverityInputs(
        details=[{"size": "large"}], nearest_place_m={"school": 20}, unique_reporters=25
    )
    result = compute_severity(RULES, inputs)
    assert result.level is L.CRITICAL
    assert result.steps == [
        "base medium",
        "size = large sets high",
        "school 20 m away raises 2",
        "25 reporters raise 2",
        "capped at critical",
    ]
    assert result.reason.endswith("-> critical")


@pytest.mark.parametrize(
    "rules",
    [
        {"base": "severe"},
        {"field_rules": [{"field": "Size", "equals": "x", "set": "high"}]},
        {"near_places": [{"kinds": ["school", "school"], "within_m": 10}]},
        {"near_places": [{"kinds": ["zoo"], "within_m": 10}]},
        {"near_places": [{"kinds": ["school"], "within_m": 0}]},
        {"report_count_raise": [{"unique_reporters_gte": 0}]},
        {"report_count_raise": [{"unique_reporters_gte": 3, "raise_by": 9}]},
        {"surprise": 1},
    ],
)
def test_invalid_rules_are_rejected(rules: dict) -> None:
    with pytest.raises(ValidationError):
        SeverityRules.model_validate(rules)


# --- priority -----------------------------------------------------------------------------

DEFAULT = PriorityConfig()


def priority(**overrides: object) -> PriorityInputs:
    values: dict = {
        "severity": L.MEDIUM,
        "unique_reporters": 1,
        "age_days": 0.0,
        "recurrence": 0,
        "near_place": False,
    }
    return PriorityInputs(**{**values, **overrides})


def test_priority_adds_weighted_factors() -> None:
    result = compute_priority(
        DEFAULT,
        priority(severity=L.HIGH, unique_reporters=3, age_days=6, recurrence=1, near_place=True),
    )
    expected = 40 * 0.75 + 20 * math.log(4) / math.log(11) + 15 * 6 / 30 + 15 * 1 / 3 + 10 * 1
    assert result.score == pytest.approx(expected, abs=0.01)
    assert result.band is PriorityBand.MEDIUM  # 59.56, just under the high band
    by_name = {f.factor: f for f in result.factors}
    assert by_name["severity"].value == "high"
    assert by_name["severity"].points == 30.0
    assert by_name["near_places"].value is True
    assert by_name["age"].normalized == pytest.approx(0.2)
    assert result.factors[0].explanation_key == "priority.severity"
    # Sorted by points, descending.
    points = [f.points for f in result.factors]
    assert points == sorted(points, reverse=True)


def test_every_factor_saturates() -> None:
    result = compute_priority(
        DEFAULT,
        priority(
            severity=L.CRITICAL, unique_reporters=500, age_days=400, recurrence=9, near_place=True
        ),
    )
    assert result.score == 100.0
    assert all(f.normalized == 1.0 for f in result.factors)
    assert result.band is PriorityBand.CRITICAL


def test_reporter_volume_flattens_out() -> None:
    assert reporters_factor(0, 10) == 0.0
    assert reporters_factor(10, 10) == pytest.approx(1.0)
    assert reporters_factor(1000, 10) == 1.0
    # The second reporter adds far more than the ninth.
    assert reporters_factor(2, 10) - reporters_factor(1, 10) > 3 * (
        reporters_factor(9, 10) - reporters_factor(8, 10)
    )


def test_inactive_issues_score_zero() -> None:
    for status in ("rejected", "closed", "merged"):
        result = compute_priority(
            DEFAULT, priority(severity=L.CRITICAL, unique_reporters=50, inactive_status=status)
        )
        assert (result.score, result.band) == (0.0, PriorityBand.LOW)
        assert [f.as_json() for f in result.factors] == [
            {
                "factor": "status",
                "value": status,
                "normalized": 0.0,
                "points": 0.0,
                "explanation_key": "priority.inactive",
            }
        ]


def test_band_thresholds_are_inclusive() -> None:
    bands = PriorityBands()
    assert band_for(80, bands) is PriorityBand.CRITICAL
    assert band_for(79.99, bands) is PriorityBand.HIGH
    assert band_for(60, bands) is PriorityBand.HIGH
    assert band_for(59.99, bands) is PriorityBand.MEDIUM
    assert band_for(35, bands) is PriorityBand.MEDIUM
    assert band_for(34.99, bands) is PriorityBand.LOW
    assert band_for(0, bands) is PriorityBand.LOW


def test_priority_follows_the_tenant_config() -> None:
    config = PriorityConfig.model_validate(
        {
            "weights": {
                "severity": 100,
                "reporters": 0,
                "age": 0,
                "recurrence": 0,
                "near_places": 0,
            },
            "bands": {"critical": 90, "high": 50, "medium": 20},
        }
    )
    result = compute_priority(config, priority(severity=L.MEDIUM, unique_reporters=40))
    assert result.score == 40.0
    assert result.band is PriorityBand.MEDIUM
