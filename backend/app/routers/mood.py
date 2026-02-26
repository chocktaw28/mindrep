"""
Mood Check-in Router
====================
POST /api/v1/mood/checkin — Submit a daily mood check-in.

This is the highest-traffic endpoint in MindRep and the primary data
ingestion point for the correlation engine. Every check-in flows through
a strict data protection pipeline:

    1. Verify user exists and is authenticated
    2. Verify mood_data_consent is granted
    3. Validate manual_tags against allowed set
    4. Store the check-in record (raw journal text stays in our DB only)
    5. IF journal text provided AND ai_processing_consent granted AND
       AI classification enabled → anonymise text → classify via Claude API
    6. Update the check-in record with AI classification results
    7. Return the complete check-in to the client

If AI classification fails for any reason, the check-in still succeeds —
the user's data is saved, just without AI labels. Classification failures
are logged but never block the check-in flow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from app.config import get_settings
from app.db.supabase import get_supabase_client
from app.models.mood import (
    VALID_MANUAL_TAGS,
    MoodCheckinRequest,
    MoodCheckinResponse,
    MoodClassification,
)
from app.services.mood_classifier import get_mood_classifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mood", tags=["mood"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_authenticated_user(authorization: str) -> dict:
    """Verify the JWT and return the user record from Supabase.

    In production this validates the Supabase JWT from the Authorization
    header. For the MVP, we use Supabase's built-in auth to verify the
    token and fetch the user record in one call.

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

    # Fetch the full user record (with consent fields) from our users table
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


def _validate_manual_tags(tags: Optional[list[str]]) -> Optional[list[str]]:
    """Validate manual mood tags against the allowed set.

    Returns the validated list or raises HTTPException 422 if any
    tags are invalid. We validate strictly because these tags feed
    into the correlation engine — garbage in, garbage out.
    """
    if not tags:
        return tags

    invalid = [t for t in tags if t not in VALID_MANUAL_TAGS]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Invalid manual tags: {', '.join(invalid)}",
                "code": "invalid_tags",
                "valid_tags": sorted(VALID_MANUAL_TAGS),
            },
        )
    return tags


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/checkin",
    response_model=MoodCheckinResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a mood check-in",
    description=(
        "Record a daily mood check-in with an optional journal entry. "
        "If AI processing consent is granted and journal text is provided, "
        "the text is anonymised and classified via AI for structured mood labels."
    ),
    responses={
        201: {"description": "Check-in created successfully"},
        401: {"description": "Authentication required"},
        403: {"description": "Mood data consent not granted"},
        422: {"description": "Validation error (invalid score, tags, etc.)"},
    },
)
async def submit_mood_checkin(
    body: MoodCheckinRequest,
    authorization: str = Header(..., description="Bearer token from Supabase Auth"),
) -> MoodCheckinResponse:
    """Submit a mood check-in.

    The full data flow:
    1. Auth + consent verification
    2. Insert check-in record (journal text stored in our DB only)
    3. If eligible: anonymise journal → Claude API → store AI labels
    4. Return complete record to client
    """
    settings = get_settings()

    # ------------------------------------------------------------------
    # 1. Auth & consent checks
    # ------------------------------------------------------------------
    user = _get_authenticated_user(authorization)
    user_id: str = user["id"]

    # Mood data consent is REQUIRED — cannot use the product without it.
    # This is a UK GDPR Article 9 explicit consent requirement.
    if not user.get("mood_data_consent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    "Mood data consent is required to submit check-ins. "
                    "Please grant consent in your settings."
                ),
                "code": "consent_required",
            },
        )

    # ------------------------------------------------------------------
    # 2. Validate inputs
    # ------------------------------------------------------------------
    validated_tags = _validate_manual_tags(body.manual_tags)

    # ------------------------------------------------------------------
    # 3. Insert the check-in record
    # ------------------------------------------------------------------
    db = get_supabase_client()

    insert_data: dict = {
        "user_id": user_id,
        "mood_score": body.mood_score,
        "journal_text": body.journal_text,  # stored encrypted at rest in Supabase
        "manual_tags": validated_tags,
        "ai_processed": False,
    }

    result = db.table("mood_checkins").insert(insert_data).execute()

    if not result.data or len(result.data) == 0:
        logger.error("Failed to insert mood check-in for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to save check-in", "code": "db_error"},
        )

    checkin = result.data[0]
    checkin_id: str = checkin["id"]

    # ------------------------------------------------------------------
    # 4. AI classification (if eligible)
    # ------------------------------------------------------------------
    # Three conditions must ALL be true:
    #   a) Journal text was provided (can't classify nothing)
    #   b) User has granted ai_processing_consent (GDPR Art. 9)
    #   c) AI classification is enabled globally (kill switch)
    classification: Optional[MoodClassification] = None
    ai_processed = False

    has_journal = bool(body.journal_text and body.journal_text.strip())
    has_ai_consent = bool(user.get("ai_processing_consent"))
    ai_enabled = settings.enable_ai_classification

    if has_journal and has_ai_consent and ai_enabled:
        try:
            classifier = get_mood_classifier()
            # classify() handles the full pipeline:
            #   raw text → anonymisation → Claude API → structured labels
            classification = await classifier.classify(body.journal_text)

            if classification:
                # Update the check-in record with AI results
                db.table("mood_checkins").update({
                    "ai_mood_label": classification.mood_label,
                    "ai_intensity": classification.intensity,
                    "ai_themes": classification.themes,
                    "ai_confidence": classification.confidence,
                    "ai_processed": True,
                }).eq("id", checkin_id).execute()

                ai_processed = True
                logger.info(
                    "Mood classified for checkin %s: %s (confidence: %.2f)",
                    checkin_id,
                    classification.mood_label,
                    classification.confidence,
                )

        except Exception:
            # Classification failure must NEVER block the check-in.
            # The user's data is already saved — we just won't have AI labels.
            logger.exception(
                "AI classification failed for checkin %s (non-blocking)",
                checkin_id,
            )

    elif has_journal and not has_ai_consent:
        logger.debug(
            "Skipping AI classification for checkin %s: user declined AI consent",
            checkin_id,
        )
    elif has_journal and not ai_enabled:
        logger.debug(
            "Skipping AI classification for checkin %s: AI classification disabled",
            checkin_id,
        )

    # ------------------------------------------------------------------
    # 5. Build response
    # ------------------------------------------------------------------
    return MoodCheckinResponse(
        id=checkin_id,
        created_at=checkin["created_at"],
        mood_score=body.mood_score,
        journal_text_stored=has_journal,
        ai_processed=ai_processed,
        classification=classification,
        manual_tags=validated_tags,
    )
