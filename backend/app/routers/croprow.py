"""CropRow lab endpoints -- single-class crop (lettuce) localization.

Separate from /detect on purpose: no case, no advisory, no database. The lab
scanner draws boxes as live-camera or uploaded-video frames play and saves
nothing. Preferred path is the browser running the ONNX model on-device via
GET /croprow/model; POST /croprow/frame is the server fallback.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
import numpy as np

from app.config import settings
from app.services.croprow_detector import croprow_detector

log = logging.getLogger(__name__)
router = APIRouter(prefix="/croprow", tags=["croprow"])

MAX_FRAME_BYTES = 12 * 1024 * 1024


@router.get("/status", summary="CropRow model status")
def status() -> dict:
    return croprow_detector.status()


@router.get("/thresholds", summary="Class list + thresholds for the browser model")
def thresholds() -> dict:
    """Feeds the in-browser decoder the same class order and cut-offs the server
    uses, so a frame is localized identically on either path."""
    s = croprow_detector.status()
    return {
        "classes": s["classes"],
        "per_class": {},  # single class: one default cut-off is enough
        "default": s["conf_threshold"],
        "low_confidence_threshold": s["conf_threshold"],
        "iou_threshold": s["iou_threshold"],
        "source": s["version"],
    }


@router.get("/model", summary="Download the ONNX model for in-browser inference")
def model_file():
    path = Path(settings.croprow_onnx_path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No croprow ONNX installed. Run `python croprow/export_onnx.py` to write "
                "croprow/models/best.onnx. The lab scanner falls back to server inference "
                "until then."
            ),
        )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename="croprow.onnx",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/frame", summary="Localize crop in one frame (no case created)")
async def detect_frame(image: UploadFile = File(..., description="One frame from the lab scanner")):
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty frame.")
    if len(raw) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame is larger than 12 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            arr = np.asarray(img.convert("RGB"))
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Not a readable image: {exc}") from exc

    try:
        result = croprow_detector.predict_array(arr)
    except Exception as exc:  # a corrupt model must not 500 the lab preview
        log.exception("CropRow frame inference failed")
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    return {
        "model_available": result.model_available,
        "model_version": result.model_version,
        "count": len(result.detections),
        "detections": [
            {"class_key": d["class_key"], "confidence": d["confidence"], "bbox_norm": d["bbox_norm"]}
            for d in result.detections
        ],
        "note": result.note,
    }
