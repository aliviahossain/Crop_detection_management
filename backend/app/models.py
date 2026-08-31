"""ORM schema.

Design note: `Case` is the spine of the system. A case is created by /detect
(image path) or by /risk (proactive, no image). Everything else -- advisory,
expert review, follow-up, hotspot aggregation -- hangs off it, which is what
makes "learns from field confirmations" possible: a reviewed case with a
corrected label is a new training sample.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseSource(str, enum.Enum):
    IMAGE = "image"
    RISK_FORECAST = "risk_forecast"
    SENSOR = "sensor"


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FollowUpOutcome(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    IMPROVING = "improving"
    UNCHANGED = "unchanged"
    WORSENED = "worsened"


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[CaseSource] = mapped_column(Enum(CaseSource), default=CaseSource.IMAGE)

    # Farmer / plot context
    farmer_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    crop: Mapped[str] = mapped_column(String(60), default="potato", index=True)
    variety: Mapped[str | None] = mapped_column(String(60))
    crop_stage: Mapped[str | None] = mapped_column(String(40))
    soil_condition: Mapped[str | None] = mapped_column(String(40))
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    village: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    geo_cell: Mapped[str | None] = mapped_column(String(32), index=True)

    # Detection result
    image_path: Mapped[str | None] = mapped_column(String(255))
    predicted_class: Mapped[str | None] = mapped_column(String(80), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    detections: Mapped[list | None] = mapped_column(JSON)  # [{class,conf,bbox}]
    model_version: Mapped[str | None] = mapped_column(String(60))

    # Risk result
    risk_level: Mapped[RiskLevel | None] = mapped_column(Enum(RiskLevel), index=True)
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_detail: Mapped[dict | None] = mapped_column(JSON)

    # Triage / advisory
    escalate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    escalation_reasons: Mapped[list | None] = mapped_column(JSON)
    advisory: Mapped[dict | None] = mapped_column(JSON)
    language: Mapped[str] = mapped_column(String(8), default="en")

    # Expert validation
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.PENDING, index=True
    )
    confirmed_class: Mapped[str | None] = mapped_column(String(80), index=True)
    reviewer: Mapped[str | None] = mapped_column(String(120))
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    follow_ups: Mapped[list["FollowUp"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    @property
    def effective_class(self) -> str | None:
        """The label to trust: an expert's word beats the model's."""
        return self.confirmed_class or self.predicted_class


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    outcome: Mapped[FollowUpOutcome] = mapped_column(
        Enum(FollowUpOutcome), default=FollowUpOutcome.PENDING, index=True
    )
    treatment_applied: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    case: Mapped[Case] = relationship(back_populates="follow_ups")


class SensorReading(Base):
    """Pest-trap / field-sensor ingestion. Kept deliberately generic:
    a pheromone trap posts `metric='trap_count'`, a leaf-wetness probe posts
    `metric='leaf_wetness'`, and the risk engine reads whatever is there."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    device_type: Mapped[str] = mapped_column(String(40), default="pest_trap")
    metric: Mapped[str] = mapped_column(String(40), default="trap_count", index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    crop: Mapped[str | None] = mapped_column(String(60))
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geo_cell: Mapped[str | None] = mapped_column(String(32), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    raw: Mapped[dict | None] = mapped_column(JSON)


class TrainingSample(Base):
    """The feedback loop's output: every expert-validated case lands here and
    is exported by `ml/export_feedback.py` as the next training increment."""

    __tablename__ = "training_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    image_path: Mapped[str | None] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(80), index=True)
    was_model_correct: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str | None] = mapped_column(String(60))
    exported: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WeatherObservation(Base):
    """Hourly weather cache. Doubles as the history buffer the Smith Period
    needs (it looks back over consecutive days)."""

    __tablename__ = "weather_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    geo_cell: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    temp_c: Mapped[float] = mapped_column(Float)
    humidity: Mapped[float] = mapped_column(Float)
    rainfall_mm: Mapped[float] = mapped_column(Float, default=0.0)
    wind_kph: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="openweathermap")
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False)
