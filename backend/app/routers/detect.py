"""POST /detect -- the farmer-facing core loop entry point."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, settings
from app.database import get_db
from app.models import CaseSource
from app.schemas import DetectResponse
from app.services import taxonomy
from app.services.detector import detector
from app.services.pipeline import run_case
from app.services.risk_engine import RiskContext
from app.services.translate import normalise_language

log = logging.getLogger(__name__)
router = APIRouter(prefix="/detect", tags=["detect"])

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
# Field phones produce large images; downscaling keeps disk use sane and does
# not hurt a 640px model input.
MAX_STORED_EDGE = 1600


def _repo_relative(path: Path) -> str:
    """Store portable paths so the DB survives the repo being moved."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{suffix or 'unknown'}'. Use JPG, PNG or WEBP.",
        )
    raw = upload.file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 12 MB.")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")

    day_dir = settings.upload_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    dest = day_dir / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(raw)

    try:
        with Image.open(dest) as img:
            img.verify()
        with Image.open(dest) as img:
            img = img.convert("RGB")
            if max(img.size) > MAX_STORED_EDGE:
                img.thumbnail((MAX_STORED_EDGE, MAX_STORED_EDGE))
                img.save(dest)
    except (UnidentifiedImageError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Not a readable image: {exc}") from exc
    return dest


@router.post("", response_model=DetectResponse, summary="Detect disease/pest from a crop photo")
async def detect(
    image: UploadFile = File(..., description="Crop leaf photograph"),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    crop: str = Form("potato"),
    variety: str | None = Form(None),
    crop_stage: str | None = Form(None),
    soil_condition: str | None = Form(None),
    district: str | None = Form(None),
    village: str | None = Form(None),
    farmer_name: str | None = Form(None),
    phone: str | None = Form(None),
    severity_fraction: float | None = Form(
        None, description="Farmer's estimate of the share of the field affected, 0-1."
    ),
    language: str = Form("en"),
    db: Session = Depends(get_db),
) -> DetectResponse:
    lang = normalise_language(language)
    path = _save_upload(image)

    try:
        result = detector.predict(path)
    except Exception as exc:  # a corrupt model must not 500 the farmer flow
        log.exception("Detector failed on %s", path)
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    ctx = RiskContext(
        crop=crop,
        crop_stage=crop_stage,
        variety=variety,
        soil_condition=soil_condition,
        district=district,
    )
    outcome = run_case(
        db,
        source=CaseSource.IMAGE,
        detection=result,
        image_path=_repo_relative(path),
        lat=latitude,
        lon=longitude,
        ctx=ctx,
        language=lang,
        farmer_name=farmer_name,
        phone=phone,
        village=village,
        severity_fraction=severity_fraction,
    )

    case = outcome["case"]
    return DetectResponse(
        case_id=case.id,
        model_available=result.model_available,
        model_version=result.model_version,
        predicted_class=result.top_class,
        predicted_display=taxonomy.display_name(result.top_class, lang)
        if result.top_class
        else None,
        confidence=result.top_confidence,
        detections=[
            {
                "class_key": d.class_key,
                "class_display": taxonomy.display_name(d.class_key, lang),
                "confidence": d.confidence,
                "bbox": d.bbox,
                "bbox_norm": d.bbox_norm,
            }
            for d in result.detections
        ],
        image_size=list(result.image_size) if result.image_size else None,
        note=result.note,
        risk=outcome["risk"],
        triage=outcome["triage"],
        advisory=outcome["advisory"],
        follow_up_id=outcome["follow_up"].id if outcome["follow_up"] else None,
        language=lang,
    )


@router.get("/status", summary="Detection model status")
def status() -> dict:
    return detector.status()
