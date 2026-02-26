"""
Exercise Session Router
=======================
POST /api/v1/exercise — Log an exercise session.

Auth is required. No additional consent check — logging exercise is a
core app feature that does not require special consent beyond authentication.
Exercise type is validated against the allowed set so the correlation engine
receives clean, consistent data.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from app.db.supabase import get_supabase_client
from app.models.exercise import (
    VALID_EXERCISE_TYPES,
    ExerciseSessionCreate,
    ExerciseSessionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/exercise", tags=["exercise"])


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


def _validate_exercise_type(exercise_type: str) -> str:
    """Validate exercise_type against the allowed set.

    Raises HTTPException 422 with a helpful error including the valid list.
    """
    if exercise_type not in VALID_EXERCISE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Invalid exercise_type: '{exercise_type}'",
                "code": "invalid_exercise_type",
                "valid_types": sorted(VALID_EXERCISE_TYPES),
            },
        )
    return exercise_type


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ExerciseSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log an exercise session",
    description=(
        "Record a completed exercise session. Exercise type is validated against "
        "the allowed set so the correlation engine receives clean, consistent data."
    ),
    responses={
        201: {"description": "Exercise session created successfully"},
        401: {"description": "Authentication required"},
        422: {"description": "Validation error (invalid exercise_type, duration, etc.)"},
    },
)
async def log_exercise_session(
    body: ExerciseSessionCreate,
    authorization: str = Header(..., description="Bearer token from Supabase Auth"),
) -> ExerciseSessionResponse:
    """Log an exercise session."""
    # ------------------------------------------------------------------
    # 1. Auth
    # ------------------------------------------------------------------
    user = _get_authenticated_user(authorization)
    user_id: str = user["id"]

    # ------------------------------------------------------------------
    # 2. Validate exercise type
    # ------------------------------------------------------------------
    _validate_exercise_type(body.exercise_type)

    # ------------------------------------------------------------------
    # 3. Insert
    # ------------------------------------------------------------------
    db = get_supabase_client()

    row = {
        "user_id": user_id,
        "date": body.date.isoformat(),
        "exercise_type": body.exercise_type,
        "duration_minutes": body.duration_minutes,
        "intensity": body.intensity,
        "avg_heart_rate": body.avg_heart_rate,
        "calories": body.calories,
        "source": body.source,
        "notes": body.notes,
    }

    result = db.table("exercise_sessions").insert(row).execute()

    if not result.data or len(result.data) == 0:
        logger.error("Failed to insert exercise session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to save exercise session", "code": "db_error"},
        )

    return ExerciseSessionResponse(**result.data[0])
