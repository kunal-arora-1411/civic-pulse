"""Severity (FR-038) and priority (FR-039 to FR-044) as pure functions.

Rules only, no learning: the inputs are facts the database already knows
(report answers, nearby places, distinct reporters, age, recurrence), and
every result carries its own explanation. app/domains/priority/service.py
gathers the inputs and stores the results.

Severity, from a category's `severity_rules`:

1. Start from `base`.
2. Field rules compare a report answer with a value. When several match
   (on any of the issue's reports), the highest `set` level wins and
   replaces the base.
3. Raises are added on top: the largest matching `near_places` raise plus
   the largest matching `report_count_raise`. Within one group the rules
   are tiers, so only the biggest one that matches counts. The result is
   capped at `critical`.

Priority, from the tenant's priority config: five factors, each scaled to
[0, 1] and multiplied by its weight; the score is their sum (0 to 100)
and the band comes from the thresholds. Rejected, closed and merged issues
score 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.config.schemas import PriorityBands, PriorityConfig

# Contract F: a place of interest this close counts for the priority factor.
NEAR_PLACES_RADIUS_M = 150


class SeverityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PriorityBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PlaceKind(StrEnum):
    SCHOOL = "school"
    HOSPITAL = "hospital"
    BUS_STOP = "bus_stop"
    MARKET = "market"
    OTHER = "other"


LEVELS: tuple[SeverityLevel, ...] = tuple(SeverityLevel)
BAND_ORDER: dict[str, int] = {band.value: rank for rank, band in enumerate(PriorityBand)}


def raise_level(level: SeverityLevel, steps: int) -> SeverityLevel:
    index = min(len(LEVELS) - 1, max(0, LEVELS.index(level) + steps))
    return LEVELS[index]


# --- the rules document stored on a category ------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldRule(_Strict):
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="A category field key.")
    equals: str | bool | int | float = Field(description="The answer that triggers the rule.")
    set: SeverityLevel


class NearPlacesRule(_Strict):
    kinds: list[PlaceKind] = Field(min_length=1, max_length=len(PlaceKind))
    within_m: int = Field(ge=1, le=5000)
    raise_by: int = Field(default=1, ge=1, le=3)


class ReporterRule(_Strict):
    unique_reporters_gte: int = Field(ge=1, le=100_000)
    raise_by: int = Field(default=1, ge=1, le=3)


class SeverityRules(_Strict):
    base: SeverityLevel = SeverityLevel.MEDIUM
    field_rules: list[FieldRule] = Field(default_factory=list, max_length=50)
    near_places: list[NearPlacesRule] = Field(default_factory=list, max_length=10)
    report_count_raise: list[ReporterRule] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _unique_kinds(self) -> Self:
        for rule in self.near_places:
            if len(rule.kinds) != len(set(rule.kinds)):
                raise ValueError("A near_places rule lists the same kind twice.")
        return self

    @property
    def search_radius_m(self) -> int:
        """How far to look for places to evaluate the near_places rules."""
        return max([NEAR_PLACES_RADIUS_M, *(r.within_m for r in self.near_places)])


# --- severity -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeverityInputs:
    details: list[dict[str, Any]]  # the answers of every report on the issue
    nearest_place_m: dict[str, float]  # place kind -> distance to the nearest one
    unique_reporters: int


@dataclass(frozen=True, slots=True)
class SeverityResult:
    level: SeverityLevel
    reason: str
    steps: list[str] = field(default_factory=list)


def _answer_matches(answer: Any, expected: Any) -> bool:
    # bool is an int in Python: a `true` rule must not match the answer 1.
    if isinstance(expected, bool) or isinstance(answer, bool):
        return isinstance(answer, bool) and isinstance(expected, bool) and answer is expected
    return answer == expected


def compute_severity(rules: SeverityRules, inputs: SeverityInputs) -> SeverityResult:
    level = rules.base
    steps = [f"base {rules.base.value}"]

    matched = [
        rule
        for rule in rules.field_rules
        if any(
            rule.field in details and _answer_matches(details[rule.field], rule.equals)
            for details in inputs.details
        )
    ]
    if matched:
        top = max(matched, key=lambda r: LEVELS.index(r.set))
        level = top.set
        steps.append(f"{top.field} = {_render(top.equals)} sets {top.set.value}")

    near = [
        (rule, kind, inputs.nearest_place_m[kind.value])
        for rule in rules.near_places
        for kind in rule.kinds
        if inputs.nearest_place_m.get(kind.value, math.inf) <= rule.within_m
    ]
    near_raise = 0
    if near:
        rule, kind, distance = max(near, key=lambda item: (item[0].raise_by, -item[2]))
        near_raise = rule.raise_by
        steps.append(f"{kind.value} {distance:.0f} m away raises {rule.raise_by}")

    crowd = [
        r for r in rules.report_count_raise if inputs.unique_reporters >= r.unique_reporters_gte
    ]
    crowd_raise = 0
    if crowd:
        rule = max(crowd, key=lambda r: r.raise_by)
        crowd_raise = rule.raise_by
        steps.append(f"{inputs.unique_reporters} reporters raise {rule.raise_by}")

    raised = raise_level(level, near_raise + crowd_raise)
    if near_raise + crowd_raise and LEVELS.index(level) + near_raise + crowd_raise >= len(LEVELS):
        steps.append("capped at critical")
    return SeverityResult(
        level=raised, reason="; ".join(steps) + f" -> {raised.value}", steps=steps
    )


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


# --- priority -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriorityInputs:
    severity: SeverityLevel
    unique_reporters: int
    age_days: float
    recurrence: int  # other issues of the category nearby within the lookback
    near_place: bool  # any place of interest within NEAR_PLACES_RADIUS_M
    inactive_status: str | None = None  # "rejected", "closed" or "merged" -> score 0


@dataclass(frozen=True, slots=True)
class Factor:
    factor: str
    value: Any
    normalized: float
    points: float
    explanation_key: str

    def as_json(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "value": self.value,
            "normalized": self.normalized,
            "points": self.points,
            "explanation_key": self.explanation_key,
        }


@dataclass(frozen=True, slots=True)
class PriorityResult:
    score: float
    band: PriorityBand
    factors: list[Factor]


def band_for(score: float, bands: PriorityBands) -> PriorityBand:
    if score >= bands.critical:
        return PriorityBand.CRITICAL
    if score >= bands.high:
        return PriorityBand.HIGH
    if score >= bands.medium:
        return PriorityBand.MEDIUM
    return PriorityBand.LOW


def reporters_factor(unique_reporters: int, saturation: int) -> float:
    """Logarithmic, so piling on reports flattens out quickly (PRD §12.3)."""
    u = max(0, unique_reporters)
    return min(1.0, math.log1p(u) / math.log1p(saturation))


def age_factor(age_days: float, saturation_days: int) -> float:
    return min(1.0, max(0.0, age_days) / saturation_days)


def recurrence_factor(count: int, saturation: int) -> float:
    return min(1.0, max(0, count) / saturation)


def compute_priority(config: PriorityConfig, inputs: PriorityInputs) -> PriorityResult:
    if inputs.inactive_status is not None:
        factor = Factor("status", inputs.inactive_status, 0.0, 0.0, "priority.inactive")
        return PriorityResult(score=0.0, band=PriorityBand.LOW, factors=[factor])

    w = config.weights
    normalized: list[tuple[str, Any, float, float]] = [
        (
            "severity",
            inputs.severity.value,
            getattr(config.severity_points, inputs.severity.value),
            w.severity,
        ),
        (
            "reporters",
            inputs.unique_reporters,
            reporters_factor(inputs.unique_reporters, config.reporters_saturation),
            w.reporters,
        ),
        (
            "age",
            round(max(0.0, inputs.age_days), 1),
            age_factor(inputs.age_days, config.age_saturation_days),
            w.age,
        ),
        (
            "recurrence",
            inputs.recurrence,
            recurrence_factor(inputs.recurrence, config.recurrence.saturation),
            w.recurrence,
        ),
        ("near_places", inputs.near_place, 1.0 if inputs.near_place else 0.0, w.near_places),
    ]
    factors = [
        Factor(name, value, round(norm, 4), round(norm * weight, 2), f"priority.{name}")
        for name, value, norm, weight in normalized
    ]
    score = round(min(100.0, sum(norm * weight for _, _, norm, weight in normalized)), 2)
    factors.sort(key=lambda f: (-f.points, f.factor))
    return PriorityResult(score=score, band=band_for(score, config.bands), factors=factors)
