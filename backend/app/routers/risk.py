"""POST /risk -- proactive, weather-driven forecasting with no image required.

This is the "predict before visible symptoms" half of the problem statement.
A farmer (or a scheduled job for a whole district) can ask "what is my risk
this week" and get an answer built from published agronomic models.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CaseSource
from app.schemas import RiskRequest, RiskResponse
from app.services import risk_models
from app.services.pipeline import run_case
from app.services.risk_engine import RiskContext, assess
from app.services.risk_secondary import secondary_layer
from app.services.translate import normalise_language
from app.services.weather import get_series

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("", response_model=RiskResponse, summary="Weather-based risk forecast")
def risk(req: RiskRequest, db: Session = Depends(get_db)) -> RiskResponse:
    lang = normalise_language(req.language)
    ctx = RiskContext(
        crop=req.crop,
        crop_stage=req.crop_stage,
        variety=req.variety,
        soil_condition=req.soil_condition,
        district=req.district,
    )

    if not req.save_case and not req.include_advisory:
        return RiskResponse(
            assessment=assess(
                db,
                req.latitude,
                req.longitude,
                ctx,
                past_days=req.past_days,
                forecast_days=req.forecast_days,
            ),
            language=lang,
        )

    outcome = run_case(
        db,
        source=CaseSource.RISK_FORECAST,
        detection=None,
        image_path=None,
        lat=req.latitude,
        lon=req.longitude,
        ctx=ctx,
        language=lang,
        village=req.village,
        persist=req.save_case,
        include_advisory=req.include_advisory,
    )
    case = outcome["case"]
    return RiskResponse(
        case_id=case.id if case else None,
        assessment=outcome["risk"],
        advisory=outcome["advisory"] or None,
        triage=outcome["triage"],
        language=lang,
    )


@router.get("/weather", summary="Raw weather series behind the risk models")
def weather(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    past_days: int = Query(7, ge=1, le=30),
    forecast_days: int = Query(3, ge=0, le=5),
    db: Session = Depends(get_db),
) -> dict:
    """Exposed so an officer can audit *why* a risk level was issued."""
    series = get_series(db, latitude, longitude, past_days=past_days, forecast_days=forecast_days)
    days = risk_models.summarise_days(series.points)
    return {
        "summary": series.summary(),
        "warnings": series.warnings,
        "daily": [
            {
                "day": d.day.isoformat(),
                "temp_min": d.temp_min,
                "temp_max": d.temp_max,
                "temp_mean": d.temp_mean,
                "rh_mean": d.rh_mean,
                "hours_rh_above_90": d.hours_rh_above_90,
                "hours_rh_above_75": d.hours_rh_above_75,
                "rainfall_mm": d.rainfall_mm,
            }
            for d in days
        ],
        "hourly_count": len(series.points),
    }


@router.get("/models", summary="Which risk models are active and their thresholds")
def models() -> dict:
    return {
        "primary": {
            "layer": "published agronomic models (deterministic)",
            "models": [
                {
                    "name": "smith_period",
                    "target": "potato_late_blight",
                    "thresholds": {
                        "min_temp_c": risk_models.SMITH_MIN_TEMP_C,
                        "rh_pct": risk_models.SMITH_RH_PCT,
                        "rh_hours": risk_models.SMITH_RH_HOURS,
                        "consecutive_days": risk_models.SMITH_CONSECUTIVE_DAYS,
                    },
                    "reference": "Smith (1956), UK MAFF late blight criteria",
                },
                {
                    "name": "beaumont_period",
                    "target": "potato_late_blight",
                    "thresholds": {
                        "min_temp_c": risk_models.BEAUMONT_MIN_TEMP_C,
                        "rh_pct": risk_models.BEAUMONT_RH_PCT,
                        "hours": risk_models.BEAUMONT_HOURS,
                    },
                    "reference": "Beaumont (1947)",
                },
                {
                    "name": "tomcast_dsv",
                    "target": "potato_early_blight",
                    "thresholds": {
                        "spray_dsv": risk_models.EARLY_BLIGHT_DSV_SPRAY_THRESHOLD,
                        "watch_dsv": risk_models.EARLY_BLIGHT_DSV_WATCH_THRESHOLD,
                    },
                    "reference": "TOMCAST disease severity values",
                },
                *[
                    {
                        "name": f"degree_days:{p.key}",
                        "target": p.key,
                        "thresholds": {
                            "base_temp_c": p.base_temp_c,
                            "dd_per_generation": p.degree_days_per_generation,
                        },
                        "reference": "Single-triangle degree-day accumulation",
                    }
                    for p in risk_models.PEST_MODELS.values()
                ],
            ],
        },
        "secondary": secondary_layer.status(),
    }
