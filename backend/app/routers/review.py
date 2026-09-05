"""/review -- the expert validation queue and the learning feedback loop.

An extension officer confirms, corrects or rejects each AI diagnosis. A decision
does three things:

1. Sets the case's authoritative label (`confirmed_class`), which is what the
   hotspot map and dashboard count -- so officials never plan around unverified
   model output.
2. Writes a `TrainingSample`, which `ml/export_feedback.py` turns into the next
   training increment. That is the "learns from field confirmations" requirement,
   made concrete.
3. Feeds `local pest history` back into the risk engine for neighbouring farms.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Case, ReviewStatus, TrainingSample
from app.schemas import CaseOut, ReviewDecision
from app.services import taxonomy

router = APIRouter(prefix="/review", tags=["review"])

# Seeded demo cases carry this model_version; real detections never do.
DEMO_MODEL_VERSION = "demo-seed"


def _exclude_demo(stmt):
    """Drop seeded demo cases while keeping real ones, including those whose
    model_version is NULL (a plain ``!=`` would silently drop NULLs too)."""
    return stmt.where(
        or_(Case.model_version.is_(None), Case.model_version != DEMO_MODEL_VERSION)
    )


@router.get("/queue", response_model=list[CaseOut], summary="Cases awaiting expert validation")
def queue(
    district: str | None = Query(None),
    only_escalated: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Case]:
    stmt = select(Case).where(Case.review_status == ReviewStatus.PENDING)
    if district:
        stmt = stmt.where(Case.district == district)
    if only_escalated:
        stmt = stmt.where(Case.escalate.is_(True))
    # Escalated and low-confidence cases first -- that is where an officer's
    # time is worth the most.
    stmt = stmt.order_by(Case.escalate.desc(), Case.confidence.asc(), Case.created_at.desc())
    return list(db.scalars(stmt.limit(limit)).all())


@router.get("/stats/accuracy", summary="Field-validated model accuracy")
def accuracy(
    include_demo: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    """Real accuracy measured against expert decisions, not a test-set number.

    This is the metric that matters after deployment, and it is what tells you
    when a retrain is due.
    """

    def count_where(*clauses) -> int:
        stmt = select(func.count(Case.id))
        for clause in clauses:
            stmt = stmt.where(clause)
        if not include_demo:
            stmt = _exclude_demo(stmt)
        return db.scalar(stmt) or 0

    reviewed = count_where(
        Case.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED])
    )
    confirmed = count_where(Case.review_status == ReviewStatus.CONFIRMED)
    rejected = count_where(Case.review_status == ReviewStatus.REJECTED)
    pending = count_where(Case.review_status == ReviewStatus.PENDING)

    per_class_stmt = (
        select(
            Case.predicted_class,
            func.count(Case.id),
            func.sum(sql_case((Case.review_status == ReviewStatus.CONFIRMED, 1), else_=0)),
        )
        .where(Case.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED]))
        .group_by(Case.predicted_class)
    )
    if not include_demo:
        per_class_stmt = _exclude_demo(per_class_stmt)
    per_class = db.execute(per_class_stmt).all()

    unexported = db.scalar(
        select(func.count(TrainingSample.id)).where(TrainingSample.exported.is_(False))
    ) or 0

    return {
        "reviewed": reviewed,
        "confirmed": confirmed,
        "corrected": reviewed - confirmed,
        "rejected": rejected,
        "pending": pending,
        "field_accuracy": round(confirmed / reviewed, 3) if reviewed else None,
        "per_class": [
            {
                "predicted_class": cls,
                "display": taxonomy.display_name(cls),
                "reviewed": total,
                "confirmed": int(ok or 0),
                "accuracy": round(int(ok or 0) / total, 3) if total else None,
            }
            for cls, total, ok in per_class
        ],
        "retraining_samples_pending_export": unexported,
    }


@router.get("/{case_id}", response_model=CaseOut, summary="Full case detail for review")
def get_case(case_id: int, db: Session = Depends(get_db)) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


@router.post("/{case_id}", response_model=CaseOut, summary="Record an expert decision")
def decide(case_id: int, decision: ReviewDecision, db: Session = Depends(get_db)) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    if decision.status == ReviewStatus.PENDING:
        raise HTTPException(status_code=422, detail="Cannot set a case back to pending.")

    if decision.status == ReviewStatus.CORRECTED:
        if not decision.confirmed_class:
            raise HTTPException(
                status_code=422, detail="'confirmed_class' is required when correcting a case."
            )
        if not taxonomy.get(decision.confirmed_class):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown class '{decision.confirmed_class}'. The deployed model covers "
                    f"{taxonomy.CLASS_NAMES}. To record something outside these, reject the "
                    "case and note the true diagnosis."
                ),
            )
        case.confirmed_class = decision.confirmed_class
    elif decision.status == ReviewStatus.CONFIRMED:
        case.confirmed_class = case.predicted_class

    case.review_status = decision.status
    case.reviewer = decision.reviewer
    case.reviewer_notes = decision.notes
    case.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Feedback loop: a validated image is a training sample.
    if case.image_path and decision.status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}:
        db.add(
            TrainingSample(
                case_id=case.id,
                image_path=case.image_path,
                label=case.confirmed_class or case.predicted_class or "unknown",
                was_model_correct=decision.status == ReviewStatus.CONFIRMED,
                model_version=case.model_version,
            )
        )

    db.commit()
    db.refresh(case)
    return case
