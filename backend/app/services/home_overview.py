"""Farmer home overview -- the "should I walk my field today?" answer.

This binds two proactive signals into one simple traffic light a farmer sees on
opening the app, without having to run a scan or read a dashboard:

* **Proactive scouting alert** (weather half). The published agronomic models in
  ``risk_engine.assess`` already predict blight infection *before* a symptom is
  visible. Here we turn that forecast into an instruction -- "check your plants
  this morning" -- instead of a number the farmer has to go find.

* **Cross-farm outbreak pressure** (neighbour half). *Phytophthora infestans*
  spreads by wind-dispersed sporangia, so an expert-confirmed late blight case a
  short distance upwind raises a farmer's risk *before they have detected
  anything themselves*. We compute a distance-decayed infection pressure from
  nearby CONFIRMED cases and let it raise the alert.

Two honesty guardrails, consistent with the rest of the system:

1. **Never fabricate a detection.** Outbreak pressure can only RAISE the scouting
   urgency (nudge the farmer to look); it never claims their crop is infected and
   it is capped -- exactly like the airflow signal and the XGBoost layer, which
   can refine but never override a validated agronomic rule.
2. **No numeric double-count.** The engine's own ``assess`` already folds a
   confirmed-history bump into its score over a wide 15 km radius. This module
   does not add to that number; it computes a *tighter*, distance-decayed
   neighbour signal and combines it with the weather forecast at the categorical
   (traffic-light) level by taking the more urgent of the two. So a farmer with
   calm local weather but confirmed blight 1.5 km away is still moved off green.

Everything returned is machine-readable (levels, counts, booleans, threat keys)
so the frontend renders every farmer-facing word through its own i18n catalog in
Marathi / Hindi / Bengali / English -- the server localises nothing here.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Case, ReviewStatus
from app.services import taxonomy
from app.services.geo import geo_cell, haversine_km
from app.services.risk_engine import RiskContext, assess

# Seeded demo cases carry this model_version; real detections never do. Kept in
# lockstep with the same marker in routers/hotspots.py so the home page's
# demo/live switch drops exactly the rows the map's switch does.
DEMO_MODEL_VERSION = "demo-seed"

# ----------------------------------------------------------------------
# Cross-farm propagation parameters
# ----------------------------------------------------------------------
# Look-back for nearby confirmations. Aligned with the hotspot map's own 30-day
# default so the home page and the map tell the same story from the same cases;
# an epidemic's inoculum stays relevant across this window. Recency still matters
# for *urgency*, which the tight close-band below drives.
PROPAGATION_WINDOW_DAYS = 30
# Outer cutoff for any neighbour signal, and the inner "close" band for
# wind-dispersed spread that a single case is enough to act on.
PROPAGATION_RADIUS_KM = 5.0
PROPAGATION_CLOSE_KM = 2.0
# Gaussian decay scale: a case at this distance contributes ~37% of a case next
# door. Matches the steep fall-off of local sporangia deposition.
PROPAGATION_DECAY_SCALE_KM = 2.0
# Sum of decayed weights that saturates pressure to 1.0 (~three close cases).
PRESSURE_SATURATION = 3.0
# The most this neighbour prior may shift a risk estimate, mirroring the ±0.20
# ceiling the secondary XGBoost layer is held to. Exposed for transparency; the
# traffic light uses the level, not this number.
PROPAGATION_PRIOR_CAP = 0.20

# Pressure band cut-offs.
PRESSURE_HIGH = 0.50
PRESSURE_ELEVATED = 0.15

# "Your area" for the most-common-disease breakdown -- wider than the tight
# outbreak-pressure radius, matching the engine's 15 km local-history reach, so it
# answers "what is circulating around me" rather than "right next to me".
AREA_RADIUS_KM = 15.0

# The disease classes a farmer can see and act on (healthy is not a disease).
_DISEASES = ("potato_late_blight", "potato_early_blight")

# Urgency ranking shared by both halves so they can be combined by max().
_URGENCY_RANK = {"calm": 0, "watch": 1, "act": 2}
_RANK_URGENCY = {v: k for k, v in _URGENCY_RANK.items()}

# The fungal blights -- the threats a morning photo of the canopy actually helps
# with (a pest needs a trap, not a leaf close-up).
_FUNGAL = {"potato_late_blight", "potato_early_blight"}


def _since(days: int) -> datetime:
    # Mirror the engine's naive-UTC comparison against Case.created_at.
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


def nearby_outbreak_pressure(
    db: Session | None,
    lat: float,
    lon: float,
    threat_key: str = "potato_late_blight",
    include_demo: bool = True,
) -> dict:
    """Distance-decayed infection pressure from nearby cases of ``threat_key``.

    Confirmed (expert-validated) cases drive the pressure and the alert level.
    Unconfirmed reports are counted and surfaced separately -- honest, because an
    unreviewed model guess should not by itself raise a neighbour's alarm, but a
    cluster of pending reports is still worth showing.

    ``include_demo`` mirrors the map and dashboard switch: when False, seeded
    demo cases are dropped and only real field reports remain.
    """
    empty = {
        "threat_key": threat_key,
        "threat_display": taxonomy.display_name(threat_key),
        "confirmed_count": 0,
        "reported_count": 0,
        "close_confirmed_count": 0,
        "nearest_km": None,
        "villages": 0,
        "pressure": 0.0,
        "prior_shift": 0.0,
        "level": "none",
        "radius_km": PROPAGATION_RADIUS_KM,
        "close_radius_km": PROPAGATION_CLOSE_KM,
        "window_days": PROPAGATION_WINDOW_DAYS,
        "summary": "No nearby cases reported in the last 30 days.",
    }
    if db is None:
        return empty

    stmt = (
        select(Case)
        .where(Case.created_at >= _since(PROPAGATION_WINDOW_DAYS))
        .where(Case.latitude.is_not(None))
        .where(Case.longitude.is_not(None))
        .where(Case.review_status != ReviewStatus.REJECTED)
    )
    if not include_demo:
        # Keep real cases, including those whose model_version is NULL (a plain
        # ``!=`` would silently drop NULLs too).
        stmt = stmt.where(
            or_(Case.model_version.is_(None), Case.model_version != DEMO_MODEL_VERSION)
        )
    rows = db.scalars(stmt).all()

    confirmed: list[tuple[float, Case]] = []
    reported = 0
    for r in rows:
        if r.effective_class != threat_key:
            continue
        d = haversine_km(lat, lon, r.latitude, r.longitude)
        if d > PROPAGATION_RADIUS_KM:
            continue
        if r.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}:
            confirmed.append((d, r))
        else:
            reported += 1

    if not confirmed and not reported:
        return empty

    pressure = min(
        1.0,
        sum(math.exp(-((d / PROPAGATION_DECAY_SCALE_KM) ** 2)) for d, _ in confirmed)
        / PRESSURE_SATURATION,
    )
    close = sum(1 for d, _ in confirmed if d <= PROPAGATION_CLOSE_KM)
    villages = {r.village for _, r in confirmed if r.village}

    if not confirmed:
        level = "low"  # unconfirmed reports only
    elif pressure >= PRESSURE_HIGH or close >= 2:
        level = "high"
    elif pressure >= PRESSURE_ELEVATED or close >= 1:
        level = "elevated"
    else:
        level = "low"

    nearest = round(min(d for d, _ in confirmed), 1) if confirmed else None
    display = taxonomy.display_name(threat_key)
    if confirmed:
        summary = (
            f"{len(confirmed)} confirmed {display.lower()} case(s) within "
            f"{PROPAGATION_RADIUS_KM:g} km in the last {PROPAGATION_WINDOW_DAYS} days"
            + (f" (nearest {nearest} km)." if nearest is not None else ".")
        )
    else:
        summary = (
            f"{reported} unconfirmed {display.lower()} report(s) nearby, awaiting "
            "expert review."
        )

    return {
        "threat_key": threat_key,
        "threat_display": display,
        "confirmed_count": len(confirmed),
        "reported_count": reported,
        "close_confirmed_count": close,
        "nearest_km": nearest,
        "villages": len(villages),
        "pressure": round(pressure, 3),
        "prior_shift": round(pressure * PROPAGATION_PRIOR_CAP, 3),
        "level": level,
        "radius_km": PROPAGATION_RADIUS_KM,
        "close_radius_km": PROPAGATION_CLOSE_KM,
        "window_days": PROPAGATION_WINDOW_DAYS,
        "summary": summary,
    }


def prevalent_disease(
    db: Session | None,
    lat: float,
    lon: float,
    include_demo: bool = True,
) -> dict:
    """Which disease is most common around the farmer, from confirmed + reported
    cases within ``AREA_RADIUS_KM`` over the propagation window.

    Uses the same confirmed-weighted-above-unverified rule the hotspot map uses
    (a confirmed case counts double a pending one), so the home page and the map
    agree on what dominates. ``include_demo`` follows the live/demo switch.
    """
    empty = {
        "dominant_class": None,
        "dominant_display": None,
        "total_confirmed": 0,
        "total_reported": 0,
        "by_class": {},
        "radius_km": AREA_RADIUS_KM,
        "window_days": PROPAGATION_WINDOW_DAYS,
    }
    if db is None:
        return empty

    stmt = (
        select(Case)
        .where(Case.created_at >= _since(PROPAGATION_WINDOW_DAYS))
        .where(Case.latitude.is_not(None))
        .where(Case.longitude.is_not(None))
        .where(Case.review_status != ReviewStatus.REJECTED)
    )
    if not include_demo:
        stmt = stmt.where(
            or_(Case.model_version.is_(None), Case.model_version != DEMO_MODEL_VERSION)
        )

    by_class: dict[str, dict[str, int]] = {}
    total_confirmed = 0
    total_reported = 0
    for r in db.scalars(stmt).all():
        label = r.effective_class
        if label not in _DISEASES:
            continue
        if haversine_km(lat, lon, r.latitude, r.longitude) > AREA_RADIUS_KM:
            continue
        verified = r.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}
        bucket = by_class.setdefault(label, {"confirmed": 0, "reported": 0})
        if verified:
            bucket["confirmed"] += 1
            total_confirmed += 1
        else:
            bucket["reported"] += 1
            total_reported += 1

    if not by_class:
        return empty

    # Confirmed cases weigh double an unreviewed report, exactly as the map ranks
    # a cell's dominant class.
    dominant = max(
        by_class.items(),
        key=lambda kv: kv[1]["confirmed"] * 2 + kv[1]["reported"],
    )[0]

    return {
        "dominant_class": dominant,
        "dominant_display": taxonomy.display_name(dominant),
        "total_confirmed": total_confirmed,
        "total_reported": total_reported,
        "by_class": by_class,
        "radius_km": AREA_RADIUS_KM,
        "window_days": PROPAGATION_WINDOW_DAYS,
    }


def _level_to_urgency(level: str) -> str:
    """Overall risk level -> what the farmer should do."""
    if level == "high":
        return "act"
    if level == "medium":
        return "watch"
    return "calm"


def scouting_recommendation(assessment: dict) -> dict:
    """Turn the weather-driven risk assessment into a scouting instruction.

    ``assess`` returns threats already sorted by score. We take the overall level
    for urgency, and pick the top *fungal* disease for the "photograph the
    canopy" guidance -- a morning leaf photo is the right action for blight, not
    for a pest that needs a pheromone trap.
    """
    threats = assessment.get("threats", [])
    overall_level = assessment.get("overall_level", "low")
    urgency = _level_to_urgency(overall_level)

    disease = next((t for t in threats if t.get("key") in _FUNGAL), None)
    top = threats[0] if threats else None
    focus = disease or top

    # Which published models actually fired -- the honest "why" behind the alert.
    fired: list[str] = []
    if disease:
        for m in disease.get("models", []):
            if m.get("triggered"):
                fired.append(m.get("name"))

    fungal_focus = bool(focus and focus.get("key") in _FUNGAL)
    # Photograph in the morning while dew and fresh sporulation make lesions
    # easiest to see -- only worth saying when the farmer should act today.
    time_hint = "this_morning" if urgency == "act" and fungal_focus else None

    return {
        "urgency": urgency,
        "should_scout": urgency in {"watch", "act"},
        "time_hint": time_hint,
        "overall_level": overall_level,
        "overall_score": assessment.get("overall_score"),
        "focus_threat": focus.get("key") if focus else None,
        "focus_display": focus.get("display") if focus else None,
        "focus_kind": focus.get("kind") if focus else None,
        "fired_models": fired,
    }


def build_overview(
    db: Session | None,
    lat: float,
    lon: float,
    ctx: RiskContext | None = None,
    include_demo: bool = True,
) -> dict:
    """Everything the farmer home page needs, in one call.

    ``include_demo`` toggles the seeded demo cases in the neighbour signal, the
    same live/demo switch the map and dashboard carry -- so a walkthrough can
    show a populated alert, then flip to real-only. The weather half is
    synthetic-or-real by API key (as everywhere), independent of this switch.
    """
    ctx = ctx or RiskContext()
    assessment = assess(db, lat, lon, ctx)
    scouting = scouting_recommendation(assessment)
    nearby = nearby_outbreak_pressure(db, lat, lon, include_demo=include_demo)
    prevalent = prevalent_disease(db, lat, lon, include_demo=include_demo)

    scout_rank = _URGENCY_RANK[scouting["urgency"]]
    # A confirmed outbreak in the close band is a scout-today trigger on its own,
    # regardless of the farmer's own weather -- that is the whole point of
    # propagation: raise risk before they have detected anything.
    nearby_rank = {"none": 0, "low": 1, "elevated": 2, "high": 2}[nearby["level"]]

    status = _RANK_URGENCY[max(scout_rank, nearby_rank)]
    # Attribute the headline to whichever half is driving, so the farmer sees the
    # real reason (a neighbour's outbreak vs. their own weather).
    primary_reason = (
        "nearby_outbreak"
        if nearby_rank >= scout_rank and nearby["level"] != "none"
        else "weather"
    )

    # Photograph in the morning while dew and fresh sporulation make lesions
    # easiest to see. Worth saying whenever the farmer should act today on a
    # fungal threat -- whether that urgency came from their own weather or from a
    # confirmed blight (always fungal) upwind. A pest, needing a trap, gets no
    # morning-photo hint.
    fungal_driver = primary_reason == "nearby_outbreak" or scouting["focus_kind"] == "disease"
    time_hint = "this_morning" if status == "act" and fungal_driver else None

    weather = assessment.get("weather", {})
    data_thin = bool(weather.get("synthetic")) or bool(
        assessment.get("weather_warnings")
    )

    return {
        "status": status,  # calm | watch | act -- the traffic light
        "action": {"act": "take_photo", "watch": "watch", "calm": "none"}[status],
        "time_hint": time_hint,
        "primary_reason": primary_reason,
        "include_demo": include_demo,
        "data_thin": data_thin,
        "location": assessment.get("location", {}),
        "scouting": scouting,
        "nearby": nearby,
        "prevalent": prevalent,
        "weather": {
            "temp_mean_c": weather.get("temp_mean_c"),
            "humidity_mean": weather.get("humidity_mean"),
            "synthetic": bool(weather.get("synthetic")),
        },
        "risk_level": assessment.get("overall_level"),
        "top_threat": assessment.get("top_threat"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "geo_cell": geo_cell(lat, lon),
    }
