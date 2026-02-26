"""
Mood Check-in Schemas
=====================
Pydantic models for the mood check-in API. These are the contract
between the mobile app and the backend.

Key design decisions:
- journal_text is Optional — the app works with just a numeric score
  if the user declines AI processing consent.
- manual_tags provides a fallback classification path when AI is
  disabled or the user opts out.
- AI classification fields are only populated server-side, never
  accepted from the client.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

VALID_MANUAL_TAGS = frozenset({
    "anxious",
    "stressed",
    "low_energy",
    "restless",
    "sad",
    "angry",
    "calm",
    "happy",
    "energetic",
    "focused",
    "grateful",
    "overwhelmed",
})


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class MoodCheckinRequest(BaseModel):
    """Payload the mobile app sends when the user completes a check-in."""

    mood_score: int = Field(
        ...,
        ge=1,
        le=10,
        description="Self-reported mood score. 1 = very low, 10 = excellent.",
    )
    journal_text: Optional[str] = Field(
        default=None,
        max_length=1000,
        description=(
            "Free-text micro-journal entry (1-2 sentences). "
            "Optional — user can check in with just a score. "
            "If provided AND user has AI consent, this is sent through "
            "the anonymisation pipeline → Claude API for classification."
        ),
    )
    manual_tags: Optional[list[str]] = Field(
        default=None,
        description=(
            "User-selected mood tags as a fallback when AI classification "
            "is unavailable or declined. Values must be from the allowed set."
        ),
    )

    # The client must never send AI fields — they're computed server-side.
    # Pydantic will silently ignore extra fields by default, but being
    # explicit about what we accept prevents confusion.


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class MoodClassification(BaseModel):
    """Structured output from the Claude API mood classification."""

    mood_label: str = Field(
        ...,
        description="Primary mood label, e.g. 'anxious', 'stressed', 'happy'.",
    )
    intensity: int = Field(
        ...,
        ge=1,
        le=10,
        description="AI-assessed intensity of the detected mood.",
    )
    themes: list[str] = Field(
        default_factory=list,
        description="Extracted themes, e.g. ['sleep', 'work stress'].",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence in the classification.",
    )


class MoodCheckinResponse(BaseModel):
    """Returned to the mobile app after a successful check-in."""

    id: str = Field(..., description="UUID of the created check-in record.")
    created_at: datetime
    mood_score: int
    journal_text_stored: bool = Field(
        ...,
        description="Whether journal text was stored (True if provided).",
    )
    ai_processed: bool = Field(
        ...,
        description=(
            "Whether the journal text was classified by AI. "
            "False if: no journal text, user declined AI consent, "
            "or AI classification is disabled."
        ),
    )
    classification: Optional[MoodClassification] = Field(
        default=None,
        description="AI mood classification, if processed.",
    )
    manual_tags: Optional[list[str]] = None
