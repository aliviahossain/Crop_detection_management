"""/followups -- did the recommended treatment actually work?

This closes the loop the problem statement asks for. It also does real safety
work: an outcome of `unchanged` or `worsened` marks the case escalated, so the
next advisory for that farmer refuses to recommend the same spray again and
sends them to a laboratory instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Case, FollowUp, FollowUpOutcome
from app.schemas import FollowUpIn, FollowUpOut, FollowUpUpdate

router = APIRouter(prefix="/followups", tags=["follow-up"])

ESCALATING_OUTCOMES = {FollowUpOutcome.UNCHANGED, FollowUpOutcome.WORSENED}


@router.get("", response_model=list[FollowUpOut], summary="List follow-ups")
def list_follow_ups(
    due_only: bool = Query(False, description="Only those due now and still pending"),
    case_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[FollowUp]:
    stmt = select(FollowUp)
    if case_id is not None:
        stmt = stmt.where(FollowUp.case_id == case_id)
    if due_only:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(FollowUp.outcome == FollowUpOutcome.PENDING).where(
            FollowUp.due_date <= now
        )
    return list(db.scalars(stmt.order_by(FollowUp.due_date).limit(limit)).all())


@router.post("", response_model=FollowUpOut, summary="Schedule an additional follow-up")
def create(payload: FollowUpIn, db: Session = Depends(get_db)) -> FollowUp:
    case = db.get(Case, payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {payload.case_id} not found")
    due = payload.due_date or (datetime.now(timezone.utc) + timedelta(days=7))
    if due.tzinfo is not None:
        due = due.astimezone(timezone.utc).replace(tzinfo=None)
    row = FollowUp(case_id=case.id, due_date=due, notes=payload.notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{follow_up_id}", response_model=FollowUpOut, summary="Record the outcome")
def update(follow_up_id: int, payload: FollowUpUpdate, db: Session = Depends(get_db)) -> FollowUp:
    row = db.get(FollowUp, follow_up_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Follow-up {follow_up_id} not found")

    row.outcome = payload.outcome
    row.treatment_applied = payload.treatment_applied
    row.notes = payload.notes or row.notes
    if payload.outcome != FollowUpOutcome.PENDING:
        row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if payload.outcome in ESCALATING_OUTCOMES:
        case = db.get(Case, row.case_id)
        if case is not None:
            case.escalate = True
            reasons = list(case.escalation_reasons or [])
            reasons.append(
                {
                    "code": "followup_treatment_failed",
                    "message": (
                        f"Follow-up on {row.due_date.date().isoformat()} recorded the problem as "
                        f"{payload.outcome.value} after treatment."
                    ),
                    "action": (
                        "Do not repeat the same product. Refer to the Krishi Vigyan Kendra for "
                        "laboratory confirmation and a changed management plan."
                    ),
                }
            )
            case.escalation_reasons = reasons

    db.commit()
    db.refresh(row)
    return row


@router.get("/stats", summary="Treatment outcome statistics")
def stats(days: int = Query(90, ge=1, le=730), db: Session = Depends(get_db)) -> dict:
    """What share of advisories actually resolved the problem -- the closest
    thing this system has to an outcome measure of 'reduced crop loss'."""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.execute(
        select(FollowUp.outcome, func.count(FollowUp.id))
        .where(FollowUp.created_at >= since)
        .group_by(FollowUp.outcome)
    ).all()
    counts = {outcome.value: count for outcome, count in rows}
    closed = sum(v for k, v in counts.items() if k != FollowUpOutcome.PENDING.value)
    improved = counts.get(FollowUpOutcome.RESOLVED.value, 0) + counts.get(
        FollowUpOutcome.IMPROVING.value, 0
    )
    overdue = db.scalar(
        select(func.count(FollowUp.id))
        .where(FollowUp.outcome == FollowUpOutcome.PENDING)
        .where(FollowUp.due_date <= datetime.now(timezone.utc).replace(tzinfo=None))
    ) or 0
    return {
        "window_days": days,
        "counts": counts,
        "closed": closed,
        "overdue": overdue,
        "improvement_rate": round(improved / closed, 3) if closed else None,
    }
