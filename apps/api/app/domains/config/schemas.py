"""The per-tenant matching and priority documents, with their defaults.

Every field has the contract's default, so `MatchingConfig()` is the
built-in configuration and a PUT that leaves a field out resets it. The
validators keep the numbers in ranges where the scores still mean what
the thresholds assume: weights that sum to 1 (matching) or 100 (priority),
thresholds in order, severity points that never decrease.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_TOLERANCE = 1e-6

DEFAULT_VISUAL_MIN = 0.92
"""The auto-link visual floor when neither the tenant nor the model sets one.

Cosine similarity scales differ between vision models (one model's 0.80 is
not another's), so the floor is normally the one measured for the active
model and stored in its `model_registry.metrics` (`matching.visual_min`).
This is the fallback, the value measured for the shipped CLIP model
(docs/eval/phase-2-baseline.md).
"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- matching (contract D.2 and G) --------------------------------------------------------


class MatchingWeights(_Strict):
    geo: float = Field(default=0.40, ge=0, le=1)
    visual: float = Field(default=0.40, ge=0, le=1)
    category: float = Field(default=0.10, ge=0, le=1)
    time: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def _sum_to_one(self) -> Self:
        total = self.geo + self.visual + self.category + self.time
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"The weights must add up to 1 (they add up to {total:.3f}).")
        return self


class MatchingThresholds(_Strict):
    auto: float = Field(default=0.85, gt=0, le=1, description="Score needed to link on its own.")
    review: float = Field(default=0.60, gt=0, le=1, description="Score that asks a person.")
    visual_min: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Visual similarity an automatic link also needs. Null follows the floor measured "
            "for the active vision model (0.92 for the shipped CLIP model); a number overrides it."
        ),
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.review > self.auto + _TOLERANCE:
            raise ValueError("The review threshold can't be above the automatic-link threshold.")
        return self


class MatchingConfig(_Strict):
    auto_link_enabled: bool = True
    weights: MatchingWeights = Field(default_factory=MatchingWeights)
    thresholds: MatchingThresholds = Field(default_factory=MatchingThresholds)
    classification_threshold: float = Field(
        default=0.45,
        ge=0,
        le=1,
        description="Below this top-category confidence the citizen is asked to choose.",
    )
    fallback_review_threshold: float = Field(
        default=0.40,
        ge=0,
        le=1,
        description="Without the visual signal, a score this high opens a review task.",
    )

    def with_visual_floor(self, model_floor: float | None) -> MatchingConfig:
        """This config with `visual_min` filled in: the tenant's own value if
        it set one, else the model's, else DEFAULT_VISUAL_MIN."""
        if self.thresholds.visual_min is not None:
            return self
        floor = DEFAULT_VISUAL_MIN if model_floor is None else model_floor
        thresholds = self.thresholds.model_copy(update={"visual_min": floor})
        return self.model_copy(update={"thresholds": thresholds})


# --- priority (contract F) ---------------------------------------------------------------


class PriorityWeights(_Strict):
    severity: float = Field(default=40, ge=0, le=100)
    reporters: float = Field(default=20, ge=0, le=100)
    age: float = Field(default=15, ge=0, le=100)
    recurrence: float = Field(default=15, ge=0, le=100)
    near_places: float = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def _sum_to_hundred(self) -> Self:
        total = self.severity + self.reporters + self.age + self.recurrence + self.near_places
        if abs(total - 100.0) > 1e-3:
            raise ValueError(f"The weights must add up to 100 (they add up to {total:g}).")
        return self


class SeverityPoints(_Strict):
    low: float = Field(default=0.10, ge=0, le=1)
    medium: float = Field(default=0.40, ge=0, le=1)
    high: float = Field(default=0.75, ge=0, le=1)
    critical: float = Field(default=1.00, ge=0, le=1)

    @model_validator(mode="after")
    def _non_decreasing(self) -> Self:
        if not self.low <= self.medium <= self.high <= self.critical:
            raise ValueError("A higher severity can't be worth fewer points than a lower one.")
        return self


class RecurrenceConfig(_Strict):
    radius_m: int = Field(default=50, ge=1, le=5000)
    lookback_days: int = Field(default=180, ge=1, le=3650)
    saturation: int = Field(default=3, ge=1, le=100)


class PriorityBands(_Strict):
    critical: float = Field(default=80, gt=0, le=100)
    high: float = Field(default=60, gt=0, le=100)
    medium: float = Field(default=35, gt=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.critical > self.high > self.medium:
            raise ValueError("Band thresholds must fall from critical to high to medium.")
        return self


class PriorityConfig(_Strict):
    weights: PriorityWeights = Field(default_factory=PriorityWeights)
    severity_points: SeverityPoints = Field(default_factory=SeverityPoints)
    reporters_saturation: int = Field(default=10, ge=1, le=1000)
    age_saturation_days: int = Field(default=30, ge=1, le=3650)
    recurrence: RecurrenceConfig = Field(default_factory=RecurrenceConfig)
    bands: PriorityBands = Field(default_factory=PriorityBands)


class ClosureConfig(_Strict):
    """Resolution window and the citizen-confirmation threshold (Phase 3)."""

    resolution_window_hours: int = Field(
        default=168, ge=1, le=2160, description="`resolved` becomes `closed` after this long."
    )
    confirmations_required: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Distinct citizens confirming resolution, for categories that don't "
        "require approval (FR-073).",
    )


class ReportLimitsConfig(_Strict):
    """How many reports one citizen may submit, per tenant (PRD §12.3).

    The process-wide defaults (10/hour, 30/day) apply until a tenant sets
    its own; a stricter or looser city doesn't need a code change."""

    max_per_hour: int = Field(default=10, ge=1, le=1000)
    max_per_day: int = Field(default=30, ge=1, le=10000)

    @model_validator(mode="after")
    def _day_not_below_hour(self) -> Self:
        if self.max_per_day < self.max_per_hour:
            raise ValueError("The daily limit can't be below the hourly limit.")
        return self
