"""Triage: decide whether a case is safe to self-treat or must go to an expert.

This is the safety gate the problem statement asks for -- "referral to extension
officers or laboratories" and "safe input usage". It sits between the model and
the advisory, and it is deliberately conservative: when the system is unsure,
it says so and hands the case to a human instead of recommending a pesticide.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.services import taxonomy


@dataclass
class TriageResult:
    escalate: bool
    urgency: str  # routine | soon | urgent
    reasons: list[dict] = field(default_factory=list)
    self_treatment_allowed: bool = True
    referral_level: str | None = None  # village | block | district | laboratory

    def to_dict(self) -> dict:
        return {
            "escalate": self.escalate,
            "urgency": self.urgency,
            "self_treatment_allowed": self.self_treatment_allowed,
            "referral_level": self.referral_level,
            "reasons": self.reasons,
        }


def _reason(code: str, message: str, action: str) -> dict:
    return {"code": code, "message": message, "action": action}


def evaluate(
    *,
    model_available: bool,
    predicted_class: str | None,
    confidence: float | None,
    risk: dict | None = None,
    detection_count: int = 0,
    failed_treatments: int = 0,
    severity_fraction: float | None = None,
) -> TriageResult:
    """`severity_fraction` is the share of the field reported affected, 0-1."""
    reasons: list[dict] = []
    escalate = False
    self_treat = True
    urgency = "routine"
    referral: str | None = None

    # 1. No model, no diagnosis. Never guess a pesticide from nothing.
    if not model_available:
        return TriageResult(
            escalate=True,
            urgency="soon",
            self_treatment_allowed=False,
            referral_level="block",
            reasons=[
                _reason(
                    "model_unavailable",
                    "The image detection model is not available on this deployment, so no "
                    "automated diagnosis was made.",
                    "Send the photograph to your Taluka Agriculture Officer or KVK for a "
                    "human diagnosis. Do not spray on the basis of this app alone.",
                )
            ],
        )

    # 2. Model ran but saw nothing above threshold.
    if predicted_class is None or detection_count == 0:
        escalate = True
        self_treat = False
        referral = "village"
        urgency = "soon"
        reasons.append(
            _reason(
                "no_detection",
                "The model found no symptom it recognises above the confidence threshold. "
                "This may mean a healthy crop, a poor photograph, or a problem outside the "
                "three potato classes it was trained on.",
                "Retake the photo in daylight, filling the frame with the affected leaf. If "
                "symptoms are visible to you, refer the case to an extension officer.",
            )
        )

    # 3. Low confidence -- the core safety rule.
    if confidence is not None and confidence < settings.low_confidence_threshold:
        escalate = True
        self_treat = False
        referral = referral or "village"
        urgency = "soon" if urgency == "routine" else urgency
        reasons.append(
            _reason(
                "low_confidence",
                f"Model confidence is {confidence:.0%}, below the "
                f"{settings.low_confidence_threshold:.0%} threshold required to recommend a "
                "chemical treatment.",
                "Treat the diagnosis as provisional. Get it confirmed by an extension officer "
                "before buying or applying any pesticide.",
            )
        )

    # 4. Image and weather disagree -- classic misdiagnosis trap.
    if risk and predicted_class and taxonomy.is_actionable(predicted_class):
        top = risk.get("top_threat")
        top_level = risk.get("overall_level")
        if top and top != predicted_class and top_level == "high":
            escalate = True
            reasons.append(
                _reason(
                    "conflicting_signals",
                    f"The image was classified as {taxonomy.display_name(predicted_class)}, but "
                    f"weather conditions indicate HIGH risk of "
                    f"{taxonomy.display_name(top)} instead.",
                    "Have an extension officer inspect the field before choosing a chemistry - "
                    "the wrong product here wastes money and leaves residue for no benefit.",
                )
            )

    # 5. High weather risk with a healthy-looking crop is a preventive decision.
    if risk and predicted_class == "potato_healthy" and risk.get("overall_level") == "high":
        urgency = "soon"
        reasons.append(
            _reason(
                "preventive_window",
                "No symptoms were detected, but the weather risk forecast is HIGH. This is the "
                "window where a protectant spray prevents an epidemic instead of chasing it.",
                "Follow the preventive advisory and scout the field within 48 hours. This is a "
                "judgement call worth confirming with your Krishi Sahayak.",
            )
        )

    # 6. Repeated treatment failure suggests resistance, not a bigger dose.
    if failed_treatments >= 2:
        escalate = True
        self_treat = False
        referral = "laboratory"
        urgency = "urgent"
        reasons.append(
            _reason(
                "treatment_failure",
                f"{failed_treatments} follow-ups recorded the problem as unchanged or worsened "
                "after treatment.",
                "Do not repeat the same spray. This pattern suggests fungicide resistance or a "
                "misdiagnosis and needs laboratory confirmation through your KVK.",
            )
        )

    # 7. Field-scale severity is an outbreak, not an individual problem.
    if severity_fraction is not None and severity_fraction >= 0.25:
        escalate = True
        referral = "district"
        urgency = "urgent"
        reasons.append(
            _reason(
                "high_severity",
                f"About {severity_fraction:.0%} of the field is reported affected.",
                "Report to the Taluka Agriculture Officer today. At this scale a coordinated "
                "response is needed, and neighbouring fields should be surveyed.",
            )
        )

    # 8. A confident high-severity disease is urgent even if self-treatable.
    info = taxonomy.get(predicted_class)
    if (
        info
        and info.severity == "high"
        and confidence is not None
        and confidence >= settings.low_confidence_threshold
    ):
        urgency = "urgent" if urgency != "urgent" else urgency
        reasons.append(
            _reason(
                "fast_moving_disease",
                f"{info.display} can destroy an unprotected crop within 7-10 days once "
                "conditions are favourable.",
                "Begin the recommended management today, and inform neighbouring farmers so "
                "they can protect their fields.",
            )
        )

    if not reasons:
        reasons.append(
            _reason(
                "clear_case",
                "Confident diagnosis with no conflicting signals.",
                "Follow the advisory below and complete the scheduled follow-up.",
            )
        )

    return TriageResult(
        escalate=escalate,
        urgency=urgency,
        self_treatment_allowed=self_treat,
        referral_level=referral,
        reasons=reasons,
    )
