"""Triage is the safety gate. If it is wrong, the system recommends pesticide
it should not have, so every branch gets a test."""
from __future__ import annotations

from app.services import triage


def codes(result) -> set[str]:
    return {r["code"] for r in result.reasons}


def test_missing_model_never_authorises_self_treatment():
    r = triage.evaluate(model_available=False, predicted_class=None, confidence=None)
    assert r.escalate is True
    assert r.self_treatment_allowed is False
    assert codes(r) == {"model_unavailable"}


def test_low_confidence_blocks_a_chemical_recommendation():
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_late_blight",
        confidence=0.31,
        detection_count=1,
    )
    assert r.escalate is True
    assert r.self_treatment_allowed is False
    assert "low_confidence" in codes(r)


def test_confident_detection_is_allowed_through():
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_early_blight",
        confidence=0.91,
        detection_count=2,
    )
    assert r.escalate is False
    assert r.self_treatment_allowed is True


def test_high_severity_disease_is_marked_urgent():
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_late_blight",
        confidence=0.88,
        detection_count=1,
    )
    assert r.urgency == "urgent"
    assert "fast_moving_disease" in codes(r)


def test_image_and_weather_disagreement_escalates():
    risk = {"top_threat": "potato_early_blight", "overall_level": "high"}
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_late_blight",
        confidence=0.92,
        detection_count=1,
        risk=risk,
    )
    assert r.escalate is True
    assert "conflicting_signals" in codes(r)


def test_repeated_treatment_failure_routes_to_a_laboratory():
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_late_blight",
        confidence=0.95,
        detection_count=1,
        failed_treatments=2,
    )
    assert r.referral_level == "laboratory"
    assert r.self_treatment_allowed is False
    assert "treatment_failure" in codes(r)


def test_field_scale_severity_escalates_to_district():
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_late_blight",
        confidence=0.95,
        detection_count=1,
        severity_fraction=0.4,
    )
    assert r.referral_level == "district"
    assert r.urgency == "urgent"


def test_healthy_crop_under_high_risk_opens_the_preventive_window():
    risk = {"top_threat": "potato_late_blight", "overall_level": "high"}
    r = triage.evaluate(
        model_available=True,
        predicted_class="potato_healthy",
        confidence=0.97,
        detection_count=1,
        risk=risk,
    )
    assert "preventive_window" in codes(r)
    assert r.urgency == "soon"


def test_no_detection_asks_for_a_better_photo():
    r = triage.evaluate(
        model_available=True, predicted_class=None, confidence=None, detection_count=0
    )
    assert r.escalate is True
    assert "no_detection" in codes(r)
