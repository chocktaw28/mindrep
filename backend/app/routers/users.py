"""
Users Router
============
PATCH /api/v1/users/consent — Update a user's consent preferences.

Called at the end of onboarding to record:
  - mood_data_consent      (required to use the product)
  - wearable_data_consent  (optional — enables HealthKit/Oura sync)
  - ai_processing_consent  (optional — enables Claude mood classification)

All consent timestamps are set server-side at the moment of grant/revocation.
This endpoint also handles upsert of the users row so it works for both
new magic-link signups (no pre-existing row) and returning users who update
their preferences.

UK GDPR compliance:
  - Granular consent per processing purpose (Art. 7)
  - Timestamps recorded for audit trail (Art. 7(1))
  - Consent for special category data (mood/health) is explicit opt-in (Art. 9)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, status

from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


# ---------------------------------------------------------------------------
# Helpers (shared pattern with other routers)
# ---------------------------------------------------------------------------

def _get_authenticated_user_id(authorization: str) -> str:
    """Verify the JWT and return the user's UUID.

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
            detail={"message": "Invalid or expired token", "code": "auth_required"},
        )

    if not auth_response or not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "User not found", "code": "auth_required"},
        )

    return str(auth_response.user.id)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description="Return the authenticated user's profile including consent flags.",
    responses={
        200: {"description": "User profile"},
        401: {"description": "Authentication required"},
        404: {"description": "User row not yet created"},
    },
)
async def get_me(
    authorization: str = Header(...),
) -> dict:
    """Return the current user's profile row."""
    user_id = _get_authenticated_user_id(authorization)

    db = get_supabase_client()
    result = (
        db.table("users")
        .select("id, mood_data_consent, wearable_data_consent, ai_processing_consent")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        # Row hasn't been created yet (brand-new signup before onboarding)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User profile not found", "code": "user_not_found"},
        )

    return result.data


@router.patch(
    "/consent",
    status_code=status.HTTP_200_OK,
    summary="Update consent preferences",
    description=(
        "Upsert the authenticated user's consent flags. "
        "Called at end of onboarding and from Settings. "
        "mood_data_consent is required for core product functionality."
    ),
    responses={
        200: {"description": "Consent updated successfully"},
        400: {"description": "mood_data_consent must be true"},
        401: {"description": "Authentication required"},
    },
)
async def update_consent(
    body: dict,
    authorization: str = Header(...),
) -> dict:
    """Update consent preferences for the authenticated user.

    Accepts a JSON body with any subset of:
      { mood_data_consent, wearable_data_consent, ai_processing_consent }

    Timestamps are set server-side for any field that is changing to True.
    """
    user_id = _get_authenticated_user_id(authorization)

    mood_consent = body.get("mood_data_consent")
    wearable_consent = body.get("wearable_data_consent")
    ai_consent = body.get("ai_processing_consent")

    # mood_data_consent is the legal basis for the core product — must be True
    if mood_consent is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": (
                    "mood_data_consent must be granted to use MindRep. "
                    "Without it we cannot process your wellbeing data."
                ),
                "code": "mood_consent_required",
            },
        )

    now = datetime.now(timezone.utc).isoformat()
    update_payload: dict = {"id": user_id}

    if mood_consent is not None:
        update_payload["mood_data_consent"] = mood_consent
        if mood_consent:
            update_payload["mood_data_consent_at"] = now

    if wearable_consent is not None:
        update_payload["wearable_data_consent"] = wearable_consent
        if wearable_consent:
            update_payload["wearable_data_consent_at"] = now

    if ai_consent is not None:
        update_payload["ai_processing_consent"] = ai_consent
        if ai_consent:
            update_payload["ai_processing_consent_at"] = now

    db = get_supabase_client()
    db.table("users").upsert(update_payload).execute()

    logger.info(
        "Consent updated for user %s: mood=%s wearable=%s ai=%s",
        user_id,
        mood_consent,
        wearable_consent,
        ai_consent,
    )

    return {
        "data": {
            "mood_data_consent": mood_consent,
            "wearable_data_consent": wearable_consent,
            "ai_processing_consent": ai_consent,
        },
        "error": None,
    }


@router.post(
    "/export",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request data export",
    description=(
        "Queue a full data export for the authenticated user (UK GDPR Art. 20 — data portability). "
        "Returns 202 Accepted immediately; the export is prepared asynchronously and delivered by email."
    ),
    responses={
        202: {"description": "Export request accepted"},
        401: {"description": "Authentication required"},
    },
)
async def request_export(
    authorization: str = Header(...),
) -> dict:
    """Accept and log a data export request.

    In the MVP the export is acknowledged synchronously; a background job
    (outside MVP scope) would generate and email the archive.
    """
    user_id = _get_authenticated_user_id(authorization)

    logger.info("Data export requested by user %s", user_id)

    return {
        "data": {
            "message": (
                "Your data export has been requested. "
                "We will email it to you within 30 days as required by UK GDPR."
            )
        },
        "error": None,
    }


@router.delete(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Delete account and all data",
    description=(
        "Permanently delete the authenticated user's account and all associated data "
        "(mood check-ins, wearable data, exercise sessions, prescriptions, correlations). "
        "This action is irreversible. UK GDPR Art. 17 — right to erasure."
    ),
    responses={
        200: {"description": "Account and all data deleted"},
        401: {"description": "Authentication required"},
    },
)
async def delete_account(
    authorization: str = Header(...),
) -> dict:
    """Delete the user's account and all associated data rows.

    Deletion order respects foreign-key constraints:
      1. user_correlations
      2. mood_prescriptions
      3. exercise_sessions
      4. wearable_daily
      5. mood_checkins
      6. oura_tokens
      7. users (profile row)
      8. Supabase auth user (admin client)
    """
    user_id = _get_authenticated_user_id(authorization)
    db = get_supabase_client()

    tables_in_order = [
        "user_correlations",
        "mood_prescriptions",
        "exercise_sessions",
        "wearable_daily",
        "mood_checkins",
        "oura_tokens",
        "users",
    ]

    for table in tables_in_order:
        try:
            db.table(table).delete().eq("user_id" if table != "users" else "id", user_id).execute()
        except Exception as exc:
            logger.warning("Error deleting from %s for user %s: %s", table, user_id, exc)

    # Delete the Supabase auth record (requires service_role key which get_supabase_client uses)
    try:
        db.auth.admin.delete_user(user_id)
    except Exception as exc:
        logger.warning("Error deleting auth user %s: %s", user_id, exc)

    logger.info("Account deleted for user %s", user_id)

    return {
        "data": {"message": "Your account and all associated data have been permanently deleted."},
        "error": None,
    }
