"""/meta -- health, capabilities and self-description.

`/meta/health` is deliberately verbose about what is *degraded*: no weights, no
weather key, no LLM. A judge or an officer should be able to see at a glance
which parts of the system are running on real data and which are running on the
documented fallbacks.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.services import advisory as advisory_service
from app.services import taxonomy, translate
from app.services.detector import detector
from app.services.knowledge_base import knowledge_base
from app.services.risk_secondary import secondary_layer

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/health", summary="Service health, degraded capabilities and design states")
def health() -> dict:
    """Two different things get reported separately, because conflating them is
    misleading in both directions.

    * **degraded** -- something that should be working and is not. A missing
      detector means no diagnosis; a missing weather key means the risk engine
      is running on invented weather. These need fixing.
    * **by_design** -- a documented, deliberate state. The advisory layer is
      template-first *by design* (a farmer gets full Marathi/Bengali with no API
      key), and the XGBoost layer is inactive *by design* until real historical
      outbreak data exists. Flagging these as faults implies the system is
      broken when it is behaving exactly as specified.
    """
    det = detector.status()
    kb = knowledge_base.status()

    degraded: list[dict] = []
    by_design: list[dict] = []

    if not det["available"]:
        degraded.append(
            {
                "code": "detection_model_missing",
                "summary": "No trained detector installed, so photo cases go to the expert "
                "review queue instead of receiving a guessed diagnosis.",
                "remedy": "Train on Kaggle (ml/notebooks/) and place best.onnx in ml/weights/.",
            }
        )
    if det.get("class_mismatch"):
        degraded.append(
            {
                "code": "detector_class_mismatch",
                "summary": "The loaded model's class order does not match the app's taxonomy, "
                "so predictions would be mislabelled. Detections are unsafe to trust.",
                "remedy": det["class_mismatch"],
            }
        )
    if not settings.openweather_api_key:
        degraded.append(
            {
                "code": "weather_api_key_missing",
                "summary": "Risk forecasts are computed from a deterministic synthetic weather "
                "feed, not real observations. Every response is flagged synthetic:true.",
                "remedy": "Get a free key at openweathermap.org/api and set "
                "OPENWEATHER_API_KEY in .env.",
            }
        )

    if not settings.llm_enabled:
        by_design.append(
            {
                "code": "llm_translation_unused",
                "summary": "Advisories are assembled from the built-in translated message "
                f"catalog ({', '.join(settings.languages)}), which is the intended default: "
                "no API key, no network, no per-request cost.",
                "remedy": "Optional. Set GEMINI_API_KEY to also translate free-text "
                "knowledge-base excerpts.",
            }
        )
    if not secondary_layer.active:
        by_design.append(
            {
                "code": "secondary_risk_layer_inactive",
                "summary": "Risk comes entirely from the published agronomic models (Smith, "
                "Beaumont, TOMCAST, degree-days), which is the specified primary layer. The "
                "optional XGBoost refinement stays inactive until real historical outbreak "
                "data exists to train it honestly.",
                "remedy": "Optional. Accumulate confirmed cases, then run "
                "scripts/export_risk_dataset.py and ml/train_risk_xgb.py.",
            }
        )
    if kb["backend"] != "chroma":
        by_design.append(
            {
                "code": "vector_store_fallback",
                "summary": "Knowledge-base retrieval is using the built-in BM25 index. "
                "Advisories work fully; ranking is lexical rather than semantic.",
                "remedy": "Optional. pip install -r backend/requirements-extras.txt for "
                "ChromaDB vector search.",
            }
        )

    return {
        "status": "degraded" if degraded else "ok",
        "env": settings.app_env,
        "degraded": [d["code"] for d in degraded],
        "degraded_detail": degraded,
        "by_design": [d["code"] for d in by_design],
        "by_design_detail": by_design,
        "components": {
            "detector": det,
            "knowledge_base": kb,
            "advisory_pipeline": advisory_service.pipeline_status()["backend"],
            "languages": settings.languages,
            "weather_provider": settings.weather_provider
            if settings.openweather_api_key
            else "synthetic",
            "secondary_risk_layer": secondary_layer.status(),
        },
    }


@router.get("/classes", summary="Classes the deployed model covers")
def classes() -> dict:
    return {
        "crop": taxonomy.CROP,
        "scope_note": (
            "The deployed detector is trained on potato only, with three classes. Potato was "
            "chosen first because late blight is the textbook weather-driven epidemic that the "
            "Smith Period model is defined for, it is a major Maharashtra rabi crop, and clean "
            "training imagery exists. Adding a crop is a dataset and retraining task, not an "
            "architecture change."
        ),
        "classes": [
            {
                "key": c.key,
                "display": c.display,
                "crop": c.crop,
                "kind": c.kind,
                "pathogen": c.pathogen,
                "severity": c.severity,
                "names": c.names,
            }
            for c in taxonomy.CLASSES
        ],
    }


@router.get("/languages", summary="Supported advisory languages and catalog coverage")
def languages() -> dict:
    return {
        "default": settings.default_language,
        "supported": settings.languages,
        "llm_translation": settings.llm_enabled,
        "coverage": translate.coverage(),
        "note": (
            "Advisories are assembled from a translated message catalog, so Marathi and Hindi "
            "output needs no API key or network. Only free-text knowledge-base excerpts require "
            "an LLM to translate."
        ),
    }
