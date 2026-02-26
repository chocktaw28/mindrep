"""
Exercise Session Schemas
========================
Pydantic models for the exercise session API.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

VALID_EXERCISE_TYPES = frozenset({
    "running",
    "strength",
    "yoga",
    "walking",
    "cycling",
    "swimming",
    "hiit",
    "dance",
    "other",
})


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class ExerciseSessionCreate(BaseModel):
    """Payload the mobile app sends when logging an exercise session."""

    date: date
    exercise_type: str
    duration_minutes: int = Field(..., ge=1, le=600)
    intensity: Literal["low", "moderate", "vigorous"]
    avg_heart_rate: Optional[float] = None
    calories: Optional[float] = None
    source: str = Field(default="manual", max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class ExerciseSessionResponse(BaseModel):
    """Returned to the mobile app after a session is saved."""

    id: str
    created_at: datetime
    user_id: str
    date: date
    exercise_type: str
    duration_minutes: int
    intensity: str
    avg_heart_rate: Optional[float] = None
    calories: Optional[float] = None
    source: str
    notes: Optional[str] = None
