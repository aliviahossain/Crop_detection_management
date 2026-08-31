"""CropGuard Maharashtra -- FastAPI application entry point.

SIH 2026 PS26131: Crop Disease & Pest Detection System.

Run:  uvicorn app.main:app --reload --app-dir backend
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import (
    advisory,
    dashboard,
    detect,
    followup,
    hotspots,
    meta,
    review,
    risk,
    sensors,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
log = logging.getLogger("cropguard")

DESCRIPTION = """
Farmer- and extension-worker-facing crop health system for **potato**
(early blight, late blight, healthy).

* `POST /detect` - photo in, disease class + confidence + bounding boxes out,
  with an IPDM advisory and a safety triage decision.
* `POST /risk` - weather-driven forecast with no image, using published
  agronomic models (Smith Period, Beaumont Period, TOMCAST DSV, degree-days).
* `POST /advisory` - IPDM recommendations retrieved from a human-reviewed
  knowledge base, in English, Marathi or Hindi.
* `GET /hotspots` - geospatial clustering of confirmed cases.
* `POST /sensors` - pest-trap and field-sensor ingestion.
* `GET /review/queue` - expert validation queue; decisions feed retraining.
* `GET /dashboard/summary` - aggregate view for agriculture officials.

`GET /meta/health` reports which components are running on real data and which
are on documented fallbacks.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Database ready at %s", settings.database_url)
    yield


app = FastAPI(
    title="CropGuard Maharashtra",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo deployment; restrict before any real rollout
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (detect, risk, advisory, hotspots, sensors, review, followup, dashboard, meta):
    app.include_router(r.router)

# Uploaded field photos, so the review queue can display them.
settings.upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(settings.upload_dir)), name="media")


@app.get("/", tags=["meta"], summary="Service banner")
def root() -> dict:
    return {
        "service": "CropGuard Maharashtra",
        "problem_statement": "SIH 2026 PS26131",
        "crop_scope": "potato (3 classes)",
        "docs": "/docs",
        "health": "/meta/health",
    }
