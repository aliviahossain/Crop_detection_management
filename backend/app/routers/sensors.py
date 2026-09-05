"""/sensors -- pest-trap and field-sensor ingestion.

Kept deliberately schema-light so a low-cost ESP32 trap counter, a manual entry
by a Krishi Sahayak, or a bulk CSV upload from a CROPSAP surveyor all use the
same endpoint. Readings feed straight into the pest side of the risk engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SensorReading
from app.schemas import SensorBatchIn, SensorReadingIn, SensorReadingOut
from app.services.geo import cell_center, geo_cell

router = APIRouter(prefix="/sensors", tags=["sensors"])


def _to_row(r: SensorReadingIn) -> SensorReading:
    recorded = r.recorded_at or datetime.now(timezone.utc)
    if recorded.tzinfo is not None:
        recorded = recorded.astimezone(timezone.utc).replace(tzinfo=None)
    return SensorReading(
        device_id=r.device_id,
        device_type=r.device_type,
        metric=r.metric,
        value=r.value,
        unit=r.unit,
        crop=r.crop,
        district=r.district,
        latitude=r.latitude,
        longitude=r.longitude,
        geo_cell=geo_cell(r.latitude, r.longitude),
        recorded_at=recorded,
        raw=r.raw,
    )


@router.post("", response_model=SensorReadingOut, summary="Ingest one sensor/trap reading")
def ingest(reading: SensorReadingIn, db: Session = Depends(get_db)) -> SensorReading:
    row = _to_row(reading)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/batch", summary="Ingest a batch of readings")
def ingest_batch(batch: SensorBatchIn, db: Session = Depends(get_db)) -> dict:
    rows = [_to_row(r) for r in batch.readings]
    db.add_all(rows)
    db.commit()
    return {"ingested": len(rows)}


@router.get("", response_model=list[SensorReadingOut], summary="List recent readings")
def list_readings(
    device_id: str | None = Query(None),
    metric: str | None = Query(None),
    district: str | None = Query(None),
    days: int = Query(14, ge=1, le=180),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[SensorReading]:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stmt = select(SensorReading).where(SensorReading.recorded_at >= since)
    if device_id:
        stmt = stmt.where(SensorReading.device_id == device_id)
    if metric:
        stmt = stmt.where(SensorReading.metric == metric)
    if district:
        stmt = stmt.where(SensorReading.district == district)
    stmt = stmt.order_by(SensorReading.recorded_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/summary", summary="Trap pressure per geo cell (feeds the hotspot map)")
def summary(
    metric: str = Query("trap_count"),
    days: int = Query(7, ge=1, le=90),
    include_demo: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stmt = (
        select(
            SensorReading.geo_cell,
            SensorReading.district,
            func.count(SensorReading.id),
            func.avg(SensorReading.value),
            func.max(SensorReading.value),
            func.count(func.distinct(SensorReading.device_id)),
        )
        .where(SensorReading.recorded_at >= since)
        .where(SensorReading.metric == metric)
        .where(SensorReading.geo_cell.is_not(None))
        .group_by(SensorReading.geo_cell, SensorReading.district)
    )
    if not include_demo:
        stmt = stmt.where(SensorReading.device_id.notlike("demo-trap-%"))
    rows = db.execute(stmt).all()

    cells = []
    for cell, district, count, avg_v, max_v, devices in rows:
        lat, lon = cell_center(cell)
        cells.append(
            {
                "geo_cell": cell,
                "district": district,
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "readings": count,
                "devices": devices,
                "mean_value": round(float(avg_v or 0), 2),
                "max_value": round(float(max_v or 0), 2),
            }
        )
    cells.sort(key=lambda c: c["mean_value"], reverse=True)
    return {"metric": metric, "window_days": days, "cells": cells}
