"""GET /home/overview -- the farmer's home-screen traffic light.

One call, no image and no side effects: it combines the weather-driven scouting
forecast with cross-farm outbreak pressure into a single "walk your field today?"
answer. See ``services/home_overview.py`` for the logic and its honesty rules.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.home_overview import build_overview
from app.services.risk_engine import RiskContext

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/overview", summary="Proactive home alert: weather + nearby outbreaks")
def overview(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    crop: str = Query("potato"),
    crop_stage: str | None = Query(None),
    variety: str | None = Query(None),
    soil_condition: str | None = Query(None),
    district: str | None = Query(None),
    include_demo: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    ctx = RiskContext(
        crop=crop,
        crop_stage=crop_stage,
        variety=variety,
        soil_condition=soil_condition,
        district=district,
    )
    return build_overview(db, latitude, longitude, ctx, include_demo=include_demo)
