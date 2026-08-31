"""The core loop, in one place.

    image (optional) -> detection
                     -> weather risk
                     -> triage / referral decision
                     -> IPDM advisory (RAG)
                     -> persisted case + scheduled follow-up

Both `/detect` (reactive, farmer uploads a photo) and `/risk` (proactive, no
image) run through here, which is what keeps the two entry points consistent:
the same safety gate, the same advisory pipeline, the same case record feeding
the hotspot map and the officer dashboard.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Case, CaseSource, FollowUp, FollowUpOutcome, RiskLevel
from app.services import advisory as advisory_service
from app.services import triage as triage_service
from app.services.detector import DetectionResult
from app.services.geo import geo_cell
from app.services.risk_engine import RiskContext, assess


def count_failed_treatments(db: Session, phone: str | None, crop: str) -> int:
    """How many times this farmer has already reported a treatment not working.

    Two strikes flips triage into 'suspect resistance, refer to a lab' instead
    of recommending yet another spray -- the exact behaviour the problem
    statement asks for when it calls out excessive pesticide use.
    """
    if not phone:
        return 0
    return int(
        db.scalar(
            select(func.count(FollowUp.id))
            .join(Case, Case.id == FollowUp.case_id)
            .where(Case.phone == phone)
            .where(Case.crop == crop)
            .where(FollowUp.outcome.in_([FollowUpOutcome.UNCHANGED, FollowUpOutcome.WORSENED]))
        )
        or 0
    )


def run_case(
    db: Session,
    *,
    source: CaseSource,
    detection: DetectionResult | None,
    image_path: str | None,
    lat: float | None,
    lon: float | None,
    ctx: RiskContext,
    language: str,
    farmer_name: str | None = None,
    phone: str | None = None,
    village: str | None = None,
    severity_fraction: float | None = None,
    persist: bool = True,
    include_risk: bool = True,
    include_advisory: bool = True,
) -> dict:
    risk = None
    if include_risk and lat is not None and lon is not None:
        risk = assess(db, lat, lon, ctx)

    predicted = detection.top_class if detection else None
    confidence = detection.top_confidence if detection else None
    model_available = detection.model_available if detection else True
    det_count = len(detection.detections) if detection else 0

    if detection is None:
        # Proactive path: there is no image, so image-based triage rules that
        # depend on a detection are not applicable. Risk still drives urgency.
        triage_result = triage_service.evaluate(
            model_available=True,
            predicted_class=(risk or {}).get("top_threat"),
            confidence=None,
            risk=risk,
            detection_count=1,
            failed_treatments=count_failed_treatments(db, phone, ctx.crop),
            severity_fraction=severity_fraction,
        )
        # No image means no confirmed symptom: never authorise chemical use
        # from a forecast alone without the farmer scouting first.
        triage_result.self_treatment_allowed = (risk or {}).get("overall_level") == "high"
    else:
        triage_result = triage_service.evaluate(
            model_available=model_available,
            predicted_class=predicted,
            confidence=confidence,
            risk=risk,
            detection_count=det_count,
            failed_treatments=count_failed_treatments(db, phone, ctx.crop),
            severity_fraction=severity_fraction,
        )

    triage_dict = triage_result.to_dict()

    advisory = {}
    if include_advisory:
        advisory = advisory_service.generate(
            class_key=predicted or (risk or {}).get("top_threat"),
            confidence=confidence,
            model_available=model_available,
            has_detection=detection is not None and bool(detection.detections),
            risk=risk,
            triage=triage_dict,
            language=language,
        )

    case: Case | None = None
    follow_up: FollowUp | None = None
    if persist:
        case = Case(
            source=source,
            farmer_name=farmer_name,
            phone=phone,
            crop=ctx.crop,
            variety=ctx.variety,
            crop_stage=ctx.crop_stage,
            soil_condition=ctx.soil_condition,
            district=ctx.district,
            village=village,
            latitude=lat,
            longitude=lon,
            geo_cell=geo_cell(lat, lon),
            image_path=image_path,
            predicted_class=predicted,
            confidence=confidence,
            detections=[d.__dict__ for d in detection.detections] if detection else None,
            model_version=detection.model_version if detection else None,
            risk_level=RiskLevel((risk or {}).get("overall_level", "low")) if risk else None,
            risk_score=(risk or {}).get("overall_score") if risk else None,
            risk_detail={
                "top_threat": (risk or {}).get("top_threat"),
                "weather": (risk or {}).get("weather"),
                "threats": [
                    {"key": t["key"], "level": t["level"], "score": t["score"]}
                    for t in (risk or {}).get("threats", [])
                ],
            }
            if risk
            else None,
            escalate=triage_result.escalate,
            escalation_reasons=triage_result.reasons,
            advisory=advisory or None,
            language=language,
        )
        db.add(case)
        db.flush()

        days = (advisory.get("follow_up", {}) or {}).get("days", 7)
        follow_up = FollowUp(
            case_id=case.id,
            due_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days),
            notes=(advisory.get("follow_up", {}) or {}).get("text"),
        )
        db.add(follow_up)
        db.commit()
        db.refresh(case)

    return {
        "case": case,
        "follow_up": follow_up,
        "risk": risk,
        "triage": triage_dict,
        "advisory": advisory,
    }
