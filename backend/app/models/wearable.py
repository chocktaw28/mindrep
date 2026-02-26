"""
Wearable Daily Schemas
======================
Pydantic models for the wearable daily sync API.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class WearableDailyCreate(BaseModel):
    """Payload from HealthKit or Oura representing one day of biometric data."""

    date: date
    source: str = Field(..., max_length=50)
    hrv_avg: Optional[float] = None
    hrv_min: Optional[float] = None
    hrv_max: Optional[float] = None
    resting_hr: Optional[float] = None
    sleep_duration_minutes: Optional[int] = None
    sleep_deep_minutes: Optional[int] = None
    sleep_rem_minutes: Optional[int] = None
    sleep_score: Optional[float] = None
    readiness_score: Optional[float] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class WearableDailyResponse(BaseModel):
    """Returned to the mobile app after a successful sync."""

    id: str
    created_at: datetime
    user_id: str
    date: date
    source: str
    hrv_avg: Optional[float] = None
    hrv_min: Optional[float] = None
    hrv_max: Optional[float] = None
    resting_hr: Optional[float] = None
    sleep_duration_minutes: Optional[int] = None
    sleep_deep_minutes: Optional[int] = None
    sleep_rem_minutes: Optional[int] = None
    sleep_score: Optional[float] = None
    readiness_score: Optional[float] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None
