"""Weather access for the risk engine.

Why this shape:

* The agronomic risk models (Smith Period, degree-days) need an *hourly-ish
  series over consecutive days*, not a single current reading.
* OpenWeatherMap's free tier gives current conditions + a 5-day/3-hour
  forecast, but **not** history. So past hours come from our own
  `weather_observations` cache, which fills up as the system runs.
* When the cache is cold (fresh install, demo laptop, no API key) we fall back
  to a deterministic synthetic series and label it `synthetic: true` all the
  way up into the API response. We never silently pass fake weather off as
  real -- the officer dashboard shows the data-source badge.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import WeatherObservation
from app.services.geo import geo_cell

log = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"


@dataclass
class HourPoint:
    ts: datetime
    temp_c: float
    humidity: float
    rainfall_mm: float
    is_forecast: bool = False


@dataclass
class WeatherSeries:
    lat: float
    lon: float
    points: list[HourPoint]
    source: str
    synthetic: bool
    warnings: list[str]

    def past(self, now: datetime | None = None) -> list[HourPoint]:
        now = now or datetime.now(timezone.utc)
        return [p for p in self.points if p.ts <= now]

    def future(self, now: datetime | None = None) -> list[HourPoint]:
        now = now or datetime.now(timezone.utc)
        return [p for p in self.points if p.ts > now]

    def summary(self) -> dict:
        if not self.points:
            return {}
        temps = [p.temp_c for p in self.points]
        hums = [p.humidity for p in self.points]
        return {
            "temp_min_c": round(min(temps), 1),
            "temp_max_c": round(max(temps), 1),
            "temp_mean_c": round(sum(temps) / len(temps), 1),
            "humidity_mean": round(sum(hums) / len(hums), 1),
            "rainfall_total_mm": round(sum(p.rainfall_mm for p in self.points), 1),
            "hours": len(self.points),
            "source": self.source,
            "synthetic": self.synthetic,
        }


# ----------------------------------------------------------------------
# Synthetic fallback
# ----------------------------------------------------------------------
def _seeded_unit(*parts: object) -> float:
    """Deterministic pseudo-random in [0,1). Same inputs -> same weather, so
    demos and tests are reproducible."""
    raw = "|".join(str(p) for p in parts).encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF


def synth_series(
    lat: float, lon: float, start: datetime, hours: int, now: datetime
) -> list[HourPoint]:
    """Plausible Deccan-plateau rabi-season weather.

    Deliberately parameterised so late-blight-conducive spells (cool nights,
    high RH) actually occur -- otherwise the risk engine has nothing to detect
    in a demo.
    """
    pts: list[HourPoint] = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        day_seed = _seeded_unit(round(lat, 2), round(lon, 2), ts.date().isoformat())
        hour_seed = _seeded_unit(round(lat, 2), round(lon, 2), ts.isoformat())

        # Diurnal cycle: min ~05:00, max ~15:00
        phase = math.cos((ts.hour - 15) / 24 * 2 * math.pi)
        base_mean = 20.0 + 4.0 * day_seed  # 20-24 C daily mean
        amplitude = 5.0 + 3.0 * day_seed  # 5-8 C swing
        temp = base_mean + amplitude * phase + (hour_seed - 0.5) * 1.2

        # RH runs opposite to temperature; some days are humid spells.
        humid_day = day_seed > 0.55
        base_rh = 78.0 if humid_day else 58.0
        humidity = base_rh - 18.0 * phase + (hour_seed - 0.5) * 6.0
        humidity = max(25.0, min(99.0, humidity))

        rain = 0.0
        if humid_day and hour_seed > 0.88:
            rain = round(2.0 + 6.0 * hour_seed, 1)

        pts.append(
            HourPoint(
                ts=ts,
                temp_c=round(temp, 1),
                humidity=round(humidity, 1),
                rainfall_mm=rain,
                is_forecast=ts > now,
            )
        )
    return pts


# ----------------------------------------------------------------------
# Live provider
# ----------------------------------------------------------------------
def _parse_owm_forecast(payload: dict, now: datetime) -> list[HourPoint]:
    """OWM 5-day/3-hour forecast -> hourly points by linear interpolation.

    The agronomic models count *hours* above a threshold, so a 3-hourly series
    would under-count. Interpolating is the standard workaround and is stated
    in the response metadata.
    """
    raw: list[HourPoint] = []
    for entry in payload.get("list", []):
        ts = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
        main = entry.get("main", {})
        rain = entry.get("rain", {}).get("3h", 0.0)
        raw.append(
            HourPoint(
                ts=ts,
                temp_c=float(main.get("temp", 0.0)),
                humidity=float(main.get("humidity", 0.0)),
                rainfall_mm=float(rain) / 3.0,
                is_forecast=ts > now,
            )
        )
    if len(raw) < 2:
        return raw

    hourly: list[HourPoint] = []
    for a, b in zip(raw, raw[1:]):
        gap = int((b.ts - a.ts).total_seconds() // 3600) or 1
        for step in range(gap):
            frac = step / gap
            ts = a.ts + timedelta(hours=step)
            hourly.append(
                HourPoint(
                    ts=ts,
                    temp_c=round(a.temp_c + (b.temp_c - a.temp_c) * frac, 2),
                    humidity=round(a.humidity + (b.humidity - a.humidity) * frac, 2),
                    rainfall_mm=round(a.rainfall_mm, 3),
                    is_forecast=ts > now,
                )
            )
    hourly.append(raw[-1])
    return hourly


def _fetch_owm(lat: float, lon: float, now: datetime) -> tuple[list[HourPoint], list[str]]:
    warnings: list[str] = []
    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.openweather_api_key,
        "units": "metric",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(OWM_FORECAST_URL, params=params)
            resp.raise_for_status()
            points = _parse_owm_forecast(resp.json(), now)
            if points:
                warnings.append(
                    "Forecast interpolated from OpenWeatherMap 3-hourly steps to hourly."
                )
            return points, warnings
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("Weather provider call failed (%s); falling back to synthetic feed", exc)
        warnings.append(f"Weather provider unavailable ({type(exc).__name__}); using synthetic feed.")
        return [], warnings


# ----------------------------------------------------------------------
# Cache read/write
# ----------------------------------------------------------------------
def _load_cached(db: Session, cell: str, since: datetime) -> list[HourPoint]:
    rows = db.scalars(
        select(WeatherObservation)
        .where(WeatherObservation.geo_cell == cell)
        .where(WeatherObservation.observed_at >= since.replace(tzinfo=None))
        .where(WeatherObservation.is_forecast.is_(False))
        .order_by(WeatherObservation.observed_at)
    ).all()
    return [
        HourPoint(
            ts=r.observed_at.replace(tzinfo=timezone.utc),
            temp_c=r.temp_c,
            humidity=r.humidity,
            rainfall_mm=r.rainfall_mm,
            is_forecast=False,
        )
        for r in rows
    ]


def _persist(db: Session, cell: str, points: list[HourPoint], source: str) -> None:
    """Cache observed (non-forecast) hours so tomorrow's Smith Period check has
    real history to look back on."""
    if not points:
        return
    existing = {
        r.observed_at
        for r in db.scalars(
            select(WeatherObservation)
            .where(WeatherObservation.geo_cell == cell)
            .where(WeatherObservation.observed_at >= min(p.ts for p in points).replace(tzinfo=None))
        ).all()
    }
    added = 0
    for p in points:
        if p.is_forecast:
            continue
        naive = p.ts.replace(tzinfo=None, minute=0, second=0, microsecond=0)
        if naive in existing:
            continue
        db.add(
            WeatherObservation(
                geo_cell=cell,
                observed_at=naive,
                temp_c=p.temp_c,
                humidity=p.humidity,
                rainfall_mm=p.rainfall_mm,
                source=source,
                is_forecast=False,
            )
        )
        existing.add(naive)
        added += 1
    if added:
        db.commit()


def get_series(
    db: Session | None,
    lat: float,
    lon: float,
    past_days: int = 7,
    forecast_days: int = 3,
    now: datetime | None = None,
) -> WeatherSeries:
    """Assemble a continuous hourly series spanning past_days back to
    forecast_days ahead, mixing cache + live provider + synthetic backfill."""
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=past_days)
    total_hours = (past_days + forecast_days) * 24
    cell = geo_cell(lat, lon) or "0:0:0"

    warnings: list[str] = []
    live: list[HourPoint] = []
    cached: list[HourPoint] = []

    if settings.openweather_api_key:
        live, w = _fetch_owm(lat, lon, now)
        warnings.extend(w)
    else:
        warnings.append(
            "OPENWEATHER_API_KEY not set - running on the deterministic synthetic feed."
        )

    if db is not None:
        cached = _load_cached(db, cell, start)
        if live and db is not None:
            _persist(db, cell, live, settings.weather_provider)

    by_hour: dict[datetime, HourPoint] = {}
    for p in cached:
        by_hour[p.ts.replace(minute=0, second=0, microsecond=0)] = p
    for p in live:
        by_hour[p.ts.replace(minute=0, second=0, microsecond=0)] = p

    real_hours = len(by_hour)
    synthetic_used = False
    for p in synth_series(lat, lon, start, total_hours, now):
        key = p.ts.replace(minute=0, second=0, microsecond=0)
        if key not in by_hour:
            by_hour[key] = p
            synthetic_used = True

    if synthetic_used and real_hours:
        warnings.append(
            f"{real_hours} of {len(by_hour)} hours came from real observations; "
            "the remainder is synthetic backfill (no free historical weather API)."
        )

    points = [by_hour[k] for k in sorted(by_hour)]
    if real_hours == 0:
        source = "synthetic"
    elif synthetic_used:
        source = f"{settings.weather_provider}+synthetic"
    else:
        source = settings.weather_provider

    return WeatherSeries(
        lat=lat,
        lon=lon,
        points=points,
        source=source,
        synthetic=real_hours == 0,
        warnings=warnings,
    )
