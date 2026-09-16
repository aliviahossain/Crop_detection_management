"""Golden vectors for `backend/app/services/triage.py`.

Triage is the safety gate: it decides whether a farmer may act on the app's
own diagnosis or must be sent to a human. Every branch is pinned here,
including the boundary values, because on the handset this code runs with no
server to fall back on and no reviewer watching. A port that is off by one on
`confidence >= 0.55` changes who is told to buy a fungicide.
"""
from __future__ import annotations

from app.config import settings
from app.services import triage

SOURCE = "backend/app/services/triage.py"

T = settings.low_confidence_threshold

HIGH_LATE_BLIGHT_RISK = {"top_threat": "potato_late_blight", "overall_level": "high"}
HIGH_EARLY_BLIGHT_RISK = {"top_threat": "potato_early_blight", "overall_level": "high"}
MEDIUM_RISK = {"top_threat": "potato_late_blight", "overall_level": "medium"}

BASE = {
    "model_available": True,
    "predicted_class": "potato_late_blight",
    "confidence": 0.91,
    "risk": None,
    "detection_count": 1,
    "failed_treatments": 0,
    "severity_fraction": None,
}


def case(id_, why, **over):
    return {"id": id_, "why": why, "input": {**BASE, **over}}


CASES = [
    case(
        "model_unavailable_short_circuits",
        "No model means no diagnosis. This returns immediately and must never reach the other rules.",
        model_available=False,
        predicted_class=None,
        confidence=None,
    ),
    case(
        "model_unavailable_ignores_other_signals",
        "Even with a severe field report, an absent model still yields exactly one reason.",
        model_available=False,
        predicted_class=None,
        confidence=None,
        severity_fraction=0.8,
        failed_treatments=3,
    ),
    case(
        "no_detection_null_class",
        "Model ran, recognised nothing. Escalates to village level rather than guessing.",
        predicted_class=None,
        confidence=None,
        detection_count=0,
    ),
    case(
        "no_detection_zero_count",
        "A class survived but no boxes did - detection_count 0 is the authority.",
        detection_count=0,
    ),
    case(
        "low_confidence_just_below_threshold",
        f"Confidence just under {T:.2f} must block a chemical recommendation.",
        confidence=round(T - 0.01, 4),
    ),
    case(
        "confidence_exactly_at_threshold",
        f"Exactly {T:.2f} is NOT low confidence - the rule is '<', so this passes.",
        confidence=T,
    ),
    case(
        "very_low_confidence",
        "Far below threshold - low_confidence plus no other escalation.",
        confidence=0.12,
    ),
    case(
        "conflicting_signals_image_vs_weather",
        "Image says early blight, weather says HIGH late blight risk: the misdiagnosis trap.",
        predicted_class="potato_early_blight",
        confidence=0.88,
        risk=HIGH_LATE_BLIGHT_RISK,
    ),
    case(
        "agreeing_signals_no_conflict",
        "Image and weather name the same threat - no conflict reason may fire.",
        predicted_class="potato_late_blight",
        confidence=0.88,
        risk=HIGH_LATE_BLIGHT_RISK,
    ),
    case(
        "conflict_requires_high_risk",
        "Disagreement at MEDIUM risk is not enough to escalate.",
        predicted_class="potato_early_blight",
        confidence=0.88,
        risk=MEDIUM_RISK,
    ),
    case(
        "healthy_crop_high_risk_preventive_window",
        "Healthy leaf but HIGH forecast risk - the protectant-spray decision, not an escalation.",
        predicted_class="potato_healthy",
        confidence=0.95,
        risk=HIGH_LATE_BLIGHT_RISK,
    ),
    case(
        "healthy_crop_calm_weather",
        "The do-not-spray case: healthy, no risk, nothing to escalate.",
        predicted_class="potato_healthy",
        confidence=0.95,
        risk=MEDIUM_RISK,
    ),
    case(
        "healthy_crop_is_not_actionable_for_conflict",
        "Healthy is not actionable, so the conflicting-signals rule must skip it.",
        predicted_class="potato_healthy",
        confidence=0.95,
        risk=HIGH_EARLY_BLIGHT_RISK,
    ),
    case(
        "one_failed_treatment_not_yet_resistance",
        "A single failure is not a pattern - must not escalate to laboratory.",
        failed_treatments=1,
    ),
    case(
        "two_failed_treatments_resistance",
        "Two failures means laboratory referral, not a heavier dose.",
        failed_treatments=2,
    ),
    case(
        "severity_just_below_field_scale",
        "24% affected stays an individual problem.",
        severity_fraction=0.24,
    ),
    case(
        "severity_exactly_at_field_scale",
        "25% exactly is an outbreak - the rule is '>='.",
        severity_fraction=0.25,
    ),
    case(
        "severity_majority_of_field",
        "Most of the field affected - district referral, urgent.",
        severity_fraction=0.7,
    ),
    case(
        "confident_high_severity_disease",
        "Late blight is high-severity: urgent even when self-treatment stays allowed.",
        predicted_class="potato_late_blight",
        confidence=0.93,
    ),
    case(
        "confident_moderate_severity_disease",
        "Early blight is moderate - no fast-moving-disease reason.",
        predicted_class="potato_early_blight",
        confidence=0.93,
    ),
    case(
        "clear_case_no_reasons_fired",
        "Nothing wrong: the fallback clear_case reason must be present, never an empty list.",
        predicted_class="potato_early_blight",
        confidence=0.87,
        risk=MEDIUM_RISK,
    ),
    case(
        "compound_low_confidence_and_failures",
        "Several rules fire together - reason order and the strongest referral must both hold.",
        confidence=0.3,
        failed_treatments=2,
    ),
    case(
        "compound_everything_at_once",
        "Worst case: weak detection, conflict, repeated failure and field-scale spread.",
        predicted_class="potato_early_blight",
        confidence=0.2,
        risk=HIGH_LATE_BLIGHT_RISK,
        failed_treatments=3,
        severity_fraction=0.6,
    ),
    case(
        "null_confidence_with_detection",
        "A detection with no confidence value must not crash the threshold comparison.",
        confidence=None,
    ),
    case(
        "unknown_class_not_in_taxonomy",
        "A label the taxonomy does not know must degrade safely, not raise.",
        predicted_class="tomato_leaf_mould",
        confidence=0.9,
    ),
]


def build() -> dict:
    cases = []
    for c in CASES:
        result = triage.evaluate(**c["input"])
        cases.append({**c, "fn": "evaluate", "expect": result.to_dict()})
    return {
        "suite": "triage",
        "source": SOURCE,
        "description": "The safety gate between the detector and the advisory.",
        "constants": {"low_confidence_threshold": T},
        "cases": cases,
    }
