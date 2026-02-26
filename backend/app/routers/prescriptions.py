"""
Prescriptions Router
====================
GET /api/v1/prescriptions/today — Fetch today's exercise recommendation.

Calls the PrescriptionService which:
  1. Reads the user's most recent mood check-in
  2. Detects mood state
  3. Looks for a statistically significant personal exercise–mood correlation
  4. Falls back to rule-based population defaults if no personal data
  5. Persists and returns the recommendation

No consent beyond auth is required here — the prescription is derived
entirely from data the user has already consented to provide (mood check-ins
and exercise sessions). No PII or biometric data leaves our infrastructure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from app.db.supabase import get_supabase_client
from app.models.prescription import PrescriptionResponse
from app.services.prescription import get_prescription_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prescriptions", tags=["prescriptions"])


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
    "/today",
    response_model=PrescriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get today's exercise recommendation",
    description=(
        "Returns a personalised exercise recommendation based on the user's "
        "most recent mood check-in and their personal exercise–mood correlation data. "
        "Falls back to population-level defaults if no personal data is available. "
        "Returns has_data=false if the user has not yet submitted any check-ins."
    ),
    responses={
        200: {"description": "Recommendation returned (may be null if no check-in data)"},
        401: {"description": "Authentication required"},
    },
)
async def get_todays_prescription(
    authorization: str = Header(..., description="Bearer token from Supabase Auth"),
) -> PrescriptionResponse:
    """Fetch today's exercise recommendation."""
    user = _get_authenticated_user(authorization)
    user_id: str = user["id"]

    service = get_prescription_service()
    prescription = await service.generate_for_user(user_id)

    return PrescriptionResponse(
        prescription=prescription,
        has_data=prescription is not None,
    )
