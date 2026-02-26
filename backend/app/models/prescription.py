"""
Prescription Schemas
====================
Pydantic models for exercise prescriptions returned to the mobile app.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MoodPrescription(BaseModel):
    """A single exercise prescription generated for a user."""

    id: str = Field(..., description="UUID of the prescription record.")
    created_at: datetime
    exercise_type: str = Field(..., description="Recommended exercise, e.g. 'walking'.")
    suggested_duration_minutes: int = Field(
        ...,
        description="Suggested session length in minutes.",
    )
    suggested_intensity: str = Field(
        ...,
        description="Suggested intensity: 'low', 'moderate', or 'vigorous'.",
    )
    reasoning: str = Field(
        ...,
        description="Regulatory-safe explanation shown to the user.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in this recommendation (0–1).",
    )
    source: str = Field(
        ...,
        description="'correlation' if driven by personal data, 'rule_based' otherwise.",
    )


class PrescriptionResponse(BaseModel):
    """Response envelope returned by GET /api/v1/prescriptions/today."""

    prescription: Optional[MoodPrescription] = Field(
        default=None,
        description=(
            "Today's exercise recommendation, or null if no check-in data "
            "exists yet for this user."
        ),
    )
    has_data: bool = Field(
        ...,
        description="False when no mood check-in data exists — app should prompt a check-in.",
    )
    disclaimer: str = Field(
        default="MindRep is a wellness tool, not a medical device.",
        description="Regulatory disclaimer — must always be shown alongside recommendations.",
    )
