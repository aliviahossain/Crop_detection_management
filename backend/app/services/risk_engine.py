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

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, ReviewStatus, RiskLevel, SensorReading
from app.services import risk_models, taxonomy
from app.services.risk_models import DaySummary
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

# ----------------------------------------------------------------------
# EXPERIMENTAL: canopy airflow modifier
# ----------------------------------------------------------------------
# A coarse, relative in-field airflow level, measured passively from the live
# scanner's video (see frontend/src/lib/canopyAirflow.js). It is NOT a
# calibrated wind sensor.
#
# Rather than nudging the final score, airflow adjusts the *input the fungal
# models actually care about*: leaf-wetness hours. Still air slows canopy drying
# -> dew lingers -> more wet hours; a breeze does the opposite. Those wet hours
# are what the Smith Period (>= 11 h) and TOMCAST (severity cut points) read, so
# this is an agronomically real lever, not cosmetic. Smith/TOMCAST are
# deterministic formulas -- we simply evaluate them a second time on the adjusted
# day summaries; no model, no training, no extra artifact.
#
# Applies ONLY to the moisture-driven fungal blights (late/early), never pests,
# and only to today + forecast days -- one scan cannot honestly rewrite last
# week's observed humidity. The adjustment extends or trims dew only on days that
# already had some (still air prolongs existing wetness; it does not invent dew
# on a bone-dry day).
#
# Honesty guardrail (see _combine_airflow): airflow may freely RAISE concern, but
# a breeze can never weaken a rule that already fired on the observed humidity.
AIRFLOW_WETNESS_DELTA_HOURS: dict[str, int] = {
    "still": 2,    # dew lingers -> add wet hours
    "light": 0,    # neutral, but recorded so it is auditable
    "breezy": -2,  # faster drying -> trim wet hours (pre-trigger only)
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
    # EXPERIMENTAL: 'still' | 'light' | 'breezy' from the passive canopy-airflow
    # estimate. None (the default) means no reading -> no effect at all.
    airflow_level: str | None = None


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


def _airflow_wetness_delta(airflow_level: str | None) -> int | None:
    """Map an EXPERIMENTAL airflow level to a per-day leaf-wetness-hour delta.

    Returns None for an absent or unrecognised level, so callers can skip all
    airflow handling and leave the raw forecast untouched.
    """
    if not airflow_level:
        return None
    return AIRFLOW_WETNESS_DELTA_HOURS.get(airflow_level.strip().lower())


def _adjust_days_for_airflow(
    days: list[DaySummary], delta: int, today: date
) -> list[DaySummary]:
    """Apply the wetness-hour delta to today + forecast days that already had dew.

    Past days are left as observed -- a single scan cannot rewrite last week's
    humidity. Days with no wetness at all are untouched: still air prolongs
    existing dew, it does not conjure dew where the canopy never approached
    saturation (and there is no wetness-temperature to attribute new hours to).
    """
    if not delta:
        return days
    out: list[DaySummary] = []
    for d in days:
        if d.day >= today and d.wetness_mean_temp is not None:
            new_wet = max(0, min(24, d.wetness_hours + delta))
            out.append(replace(d, wetness_hours=new_wet, hours_rh_above_90=new_wet))
        else:
            out.append(d)
    return out


def _combine_airflow(
    base_raw: float, base_adj: float, *, raw_triggered: bool
) -> tuple[float, bool]:
    """Merge the raw and airflow-adjusted base scores under the honesty rule.

    Airflow may freely raise concern (still air), and may ease a *pre-threshold*
    score (a breeze before conditions are met). But it must never weaken a rule
    that already fired on the observed humidity: if the adjustment would lower an
    already-triggered score, we keep the raw score and report it as suppressed.
    """
    if base_adj < base_raw and raw_triggered:
        return base_raw, True
    return base_adj, False


def _airflow_driver(
    level: str,
    delta: int,
    *,
    suppressed: bool,
    outcome_changed: bool,
) -> dict:
    """Auditable, clearly-experimental record of what airflow did (or didn't)."""
    if suppressed:
        why = (
            f"Experimental in-field airflow read '{level}', which would ease fungal "
            "pressure by trimming leaf-wetness hours. Suppressed: a published rule "
            "already fired on the observed humidity, and an experimental signal does "
            "not un-fire a met infection period."
        )
        effect = "neutral"
    elif delta > 0:
        why = (
            f"Experimental in-field airflow read '{level}'. Calm air slows canopy "
            f"drying, so leaf wetness was extended by ~{delta} h on today/forecast "
            "days that already had dew"
            + (
                " -- enough to change a fungal model's outcome."
                if outcome_changed
                else ", raising fungal blight pressure."
            )
        )
        effect = "increases"
    elif delta < 0:
        why = (
            f"Experimental in-field airflow read '{level}'. Moving air dries the "
            f"canopy faster, so leaf wetness was trimmed by ~{-delta} h on "
            "today/forecast days, easing pre-threshold fungal pressure."
        )
        effect = "reduces"
    else:  # light / delta == 0
        why = (
            "Experimental in-field airflow read 'light' -- recorded for transparency; "
            "no material effect on leaf-wetness duration."
        )
        effect = "neutral"

    return {
        "factor": "airflow_experimental",
        "experimental": True,
        "measured_level": level,
        "wetness_hours_delta": delta,
        "applies_to": "today + forecast days with existing dew",
        "effect": effect,
        "changed_model_outcome": outcome_changed,
        "why": why,
    }


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

    # EXPERIMENTAL: an in-field airflow reading adjusts leaf-wetness hours on
    # today + forecast days, then the deterministic fungal models are simply
    # re-evaluated on those adjusted days. None -> no reading -> raw days only.
    airflow_delta = _airflow_wetness_delta(ctx.airflow_level)
    today = datetime.now(timezone.utc).date()
    adj_days = (
        _adjust_days_for_airflow(days, airflow_delta, today)
        if airflow_delta is not None
        else days
    )

    threats: list[ThreatRisk] = []

    # ---------------- Late blight ----------------
    smith = risk_models.smith_period(days)
    beaumont = risk_models.beaumont_period(series.points)
    # Smith is the decision model; Beaumont is the earlier, looser warning.
    lb_base_raw = max(smith.score, beaumont.score * 0.7)

    # Re-run the wetness-driven model on the airflow-adjusted days and merge
    # under the honesty rule. Beaumont reads hourly points, not daily wetness
    # hours, so it is left on the observed data.
    lb_base = lb_base_raw
    lb_airflow_driver: dict | None = None
    smith_adj = smith
    if airflow_delta is not None:
        smith_adj = risk_models.smith_period(adj_days)
        lb_base_adj = max(smith_adj.score, beaumont.score * 0.7)
        lb_base, suppressed = _combine_airflow(
            lb_base_raw, lb_base_adj, raw_triggered=smith.triggered or beaumont.triggered
        )
        lb_airflow_driver = _airflow_driver(
            (ctx.airflow_level or "").strip().lower(),
            airflow_delta,
            suppressed=suppressed,
            outcome_changed=smith_adj.triggered != smith.triggered,
        )

    lb_score, lb_drivers = _apply_modifiers(lb_base, ctx)
    if lb_airflow_driver is not None:
        lb_drivers.append(lb_airflow_driver)

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

    # EXPERIMENTAL airflow: re-run TOMCAST on the wetness-adjusted days, merged
    # under the same honesty rule that a breeze cannot un-fire a met threshold.
    eb_base = dsv.score
    eb_airflow_driver: dict | None = None
    dsv_adj = dsv
    if airflow_delta is not None:
        dsv_adj = risk_models.tomcast_dsv(adj_days)
        eb_base, suppressed = _combine_airflow(
            dsv.score, dsv_adj.score, raw_triggered=dsv.triggered
        )
        eb_airflow_driver = _airflow_driver(
            (ctx.airflow_level or "").strip().lower(),
            airflow_delta,
            suppressed=suppressed,
            outcome_changed=dsv_adj.triggered != dsv.triggered,
        )

    eb_score, eb_drivers = _apply_modifiers(eb_base, ctx)
    if eb_airflow_driver is not None:
        eb_drivers.append(eb_airflow_driver)
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
