"""CropHealth lab endpoints -- two-class healthy/unhealthy crop detection.

Same contract as /croprow, one class more: every box comes back with a
``class_key`` of ``healthy`` or ``unhealthy`` instead of a single fixed crop
label. Like /croprow it is separate from /detect on purpose -- no case, no
advisory, no database -- and the preferred path is the browser running the ONNX
model on-device via GET /crophealth/model, with POST /crophealth/frame as the
server fallback.
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
from app.services.crophealth_detector import crophealth_detector

log = logging.getLogger(__name__)
router = APIRouter(prefix="/crophealth", tags=["crophealth"])

MAX_FRAME_BYTES = 12 * 1024 * 1024


@router.get("/status", summary="CropHealth model status")
def status() -> dict:
    return crophealth_detector.status()


@router.get("/thresholds", summary="Class list + thresholds for the browser model")
def thresholds() -> dict:
    """Feeds the in-browser decoder the same class order and cut-offs the server
    uses, so a frame is judged identically on either path.

    ``per_class`` stays empty: unlike the potato detector there is no tuned
    per-class table here, and shipping invented per-class numbers would make the
    two paths agree on a value neither of them measured.
    """
    s = crophealth_detector.status()
    return {
        "classes": s["classes"],
        "per_class": {},
        "default": s["conf_threshold"],
        "low_confidence_threshold": s["conf_threshold"],
        "iou_threshold": s["iou_threshold"],
        "source": s["version"],
    }


@router.get("/model", summary="Download the ONNX model for in-browser inference")
def model_file():
    path = Path(settings.crophealth_onnx_path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No crop-health ONNX installed. Run `python croprow_disease/export_onnx.py` "
                "to write croprow_disease/models/best.onnx. The lab scanner falls back to "
                "server inference until then."
            ),
        )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename="crophealth.onnx",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/frame", summary="Judge crop health in one frame (no case created)")
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
        result = crophealth_detector.predict_array(arr)
    except Exception as exc:  # a corrupt model must not 500 the lab preview
        log.exception("CropHealth frame inference failed")
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    counts: dict[str, int] = {}
    for d in result.detections:
        counts[d["class_key"]] = counts.get(d["class_key"], 0) + 1

    return {
        "model_available": result.model_available,
        "model_version": result.model_version,
        "count": len(result.detections),
        "counts": counts,
        "detections": [
            {"class_key": d["class_key"], "confidence": d["confidence"], "bbox_norm": d["bbox_norm"]}
            for d in result.detections
        ],
        "note": result.note,
    }
