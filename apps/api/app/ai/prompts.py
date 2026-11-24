"""Default English prompts for zero-shot category suggestions.

A category can override its prompts through ``categories.ai_prompts``; these
are the fallback for the five seeded categories plus the reserved
``not_civic`` class.

They are hand-written, not searched. ``scripts/eval/tune_prompts.py`` tried
a greedy search over a pool of alternatives on the calibration half of the
evaluation set; cross-fitted on calib, the searched prompts scored 85%
against 91% for these, so the search was overfitting a small split and
these stayed (``docs/eval/phase-2-baseline.md``).
"""

from __future__ import annotations

NOT_CIVIC = "not_civic"
"""Reserved code: the photo doesn't show a civic problem (selfie, food, a document...)."""
UNKNOWN = "unknown"
"""Reserved code: the model isn't confident enough to suggest anything."""

DEFAULT_PROMPTS: dict[str, list[str]] = {
    "pothole": [
        "a photo of a pothole in the road",
        "a damaged road with potholes",
        "a broken asphalt road surface with a large hole",
        "a pothole filled with rainwater on a street",
    ],
    "waste": [
        "a photo of garbage dumped on the street",
        "a pile of rubbish and plastic waste by the roadside",
        "an overflowing garbage dump in a city",
        "litter and trash scattered on the ground",
    ],
    "waterlogging": [
        "a photo of a flooded street after heavy rain",
        "a waterlogged road with vehicles driving through water",
        "people walking through a flooded road during the monsoon",
        "a street submerged under rainwater",
    ],
    "streetlight": [
        "a photo of a street light pole",
        "a street lamp on a road",
        "a broken street light",
        "a lamp post beside a road at night",
    ],
    "drainage": [
        "a photo of an open drain beside a road",
        "a clogged drain full of sewage and garbage",
        "a dirty open sewer channel in a city",
        "an overflowing drain with dirty water",
    ],
    NOT_CIVIC: [
        "a selfie of a person",
        "a photo of food on a plate",
        "a screenshot of a phone or computer screen",
        "a photo of a document or a page of text",
        "a photo of a room indoors",
        "a portrait photo of people",
    ],
}
