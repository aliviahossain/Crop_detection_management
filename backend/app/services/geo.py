"""Geo helpers.

Hotspot aggregation uses a fixed-size lat/lon grid rather than a clustering
library: cells are stable across queries (so a hotspot keeps its identity as
cases accumulate), cheap to index in SQL, and trivially explainable to an
agriculture officer -- "this 5km square has 14 confirmed late blight cases".
"""
from __future__ import annotations

import math

# ~0.05 deg latitude is ~5.5 km. Coarse enough to form clusters from sparse
# field reports, fine enough to point an extension officer at a village group.
DEFAULT_CELL_DEG = 0.05
EARTH_RADIUS_KM = 6371.0


def geo_cell(lat: float | None, lon: float | None, size_deg: float = DEFAULT_CELL_DEG) -> str | None:
    if lat is None or lon is None:
        return None
    lat_i = math.floor(lat / size_deg)
    lon_i = math.floor(lon / size_deg)
    return f"{size_deg:g}:{lat_i}:{lon_i}"


def cell_center(cell: str) -> tuple[float, float]:
    size_s, lat_s, lon_s = cell.split(":")
    size = float(size_s)
    return (int(lat_s) + 0.5) * size, (int(lon_s) + 0.5) * size


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
