"""POST /advisory -- IPDM recommendations from the knowledge base.

Callable standalone (an officer asking "what is the current guidance for late
blight in Marathi") or implicitly as part of /detect and /risk.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AdvisoryRequest, AdvisoryResponse
from app.services import advisory as advisory_service
from app.services import taxonomy, triage as triage_service
from app.services.knowledge_base import knowledge_base
from app.services.risk_engine import RiskContext, assess
from app.services.translate import normalise_language

router = APIRouter(prefix="/advisory", tags=["advisory"])


@router.post("", response_model=AdvisoryResponse, summary="Generate an IPDM advisory")
def advisory(req: AdvisoryRequest, db: Session = Depends(get_db)) -> AdvisoryResponse:
    lang = normalise_language(req.language)
    if req.class_key and not taxonomy.get(req.class_key):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown class '{req.class_key}'. Known classes: {taxonomy.CLASS_NAMES}",
        )

    risk = None
    if req.include_risk and req.latitude is not None and req.longitude is not None:
        c = req.context
        risk = assess(
            db,
            req.latitude,
            req.longitude,
            RiskContext(
                crop=c.crop if c else "potato",
                crop_stage=c.crop_stage if c else None,
                variety=c.variety if c else None,
                soil_condition=c.soil_condition if c else None,
                district=c.district if c else None,
            ),
        )

    triage = triage_service.evaluate(
        model_available=True,
        predicted_class=req.class_key,
        confidence=req.confidence if req.confidence is not None else 1.0,
        risk=risk,
        detection_count=1 if req.class_key else 0,
    ).to_dict()

    result = advisory_service.generate(
        class_key=req.class_key,
        confidence=req.confidence,
        model_available=True,
        risk=risk,
        triage=triage,
        language=lang,
        query=req.question,
    )
    return AdvisoryResponse(advisory=result, triage=triage, risk=risk, language=lang)


@router.get("/search", summary="Search the IPDM knowledge base directly")
def search(
    q: str = Query(..., min_length=2),
    k: int = Query(5, ge=1, le=20),
    class_key: str | None = Query(None),
) -> dict:
    hits = knowledge_base.search(q, k=k, class_filter=[class_key] if class_key else None)
    return {"query": q, "backend": knowledge_base.status()["backend"], "hits": hits}


@router.get("/status", summary="Advisory pipeline and knowledge base status")
def status() -> dict:
    return advisory_service.pipeline_status()


@router.post("/reindex", summary="Rebuild the knowledge base index after editing the markdown")
def reindex() -> dict:
    return knowledge_base.reindex()
