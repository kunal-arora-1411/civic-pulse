"""What the evaluation measured for each deployed model, by model id.

The AI worker copies these into ``model_registry.metrics`` when it
registers its models at start-up, so administrators see them next to the
model's source and licence, and matching reads the per-model defaults from
there. Numbers come from ``docs/eval/phase-2-baseline.md`` (raw results in
``docs/eval/phase-2-baseline-*.json``); rerun the evaluation and update this
file whenever a model id changes. They are baseline figures on a small open
dataset, not field performance.

``matching.visual_min`` is the auto-link visual floor for the model: the
lowest cosine similarity at which different photos of the same category
pass at a false-merge rate of 1% or less. It belongs to the model because
similarity scales differ between models (LAION's 0.80 is not OpenAI's
0.80). A tenant can still set its own in ``matching_config``.

Pure data, so the API image can import it without the ``ai`` extra.
"""

from __future__ import annotations

from typing import Any

_BASELINE = "docs/eval/phase-2-baseline.md"

MODEL_METRICS: dict[str, dict[str, Any]] = {
    "clip-vit-b32@onnx-1": {
        "evaluation": _BASELINE,
        "evaluated_on": "2026-11-24",
        "dataset": "187 openly licensed images (92 calibration, 95 test)",
        "classification": {
            "accuracy": 0.947,
            "accuracy_ci95": [0.905, 0.989],
            "macro_f1": 0.946,
            "top3_accuracy": 1.0,
            "log_loss": 0.208,
            "calibration_error": 0.036,
            "temperature": 0.0084,
            "threshold": 0.45,
            "coverage_at_threshold": 0.989,
        },
        "duplicates": {
            "roc_auc": 0.989,
            "average_precision": 0.888,
            "recall_at_visual_min": 0.543,
            "false_merge_rate_at_visual_min": 0.008,
            "false_merge_rate_at_0_80": 0.110,
            "same_photo_rule": "pHash distance <= 6: 100% of re-uploads, 0% of different photos",
        },
        "matching": {"visual_min": 0.92},
    },
    "yunet-2023mar@onnx-1": {
        "evaluation": "tests/ai/test_faces.py",
        "notes": (
            "Two passes (640 and 1920 px) merged with NMS; checked on a CC0 class photo with "
            "45 small faces and a CC BY group selfie. Not evaluated on a labelled face set."
        ),
    },
}


def metrics_for(model_id: str) -> dict[str, Any]:
    """The recorded metrics for ``model_id``, or an empty dict."""
    return dict(MODEL_METRICS.get(model_id, {}))
