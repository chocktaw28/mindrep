"""
Insights Router
===============
GET /api/v1/insights/weekly — Weekly mood and exercise summary.

Returns three sections in one call so the mobile dashboard can render
in a single network round-trip:

  mood_trend:        Array of {date, mood_score} for the last 7 days.
                     One entry per day where a check-in exists — days
                     with no check-in are omitted (sparse is fine for
                     the chart; the app handles gaps).

  top_correlations:  The user's personal exercise–mood correlations from
                     user_correlations, ordered by mood_change_pct desc,
                     up to 5 entries. Empty list if no correlations yet.

  exercise_summary:  Count of sessions per exercise type in the last 7
                     days, e.g. {"running": 3, "yoga": 1}.

No PII is returned. Biometric data is excluded — this endpoint reads only
mood_score, exercise_type, and correlation stats, all stored in our DB.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MoodTrendPoint(BaseModel):
    """A single day's average mood score."""
    date: date
    mood_score: float


class CorrelationSummary(BaseModel):
    """One exercise–mood correlation entry for the insights dashboard."""
    exercise_type: str
    mood_change_pct: float
    p_value: float
    sample_size: int
    insight_text: str


class WeeklyInsightsResponse(BaseModel):
    """Full weekly insights payload returned to the mobile app."""
    mood_trend: list[MoodTrendPoint]
    top_correlations: list[CorrelationSummary]
    exercise_summary: dict[str, int]
    week_start: date
    week_end: date


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_authenticated_user(authorization: str) -> dict:
    """Verify the JWT and return the user record from Supabase.

    Raises HTTPException 401 if the token is invalid or missing.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Missing or invalid authorization header", "code": "auth_required"},
        )

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Empty bearer token", "code": "auth_required"},
        )

    db = get_supabase_client()

    try:
        auth_response = db.auth.get_user(token)
    except Exception as exc:
        logger.warning("Auth token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token", "code": "auth_invalid"},
        ) from exc

    if not auth_response or not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "User not found for token", "code": "auth_invalid"},
        )

    user_id = auth_response.user.id

    result = (
        db.table("users")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User profile not found", "code": "user_not_found"},
        )

    return result.data


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/weekly",
    response_model=WeeklyInsightsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get weekly mood and exercise insights",
    description=(
        "Returns mood trend, top exercise–mood correlations, and exercise counts "
        "for the last 7 days. All sections may be empty for new users with no data."
    ),
    responses={
        200: {"description": "Weekly insights returned"},
        401: {"description": "Authentication required"},
    },
)
async def get_weekly_insights(
    authorization: str = Header(..., description="Bearer token from Supabase Auth"),
) -> WeeklyInsightsResponse:
    """Fetch weekly mood trend, correlations, and exercise summary."""
    user = _get_authenticated_user(authorization)
    user_id: str = user["id"]

    db = get_supabase_client()

    now_utc = datetime.now(timezone.utc)
    week_end = now_utc.date()
    week_start = week_end - timedelta(days=6)  # inclusive 7-day window
    week_start_iso = week_start.isoformat()

    # ------------------------------------------------------------------
    # 1. Mood trend — daily average mood score for the last 7 days
    # ------------------------------------------------------------------
    checkin_result = (
        db.table("mood_checkins")
        .select("created_at, mood_score")
        .eq("user_id", user_id)
        .gte("created_at", f"{week_start_iso}T00:00:00")
        .order("created_at", desc=False)
        .execute()
    )

    # Average per day (user may submit multiple check-ins per day)
    daily_scores: dict[date, list[float]] = {}
    for row in (checkin_result.data or []):
        day = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).date()
        daily_scores.setdefault(day, []).append(float(row["mood_score"]))

    mood_trend = [
        MoodTrendPoint(date=d, mood_score=round(sum(scores) / len(scores), 2))
        for d, scores in sorted(daily_scores.items())
    ]

    # ------------------------------------------------------------------
    # 2. Top correlations — from user_correlations, up to 5
    # ------------------------------------------------------------------
    corr_result = (
        db.table("user_correlations")
        .select("exercise_type, mood_change_pct, p_value, sample_size, insight_text")
        .eq("user_id", user_id)
        .order("mood_change_pct", desc=True)
        .limit(5)
        .execute()
    )

    top_correlations = [
        CorrelationSummary(
            exercise_type=row["exercise_type"],
            mood_change_pct=float(row["mood_change_pct"]),
            p_value=float(row["p_value"]),
            sample_size=int(row["sample_size"]),
            insight_text=row["insight_text"],
        )
        for row in (corr_result.data or [])
    ]

    # ------------------------------------------------------------------
    # 3. Exercise summary — session counts per type this week
    # ------------------------------------------------------------------
    exercise_result = (
        db.table("exercise_sessions")
        .select("exercise_type")
        .eq("user_id", user_id)
        .gte("date", week_start_iso)
        .execute()
    )

    exercise_summary: dict[str, int] = {}
    for row in (exercise_result.data or []):
        ex_type = row["exercise_type"]
        exercise_summary[ex_type] = exercise_summary.get(ex_type, 0) + 1

    return WeeklyInsightsResponse(
        mood_trend=mood_trend,
        top_correlations=top_correlations,
        exercise_summary=exercise_summary,
        week_start=week_start,
        week_end=week_end,
    )
