"""/hotspots -- geospatial clustering of cases for the map and for planning.

Aggregation rule that matters: an *expert-confirmed* case counts fully towards
a hotspot; an unverified model prediction counts at a reduced weight and is
reported separately. Officials should not deploy staff on the strength of
unreviewed AI output, but they also should not be blind to a spike of pending
reports.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Case, ReviewStatus
from app.services import taxonomy
from app.services.geo import DEFAULT_CELL_DEG, cell_center, geo_cell

router = APIRouter(prefix="/hotspots", tags=["hotspots"])

# An unreviewed prediction is worth this fraction of a confirmed case.
UNVERIFIED_WEIGHT = 0.4
# Weighted-count cut-offs for the map's colour ramp.
INTENSITY_BANDS = {"severe": 8.0, "high": 4.0, "moderate": 2.0}


def _intensity(weighted: float) -> str:
    for label, cut in INTENSITY_BANDS.items():
        if weighted >= cut:
            return label
    return "low"


@router.get("", summary="Disease/pest hotspots aggregated on a geo grid")
def hotspots(
    days: int = Query(30, ge=1, le=365),
    crop: str | None = Query(None),
    class_key: str | None = Query(None),
    district: str | None = Query(None),
    cell_size_deg: float = Query(DEFAULT_CELL_DEG, gt=0.005, le=1.0),
    include_unverified: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stmt = (
        select(Case)
        .where(Case.created_at >= since)
        .where(Case.latitude.is_not(None))
        .where(Case.longitude.is_not(None))
    )
    if crop:
        stmt = stmt.where(Case.crop == crop)
    if district:
        stmt = stmt.where(Case.district == district)
    cases = list(db.scalars(stmt).all())

    buckets: dict[str, dict] = {}
    for c in cases:
        label = c.effective_class
        if label is None or label == "potato_healthy":
            continue
        if class_key and label != class_key:
            continue
        verified = c.review_status in {ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED}
        if not verified and not include_unverified:
            continue
        if c.review_status == ReviewStatus.REJECTED:
            continue

        cell = geo_cell(c.latitude, c.longitude, cell_size_deg)
        b = buckets.setdefault(
            cell,
            {
                "geo_cell": cell,
                "districts": set(),
                "villages": set(),
                "confirmed": 0,
                "unverified": 0,
                "by_class": {},
                "latest": None,
            },
        )
        if c.district:
            b["districts"].add(c.district)
        if c.village:
            b["villages"].add(c.village)
        if verified:
            b["confirmed"] += 1
        else:
            b["unverified"] += 1
        cls = b["by_class"].setdefault(label, {"confirmed": 0, "unverified": 0})
        cls["confirmed" if verified else "unverified"] += 1
        if b["latest"] is None or c.created_at > b["latest"]:
            b["latest"] = c.created_at

    features = []
    for cell, b in buckets.items():
        lat, lon = cell_center(cell)
        weighted = b["confirmed"] + UNVERIFIED_WEIGHT * b["unverified"]
        dominant = max(
            b["by_class"].items(),
            key=lambda kv: kv[1]["confirmed"] * 2 + kv[1]["unverified"],
        )[0]
        features.append(
            {
                "geo_cell": cell,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "cell_size_deg": cell_size_deg,
                "confirmed_cases": b["confirmed"],
                "unverified_cases": b["unverified"],
                "weighted_count": round(weighted, 2),
                "intensity": _intensity(weighted),
                "dominant_class": dominant,
                "dominant_display": taxonomy.display_name(dominant),
                "by_class": b["by_class"],
                "districts": sorted(b["districts"]),
                "villages": sorted(b["villages"])[:10],
                "latest_case_at": b["latest"].isoformat() if b["latest"] else None,
            }
        )
    features.sort(key=lambda f: f["weighted_count"], reverse=True)

    return {
        "window_days": days,
        "cell_size_deg": cell_size_deg,
        "unverified_weight": UNVERIFIED_WEIGHT,
        "total_cells": len(features),
        "total_confirmed": sum(f["confirmed_cases"] for f in features),
        "total_unverified": sum(f["unverified_cases"] for f in features),
        "cells": features,
    }


@router.get("/geojson", summary="Same aggregation as a GeoJSON FeatureCollection")
def hotspots_geojson(
    days: int = Query(30, ge=1, le=365),
    crop: str | None = Query(None),
    class_key: str | None = Query(None),
    district: str | None = Query(None),
    cell_size_deg: float = Query(DEFAULT_CELL_DEG, gt=0.005, le=1.0),
    db: Session = Depends(get_db),
) -> dict:
    """Leaflet and QGIS both eat this directly, which makes the data reusable
    outside our own dashboard."""
    data = hotspots(
        days=days,
        crop=crop,
        class_key=class_key,
        district=district,
        cell_size_deg=cell_size_deg,
        include_unverified=True,
        db=db,
    )
    half = cell_size_deg / 2
    features = []
    for c in data["cells"]:
        lat, lon = c["latitude"], c["longitude"]
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [lon - half, lat - half],
                            [lon + half, lat - half],
                            [lon + half, lat + half],
                            [lon - half, lat + half],
                            [lon - half, lat - half],
                        ]
                    ],
                },
                "properties": {k: v for k, v in c.items() if k != "by_class"},
            }
        )
    return {"type": "FeatureCollection", "features": features}
