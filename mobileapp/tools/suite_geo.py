"""Golden vectors for `backend/app/services/geo.py`.

Why this suite exists at all, given the functions are four lines each:
`geo_cell` uses `math.floor`, and Dart's `~/` and `int` conversions truncate
toward zero instead. Every coordinate in Maharashtra is positive, so a
truncating port would pass every manual test and silently mis-bucket the
southern or western hemisphere the moment the app is used outside India.
That is exactly the class of bug a fixture suite is for.
"""
from __future__ import annotations

from app.services.geo import DEFAULT_CELL_DEG, cell_center, geo_cell, haversine_km

SOURCE = "backend/app/services/geo.py"

# (name, why, lat, lon, size_deg or None for default)
CELL_CASES = [
    ("pune_default_cell", "A real Maharashtra coordinate at the default 0.05 deg grid.", 18.5204, 73.8567, None),
    ("nashik_default_cell", "Second district, to prove cells differ where they should.", 19.9975, 73.7898, None),
    ("exact_grid_boundary", "Lat lands exactly on a cell edge - floor must not round up.", 18.50, 73.85, None),
    ("negative_lat_southern", "Negative latitude: floor(-1.02/0.05) is -21, truncation gives -20.", -1.02, 36.82, None),
    ("negative_lon_western", "Negative longitude, same truncation trap on the other axis.", 40.7128, -74.0060, None),
    ("both_negative", "Both axes negative - the case a truncating port gets wrong twice.", -33.8688, -70.6693, None),
    ("near_zero_positive", "Just above the equator/meridian.", 0.01, 0.01, None),
    ("near_zero_negative", "Just below - must land in a different cell from near_zero_positive.", -0.01, -0.01, None),
    ("coarse_grid", "Non-default cell size, to pin the size prefix in the cell id.", 18.5204, 73.8567, 0.25),
    ("fine_grid", "Fine grid - checks the '%g' formatting of the size prefix.", 18.5204, 73.8567, 0.01),
    ("null_lat", "A case with no coordinates must yield no cell, not a crash.", None, 73.8567, None),
    ("null_lon", "Same on the other axis.", 18.5204, None, None),
]

# (name, why, lat1, lon1, lat2, lon2)
DISTANCE_CASES = [
    ("zero_distance", "Identical points must be exactly 0, not a float artefact.", 18.5204, 73.8567, 18.5204, 73.8567),
    ("pune_to_nashik", "~165 km - the scale the 15 km neighbour radius is judged against.", 18.5204, 73.8567, 19.9975, 73.7898),
    ("one_cell_apart", "Roughly one grid cell - the resolution hotspots work at.", 18.5204, 73.8567, 18.5704, 73.8567),
    ("short_hop_1km", "Sub-cell distance, where the distance-decayed neighbour weight lives.", 18.5204, 73.8567, 18.5294, 73.8567),
    ("antipodal_ish", "Half the planet - guards the asin/sqrt domain at the extreme.", 0.0, 0.0, 0.0, 179.9),
    ("across_equator", "Sign change on latitude.", 1.0, 36.0, -1.0, 36.0),
]


def build() -> dict:
    cases = []

    for name, why, lat, lon, size in CELL_CASES:
        kwargs = {} if size is None else {"size_deg": size}
        cell = geo_cell(lat, lon, **kwargs) if size is not None else geo_cell(lat, lon)
        out = {"cell": cell}
        # cell_center only round-trips for a real cell.
        if cell is not None:
            clat, clon = cell_center(cell)
            out["center_lat"] = round(clat, 9)
            out["center_lon"] = round(clon, 9)
        cases.append(
            {
                "id": name,
                "why": why,
                "fn": "geo_cell",
                "input": {"lat": lat, "lon": lon, "size_deg": size if size is not None else DEFAULT_CELL_DEG},
                "expect": out,
            }
        )

    for name, why, lat1, lon1, lat2, lon2 in DISTANCE_CASES:
        cases.append(
            {
                "id": name,
                "why": why,
                "fn": "haversine_km",
                "input": {"lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2},
                "expect": {"km": round(haversine_km(lat1, lon1, lat2, lon2), 6)},
            }
        )

    return {
        "suite": "geo",
        "source": SOURCE,
        "description": "Grid-cell bucketing and great-circle distance.",
        "cases": cases,
    }
