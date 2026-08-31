"""/dashboard -- aggregate view for agriculture officials.

Everything here answers a planning question an officer actually has: where is
pressure building, which taluka needs staff this week, is the model still
trustworthy, and are advisories leading to resolved cases.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Case,
    CaseSource,
    FollowUp,
    FollowUpOutcome,
    ReviewStatus,
    RiskLevel,
    SensorReading,
)
from app.schemas import CaseOut
from app.services import taxonomy

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", summary="Headline numbers for the officer dashboard")
def summary(
    days: int = Query(30, ge=1, le=365),
    district: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    def base():
        stmt = select(Case).where(Case.created_at >= since)
        return stmt.where(Case.district == district) if district else stmt

    cases = list(db.scalars(base()).all())
    total = len(cases)
    escalated = sum(1 for c in cases if c.escalate)
    pending = sum(1 for c in cases if c.review_status == ReviewStatus.PENDING)
    confirmed = sum(
        1 for c in cases if c.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}
    )
    with_image = sum(1 for c in cases if c.source == CaseSource.IMAGE)
    proactive = sum(1 for c in cases if c.source == CaseSource.RISK_FORECAST)

    by_class: dict[str, int] = {}
    for c in cases:
        label = c.effective_class
        if label:
            by_class[label] = by_class.get(label, 0) + 1

    by_risk: dict[str, int] = {level.value: 0 for level in RiskLevel}
    for c in cases:
        if c.risk_level:
            by_risk[c.risk_level.value] += 1

    high_risk_districts = {}
    for c in cases:
        if c.district and c.risk_level == RiskLevel.HIGH:
            high_risk_districts[c.district] = high_risk_districts.get(c.district, 0) + 1

    overdue = db.scalar(
        select(func.count(FollowUp.id))
        .where(FollowUp.outcome == FollowUpOutcome.PENDING)
        .where(FollowUp.due_date <= datetime.now(timezone.utc).replace(tzinfo=None))
    ) or 0

    sensor_devices = db.scalar(
        select(func.count(func.distinct(SensorReading.device_id))).where(
            SensorReading.recorded_at >= since
        )
    ) or 0

    return {
        "window_days": days,
        "district": district,
        "cases": {
            "total": total,
            "from_image": with_image,
            "proactive_risk_only": proactive,
            "escalated": escalated,
            "pending_review": pending,
            "expert_confirmed": confirmed,
            "escalation_rate": round(escalated / total, 3) if total else None,
        },
        "by_class": [
            {
                "class_key": k,
                "display": taxonomy.display_name(k),
                "count": v,
                "share": round(v / total, 3) if total else 0,
            }
            for k, v in sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "by_risk_level": by_risk,
        "high_risk_districts": [
            {"district": k, "high_risk_cases": v}
            for k, v in sorted(high_risk_districts.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "follow_ups_overdue": overdue,
        "active_sensor_devices": sensor_devices,
    }


@router.get("/trend", summary="Daily case counts, for the dashboard chart")
def trend(
    days: int = Query(30, ge=7, le=365),
    district: str | None = Query(None),
    class_key: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stmt = select(Case).where(Case.created_at >= since)
    if district:
        stmt = stmt.where(Case.district == district)
    cases = list(db.scalars(stmt).all())

    series: dict[str, dict] = {}
    for i in range(days + 1):
        day = (since + timedelta(days=i)).date().isoformat()
        series[day] = {"date": day, "total": 0, "confirmed": 0, "escalated": 0, "high_risk": 0}

    for c in cases:
        label = c.effective_class
        if class_key and label != class_key:
            continue
        day = c.created_at.date().isoformat()
        row = series.get(day)
        if row is None:
            continue
        row["total"] += 1
        if c.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}:
            row["confirmed"] += 1
        if c.escalate:
            row["escalated"] += 1
        if c.risk_level == RiskLevel.HIGH:
            row["high_risk"] += 1

    return {"days": days, "class_key": class_key, "series": list(series.values())}


@router.get("/cases", response_model=list[CaseOut], summary="Filterable case list")
def cases(
    days: int = Query(30, ge=1, le=365),
    district: str | None = Query(None),
    class_key: str | None = Query(None),
    review_status: ReviewStatus | None = Query(None),
    escalated_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Case]:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stmt = select(Case).where(Case.created_at >= since)
    if district:
        stmt = stmt.where(Case.district == district)
    if review_status:
        stmt = stmt.where(Case.review_status == review_status)
    if escalated_only:
        stmt = stmt.where(Case.escalate.is_(True))
    rows = list(db.scalars(stmt.order_by(Case.created_at.desc()).limit(limit * 2)).all())
    if class_key:
        rows = [c for c in rows if c.effective_class == class_key]
    return rows[:limit]


@router.get("/districts", summary="Districts present in the data")
def districts(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Case.district, func.count(Case.id))
        .where(Case.district.is_not(None))
        .group_by(Case.district)
        .order_by(func.count(Case.id).desc())
    ).all()
    return {"districts": [{"district": d, "cases": n} for d, n in rows]}
