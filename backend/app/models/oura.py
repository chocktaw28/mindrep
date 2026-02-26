"""
Oura API Response Models
========================
Pydantic shapes for parsing raw Oura REST API v2 JSON responses.
Used internally by the Oura service layer before normalising into
WearableDailyCreate — not exposed as API responses.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class OuraDailySleepItem(BaseModel):
    """One day of Oura daily_sleep summary data."""

    day: date
    score: Optional[int] = None
    # contributor scores (all 1–100, not raw minutes)
    contributors: Optional[dict] = None


class OuraDailyReadinessItem(BaseModel):
    """One day of Oura daily_readiness summary data."""

    day: date
    score: Optional[int] = None
    # contributor scores (all 1–100, not raw bpm)
    contributors: Optional[dict] = None


class OuraDailyActivityItem(BaseModel):
    """One day of Oura daily_activity summary data."""

    day: date
    steps: Optional[int] = None
    active_calories: Optional[int] = None


class OuraTokenResponse(BaseModel):
    """Response from the Oura OAuth /oauth/token endpoint."""

    access_token: str
    refresh_token: str
    expires_in: int   # seconds until expiry
    token_type: str
    scope: str
