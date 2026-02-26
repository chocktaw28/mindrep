"""
Wearable Daily Sync Router
===========================
POST /api/v1/wearable/sync — Upsert one day of wearable biometric data.

Uses upsert (INSERT ... ON CONFLICT DO UPDATE) on the UNIQUE(user_id, date, source)
constraint so that HealthKit and Oura re-syncs overwrite the existing row rather
than failing or creating duplicates.

Biometric data NEVER leaves our infrastructure — no external API calls are made
with this data. This endpoint only accepts inbound data from the mobile app.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from app.db.supabase import get_supabase_client
from app.models.wearable import WearableDailyCreate, WearableDailyResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/wearable", tags=["wearable"])


# ---------------------------------------------------------------------------
# Helpers
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

@router.post(
    "/sync",
    response_model=WearableDailyResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync a day of wearable data",
    description=(
        "Upsert one day of biometric data from HealthKit or Oura. "
        "Re-syncing the same date+source overwrites the existing row — "
        "no duplicates. Requires wearable_data_consent."
    ),
    responses={
        200: {"description": "Wearable data synced successfully"},
        401: {"description": "Authentication required"},
        403: {"description": "Wearable data consent not granted"},
    },
)
async def sync_wearable_daily(
    body: WearableDailyCreate,
    authorization: str = Header(..., description="Bearer token from Supabase Auth"),
) -> WearableDailyResponse:
    """Upsert one day of wearable biometric data."""
    # ------------------------------------------------------------------
    # 1. Auth
    # ------------------------------------------------------------------
    user = _get_authenticated_user(authorization)
    user_id: str = user["id"]

    # ------------------------------------------------------------------
    # 2. Consent check — wearable data requires explicit consent
    # ------------------------------------------------------------------
    if not user.get("wearable_data_consent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    "Wearable data consent is required to sync biometric data. "
                    "Please grant consent in your settings."
                ),
                "code": "consent_required",
            },
        )

    # ------------------------------------------------------------------
    # 3. Upsert — UNIQUE(user_id, date, source) prevents duplicates
    # ------------------------------------------------------------------
    db = get_supabase_client()

    row = {
        "user_id": user_id,
        "date": body.date.isoformat(),
        "source": body.source,
        "hrv_avg": body.hrv_avg,
        "hrv_min": body.hrv_min,
        "hrv_max": body.hrv_max,
        "resting_hr": body.resting_hr,
        "sleep_duration_minutes": body.sleep_duration_minutes,
        "sleep_deep_minutes": body.sleep_deep_minutes,
        "sleep_rem_minutes": body.sleep_rem_minutes,
        "sleep_score": body.sleep_score,
        "readiness_score": body.readiness_score,
        "steps": body.steps,
        "active_calories": body.active_calories,
    }

    result = db.table("wearable_daily").upsert(
        row, on_conflict="user_id,date,source"
    ).execute()

    if not result.data or len(result.data) == 0:
        logger.error("Failed to upsert wearable data for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to save wearable data", "code": "db_error"},
        )

    return WearableDailyResponse(**result.data[0])
