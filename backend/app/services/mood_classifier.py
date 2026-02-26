"""
Mood Classifier Service
=======================
Classifies mood from journal text using the Claude API.

DATA PROTECTION FLOW (non-negotiable):
    1. Raw journal text arrives from the check-in endpoint
    2. AnonymisationService strips all PII
    3. ONLY the anonymised text is sent to Claude — no user ID, no
       session ID, no timestamp, no device fingerprint, nothing
    4. Claude returns structured JSON: mood_label, intensity, themes, confidence
    5. Structured labels are stored in Supabase linked to the user record
    6. Raw journal text is stored ONLY in MindRep's encrypted database

The Claude API call uses zero-retention where available and includes a
system prompt instructing the model to return only the classification
and ignore any residual identifying information.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.config import Settings, get_settings
from app.models.mood import MoodClassification
from app.services.anonymisation import AnonymisationService, get_anonymisation_service

logger = logging.getLogger(__name__)

# System prompt for mood classification — instructs Claude to return
# ONLY structured JSON and to ignore any residual PII that may have
# survived the anonymisation pipeline. Belt and braces.
_SYSTEM_PROMPT = """\
You are a mood classification engine for a wellness app. You receive \
anonymised journal entries and return structured mood analysis.

Rules:
- Return ONLY valid JSON with no markdown formatting, no backticks, no explanation.
- If the text contains any residual identifying information (names, places, \
organisations), IGNORE it completely — do not include it in your output.
- Classify the PRIMARY mood expressed in the text.
- Be sensitive to informal language, slang, sarcasm, and code-switching.

Required JSON schema:
{
  "mood_label": "<primary mood: one of: happy, sad, anxious, stressed, angry, \
calm, energetic, tired, overwhelmed, hopeful, frustrated, grateful, lonely, \
restless, focused, low>",
  "intensity": <1-10 integer, how strongly the mood is expressed>,
  "themes": [<list of 0-3 short theme strings, e.g. "sleep", "work stress", \
"exercise", "relationships", "academic pressure">],
  "confidence": <0.0-1.0 float, your confidence in this classification>
}
"""


class MoodClassifierService:
    """Classifies mood from anonymised journal text via the Claude API."""

    def __init__(
        self,
        settings: Settings | None = None,
        anonymiser: AnonymisationService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._anonymiser = anonymiser or get_anonymisation_service()
        self._api_url = "https://api.anthropic.com/v1/messages"

    async def classify(self, raw_journal_text: str) -> Optional[MoodClassification]:
        """Anonymise the journal text and classify mood via Claude API.

        Returns a MoodClassification on success, or None if classification
        fails (API error, invalid response, etc.). Failures are logged but
        never raised — a failed classification should not block the check-in.
        """
        if not raw_journal_text or not raw_journal_text.strip():
            return None

        # STEP 1: Anonymise — this is the critical data protection gate.
        # prepare_api_payload() returns ONLY the sanitised text string.
        anonymised_text = self._anonymiser.prepare_api_payload(raw_journal_text)

        if not anonymised_text:
            logger.warning("Anonymisation produced empty text, skipping classification")
            return None

        # STEP 2: Call Claude API with ONLY the anonymised text.
        # No user ID, no session ID, no metadata of any kind.
        try:
            classification_json = await self._call_claude_api(anonymised_text)
        except Exception:
            logger.exception("Claude API call failed for mood classification")
            return None

        # STEP 3: Parse the structured response.
        try:
            return self._parse_response(classification_json)
        except Exception:
            logger.exception(
                "Failed to parse Claude classification response: %s",
                classification_json[:200] if classification_json else "empty",
            )
            return None

    async def _call_claude_api(self, anonymised_text: str) -> str:
        """Send anonymised text to Claude and return the raw response text.

        The request contains ZERO identifying information:
        - No user ID
        - No session ID
        - No timestamp
        - No device fingerprint
        - Only the anonymised journal text
        """
        headers = {
            "x-api-key": self._settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self._settings.anthropic_model,
            "max_tokens": self._settings.anthropic_max_tokens,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": anonymised_text,
                }
            ],
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._api_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()

        # Extract text from the response content blocks
        text_parts = [
            block["text"]
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        return "\n".join(text_parts)

    def _parse_response(self, raw_response: str) -> MoodClassification:
        """Parse Claude's JSON response into a validated MoodClassification.

        Handles common Claude response quirks: markdown code fences,
        leading/trailing whitespace, and extra commentary before/after JSON.
        """
        text = raw_response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]  # remove opening fence line
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        # Try to find JSON object if there's extra text around it
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

        parsed = json.loads(text)
        return MoodClassification(**parsed)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default_classifier: MoodClassifierService | None = None


def get_mood_classifier() -> MoodClassifierService:
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = MoodClassifierService()
    return _default_classifier
