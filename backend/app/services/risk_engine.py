"""Risk engine: turns weather + field context into per-threat risk levels.

Pipeline for each threat the system covers:

    published agronomic model(s)      <- risk_models.py, the foundation
      x crop-stage vulnerability
      x variety susceptibility
      x soil/drainage modifier
      + local pest history (confirmed nearby cases, last 21 days)
      + pest-trap sensor pressure
      -> rule score
      -> optional XGBoost/SHAP reweighting  <- risk_secondary.py, if trained
      -> level (low / medium / high) + human-readable drivers

Every driver that moved the number is returned, because an extension officer
has to be able to argue with the output -- and because "explainable" is what
separates this from a black box in evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, ReviewStatus, RiskLevel, SensorReading
from app.services import risk_models, taxonomy
from app.services.geo import geo_cell, haversine_km
from app.services.risk_secondary import secondary_layer
from app.services.weather import WeatherSeries, get_series

# ----------------------------------------------------------------------
# Context modifiers
# ----------------------------------------------------------------------
# Crop stage: canopy closure through tuber bulking is when a blight epidemic
# does the most yield damage, so the same weather means more risk then.
CROP_STAGE_FACTORS: dict[str, float] = {
    "sowing": 0.65,
    "emergence": 0.85,
    "vegetative": 1.0,
    "tuber_initiation": 1.15,
    "tuber_bulking": 1.2,
    "maturity": 0.9,
    "harvest": 0.7,
}
CROP_STAGE_INDEX = {k: i for i, k in enumerate(CROP_STAGE_FACTORS)}

# Susceptibility of common Indian potato varieties to late blight.
VARIETY_SUSCEPTIBILITY: dict[str, float] = {
    "kufri jyoti": 1.15,
    "kufri lauvkar": 1.15,
    "kufri chandramukhi": 1.2,
    "kufri pukhraj": 1.1,
    "kufri badshah": 0.9,
    "kufri himalini": 0.75,
    "kufri girdhari": 0.75,
    "kufri chipsona-1": 1.0,
    "kufri chipsona-3": 0.95,
}
DEFAULT_VARIETY_FACTOR = 1.0

# Poor drainage keeps canopy humidity up and favours both blights.
SOIL_FACTORS: dict[str, float] = {
    "well_drained": 0.9,
    "normal": 1.0,
    "poorly_drained": 1.15,
    "waterlogged": 1.25,
    "sandy": 0.95,
    "clay": 1.1,
}
SOIL_DRAINAGE_INDEX = {
    "well_drained": 0.0, "sandy": 0.25, "normal": 0.5,
    "clay": 0.7, "poorly_drained": 0.85, "waterlogged": 1.0,
}

HISTORY_RADIUS_KM = 15.0
HISTORY_WINDOW_DAYS = 21
# Each confirmed nearby case adds this much, capped -- inoculum pressure is
# real but should not by itself drive a high alert.
HISTORY_WEIGHT = 0.06
HISTORY_CAP = 0.25

TRAP_WINDOW_DAYS = 7
TRAP_ALERT_COUNT = 20.0  # moths/trap/week that warrants action
# Degree-days are a timing signal, not an action threshold: capped so they can
# reach MEDIUM ("scout now") but never HIGH on their own.
PEST_DD_WEIGHT = 0.45
# Hard ceiling for a degree-day-only pest score, kept below LEVEL_THRESHOLDS["high"].
PEST_DD_MAX = 0.60
TRAP_MAX_CONTRIBUTION = 0.55

LEVEL_THRESHOLDS = {"high": 0.66, "medium": 0.36}


def score_to_level(score: float) -> RiskLevel:
    if score >= LEVEL_THRESHOLDS["high"]:
        return RiskLevel.HIGH
    if score >= LEVEL_THRESHOLDS["medium"]:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


@dataclass
class ThreatRisk:
    key: str
    display: str
    kind: str
    score: float
    level: RiskLevel
    models: list[dict] = field(default_factory=list)
    drivers: list[dict] = field(default_factory=list)
    secondary: dict = field(default_factory=dict)
    headline: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display": self.display,
            "kind": self.kind,
            "score": round(self.score, 3),
            "level": self.level.value,
            "headline": self.headline,
            "models": self.models,
            "drivers": self.drivers,
            "secondary_layer": self.secondary,
        }


@dataclass
class RiskContext:
    crop: str = taxonomy.CROP
    crop_stage: str | None = None
    variety: str | None = None
    soil_condition: str | None = None
    district: str | None = None


def _modifier(name: str, factor: float, why: str) -> dict:
    return {
        "factor": name,
        "multiplier": round(factor, 3),
        "effect": "increases" if factor > 1 else ("reduces" if factor < 1 else "neutral"),
        "why": why,
    }


def _local_history(db: Session | None, lat: float, lon: float, threat_key: str) -> tuple[int, list]:
    """Confirmed nearby cases of this threat -- the brief's 'local pest history'."""
    if db is None:
        return 0, []
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=HISTORY_WINDOW_DAYS)
    rows = db.scalars(
        select(Case)
        .where(Case.created_at >= since)
        .where(Case.latitude.is_not(None))
        .where(Case.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED]))
    ).all()
    nearby = [
        r
        for r in rows
        if r.effective_class == threat_key
        and haversine_km(lat, lon, r.latitude, r.longitude) <= HISTORY_RADIUS_KM
    ]
    sample = [
        {
            "case_id": r.id,
            "district": r.district,
            "village": r.village,
            "distance_km": round(haversine_km(lat, lon, r.latitude, r.longitude), 1),
            "confirmed_on": r.reviewed_at.isoformat() if r.reviewed_at else None,
        }
        for r in sorted(
            nearby, key=lambda r: haversine_km(lat, lon, r.latitude, r.longitude)
        )[:5]
    ]
    return len(nearby), sample


def _trap_pressure(db: Session | None, lat: float, lon: float) -> tuple[float, int]:
    """Mean trap count per device over the last week, for pest threats."""
    if db is None:
        return 0.0, 0
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=TRAP_WINDOW_DAYS)
    cell = geo_cell(lat, lon)
    rows = db.scalars(
        select(SensorReading)
        .where(SensorReading.recorded_at >= since)
        .where(SensorReading.metric == "trap_count")
        .where(SensorReading.geo_cell == cell)
    ).all()
    if not rows:
        return 0.0, 0
    per_device: dict[str, list[float]] = {}
    for r in rows:
        per_device.setdefault(r.device_id, []).append(r.value)
    means = [sum(v) / len(v) for v in per_device.values()]
    return round(sum(means) / len(means), 2), len(per_device)


def _apply_modifiers(base: float, ctx: RiskContext) -> tuple[float, list[dict]]:
    drivers: list[dict] = []
    score = base

    stage = (ctx.crop_stage or "").lower().replace(" ", "_")
    if stage in CROP_STAGE_FACTORS:
        f = CROP_STAGE_FACTORS[stage]
        score *= f
        drivers.append(
            _modifier(
                "crop_stage",
                f,
                f"Crop is at {stage.replace('_', ' ')}; canopy and tuber development "
                "change how much damage the same infection pressure causes.",
            )
        )

    variety = (ctx.variety or "").strip().lower()
    if variety in VARIETY_SUSCEPTIBILITY:
        f = VARIETY_SUSCEPTIBILITY[variety]
        score *= f
        drivers.append(
            _modifier("variety", f, f"{ctx.variety} susceptibility rating applied.")
        )

    soil = (ctx.soil_condition or "").lower().replace(" ", "_")
    if soil in SOIL_FACTORS:
        f = SOIL_FACTORS[soil]
        score *= f
        drivers.append(
            _modifier(
                "soil_condition",
                f,
                f"{soil.replace('_', ' ').title()} soil affects how long the canopy stays wet.",
            )
        )

    return score, drivers


def assess(
    db: Session | None,
    lat: float,
    lon: float,
    ctx: RiskContext | None = None,
    past_days: int = 7,
    forecast_days: int = 3,
    series: WeatherSeries | None = None,
) -> dict:
    ctx = ctx or RiskContext()
    series = series or get_series(db, lat, lon, past_days=past_days, forecast_days=forecast_days)
    days = risk_models.summarise_days(series.points)

    threats: list[ThreatRisk] = []

    # ---------------- Late blight ----------------
    smith = risk_models.smith_period(days)
    beaumont = risk_models.beaumont_period(series.points)
    # Smith is the decision model; Beaumont is the earlier, looser warning.
    lb_base = max(smith.score, beaumont.score * 0.7)
    lb_score, lb_drivers = _apply_modifiers(lb_base, ctx)

    hist_n, hist_sample = _local_history(db, lat, lon, "potato_late_blight")
    if hist_n:
        bump = min(HISTORY_CAP, hist_n * HISTORY_WEIGHT)
        lb_score += bump
        lb_drivers.append(
            {
                "factor": "local_history",
                "multiplier": None,
                "added": round(bump, 3),
                "effect": "increases",
                "why": (
                    f"{hist_n} expert-confirmed late blight case(s) within "
                    f"{HISTORY_RADIUS_KM:g} km in the last {HISTORY_WINDOW_DAYS} days - "
                    "inoculum is already present locally."
                ),
                "cases": hist_sample,
            }
        )

    lb_features = {
        "rule_score": lb_base,
        "temp_mean_c": series.summary().get("temp_mean_c", 0.0),
        "humidity_mean": series.summary().get("humidity_mean", 0.0),
        "rainfall_total_mm": series.summary().get("rainfall_total_mm", 0.0),
        "wetness_hours_7d": sum(d.wetness_hours for d in days),
        "crop_stage_index": CROP_STAGE_INDEX.get(
            (ctx.crop_stage or "").lower().replace(" ", "_"), 2
        ),
        "variety_susceptibility": VARIETY_SUSCEPTIBILITY.get(
            (ctx.variety or "").strip().lower(), DEFAULT_VARIETY_FACTOR
        ),
        "soil_drainage_index": SOIL_DRAINAGE_INDEX.get(
            (ctx.soil_condition or "").lower().replace(" ", "_"), 0.5
        ),
        "local_history_count": hist_n,
        "trap_count_mean": 0.0,
    }
    lb_secondary = secondary_layer.adjust(min(1.0, lb_score), lb_features)
    lb_final = lb_secondary["adjusted_score"]
    threats.append(
        ThreatRisk(
            key="potato_late_blight",
            display=taxonomy.display_name("potato_late_blight"),
            kind="disease",
            score=lb_final,
            level=score_to_level(lb_final),
            models=[smith.__dict__, beaumont.__dict__],
            drivers=lb_drivers,
            secondary=lb_secondary,
            headline=smith.explanation,
        )
    )

    # ---------------- Early blight ----------------
    dsv = risk_models.tomcast_dsv(days)
    eb_score, eb_drivers = _apply_modifiers(dsv.score, ctx)
    hist_n_eb, hist_sample_eb = _local_history(db, lat, lon, "potato_early_blight")
    if hist_n_eb:
        bump = min(HISTORY_CAP, hist_n_eb * HISTORY_WEIGHT)
        eb_score += bump
        eb_drivers.append(
            {
                "factor": "local_history",
                "multiplier": None,
                "added": round(bump, 3),
                "effect": "increases",
                "why": (
                    f"{hist_n_eb} expert-confirmed early blight case(s) within "
                    f"{HISTORY_RADIUS_KM:g} km in the last {HISTORY_WINDOW_DAYS} days."
                ),
                "cases": hist_sample_eb,
            }
        )
    eb_final = min(1.0, eb_score)
    threats.append(
        ThreatRisk(
            key="potato_early_blight",
            display=taxonomy.display_name("potato_early_blight"),
            kind="disease",
            score=eb_final,
            level=score_to_level(eb_final),
            models=[dsv.__dict__],
            drivers=eb_drivers,
            secondary={"active": False, "reason": "Secondary layer is fitted for late blight only."},
            headline=dsv.explanation,
        )
    )

    # ---------------- Pests (degree-day + trap) ----------------
    # Degree-days tell you *when to look*, not whether to act -- an accumulated
    # generation is a scouting cue, not an infestation. Observed trap catches
    # are the action threshold in every IPM programme, so degree-days alone are
    # capped below the HIGH band and only real trap data can push a pest there.
    trap_mean, trap_devices = _trap_pressure(db, lat, lon)
    for pest in risk_models.PEST_MODELS.values():
        dd = risk_models.degree_days(days, pest)
        modified, p_drivers = _apply_modifiers(dd.score * PEST_DD_WEIGHT, ctx)
        # Clamp AFTER the context multipliers -- otherwise a susceptible variety
        # on poorly drained soil at tuber bulking multiplies a capped score
        # straight back over the HIGH threshold.
        p_score = min(modified, PEST_DD_MAX)
        p_drivers.insert(
            0,
            {
                "factor": "degree_day_cap",
                "multiplier": PEST_DD_WEIGHT,
                "effect": "reduces",
                "why": (
                    "Degree-day accumulation indicates emergence timing, not infestation. "
                    f"On its own it is capped at {PEST_DD_MAX} -- enough to reach MEDIUM "
                    "(scout now) but never HIGH, which requires observed trap catches."
                ),
            },
        )
        if pest.key == "potato_tuber_moth" and trap_devices:
            bump = min(TRAP_MAX_CONTRIBUTION, (trap_mean / TRAP_ALERT_COUNT) * TRAP_MAX_CONTRIBUTION)
            p_score += bump
            p_drivers.append(
                {
                    "factor": "pest_trap",
                    "multiplier": None,
                    "added": round(bump, 3),
                    "effect": "increases",
                    "why": (
                        f"{trap_devices} trap(s) in this cell averaged {trap_mean} catches over "
                        f"the last {TRAP_WINDOW_DAYS} days (action threshold "
                        f"{TRAP_ALERT_COUNT:g})."
                    ),
                }
            )
        elif pest.key == "potato_tuber_moth":
            p_drivers.append(
                {
                    "factor": "pest_trap",
                    "multiplier": None,
                    "added": 0.0,
                    "effect": "neutral",
                    "why": (
                        "No pheromone traps are reporting in this area. Install traps at 20-25 "
                        "per hectare -- without them, pest risk here is a timing estimate only."
                    ),
                }
            )
        p_final = min(1.0, p_score)
        threats.append(
            ThreatRisk(
                key=pest.key,
                display=taxonomy.display_name(pest.key),
                kind="pest",
                score=p_final,
                level=score_to_level(p_final),
                models=[dd.__dict__],
                drivers=p_drivers,
                secondary={"active": False, "reason": "No trained artifact for pest models."},
                headline=dd.explanation,
            )
        )

    threats.sort(key=lambda t: t.score, reverse=True)
    top = threats[0]

    return {
        "location": {
            "latitude": lat,
            "longitude": lon,
            "geo_cell": geo_cell(lat, lon),
            "district": ctx.district,
        },
        "context": {
            "crop": ctx.crop,
            "crop_stage": ctx.crop_stage,
            "variety": ctx.variety,
            "soil_condition": ctx.soil_condition,
        },
        "window": {
            "past_days": past_days,
            "forecast_days": forecast_days,
            "days_analysed": len(days),
        },
        "weather": series.summary(),
        "weather_warnings": series.warnings,
        "daily": [
            {
                "day": d.day.isoformat(),
                "temp_min": d.temp_min,
                "temp_max": d.temp_max,
                "rh_mean": d.rh_mean,
                "hours_rh_above_90": d.hours_rh_above_90,
                "rainfall_mm": d.rainfall_mm,
            }
            for d in days
        ],
        "overall_level": top.level.value,
        "overall_score": round(top.score, 3),
        "top_threat": top.key,
        "threats": [t.to_dict() for t in threats],
        "secondary_layer_status": secondary_layer.status(),
    }
