"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import CaseSource, FollowUpOutcome, ReviewStatus


# ----------------------------------------------------------------------
# Shared field context
# ----------------------------------------------------------------------
class FieldContext(BaseModel):
    crop: str = "potato"
    variety: str | None = None
    crop_stage: str | None = Field(
        default=None,
        description="sowing | emergence | vegetative | tuber_initiation | tuber_bulking | maturity | harvest",
    )
    soil_condition: str | None = Field(
        default=None, description="well_drained | normal | poorly_drained | waterlogged | sandy | clay"
    )
    district: str | None = None
    village: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


# ----------------------------------------------------------------------
# Detect
# ----------------------------------------------------------------------
class DetectionOut(BaseModel):
    class_key: str
    class_display: str
    confidence: float
    bbox: list[float]
    bbox_norm: list[float]


class DetectResponse(BaseModel):
    case_id: int
    model_available: bool
    model_version: str | None = None
    predicted_class: str | None = None
    predicted_display: str | None = None
    confidence: float | None = None
    detections: list[DetectionOut] = []
    image_size: list[int] | None = None
    note: str | None = None
    risk: dict | None = None
    triage: dict
    advisory: dict
    follow_up_id: int | None = None
    language: str


# ----------------------------------------------------------------------
# Risk
# ----------------------------------------------------------------------
class RiskRequest(FieldContext):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    past_days: int = Field(default=7, ge=1, le=30)
    forecast_days: int = Field(default=3, ge=0, le=5)
    language: str = "en"
    save_case: bool = Field(
        default=False,
        description="Persist as a proactive (no-image) case so it appears on the officer dashboard.",
    )
    include_advisory: bool = True


class RiskResponse(BaseModel):
    case_id: int | None = None
    assessment: dict
    advisory: dict | None = None
    triage: dict | None = None
    language: str


# ----------------------------------------------------------------------
# Advisory
# ----------------------------------------------------------------------
class AdvisoryRequest(BaseModel):
    class_key: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    question: str | None = None
    language: str = "en"
    latitude: float | None = None
    longitude: float | None = None
    include_risk: bool = False
    context: FieldContext | None = None


class AdvisoryResponse(BaseModel):
    advisory: dict
    triage: dict
    risk: dict | None = None
    language: str


# ----------------------------------------------------------------------
# Assistant chatbot
# ----------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Prior turns for context, oldest first. Capped server-side.
    history: list[ChatMessage] = Field(default_factory=list)
    language: str = "en"


class ChatResponse(BaseModel):
    reply: str
    language: str
    # False when the Gemini key is unset and the canned fallback answered.
    live: bool


# ----------------------------------------------------------------------
# Sensors
# ----------------------------------------------------------------------
class SensorReadingIn(BaseModel):
    device_id: str
    device_type: str = "pest_trap"
    metric: str = "trap_count"
    value: float
    unit: str | None = None
    crop: str | None = "potato"
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    recorded_at: datetime | None = None
    raw: dict | None = None


class SensorBatchIn(BaseModel):
    readings: list[SensorReadingIn]


class SensorReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    device_type: str
    metric: str
    value: float
    unit: str | None
    district: str | None
    latitude: float | None
    longitude: float | None
    geo_cell: str | None
    recorded_at: datetime


# ----------------------------------------------------------------------
# Review
# ----------------------------------------------------------------------
class ReviewDecision(BaseModel):
    status: ReviewStatus
    confirmed_class: str | None = Field(
        default=None, description="Required when status is 'corrected'."
    )
    reviewer: str
    notes: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    source: CaseSource
    crop: str
    variety: str | None
    crop_stage: str | None
    district: str | None
    village: str | None
    latitude: float | None
    longitude: float | None
    geo_cell: str | None
    image_path: str | None
    predicted_class: str | None
    confidence: float | None
    detections: list | None
    risk_level: str | None
    risk_score: float | None
    escalate: bool
    review_status: ReviewStatus
    confirmed_class: str | None
    reviewer: str | None
    reviewer_notes: str | None
    reviewed_at: datetime | None
    language: str


# ----------------------------------------------------------------------
# Follow-up
# ----------------------------------------------------------------------
class FollowUpIn(BaseModel):
    case_id: int
    due_date: datetime | None = None
    notes: str | None = None


class FollowUpUpdate(BaseModel):
    outcome: FollowUpOutcome
    treatment_applied: str | None = None
    notes: str | None = None


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    created_at: datetime
    due_date: datetime
    outcome: FollowUpOutcome
    treatment_applied: str | None
    notes: str | None
    closed_at: datetime | None
