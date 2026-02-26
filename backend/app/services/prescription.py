"""
Prescription Service
====================
Generates personalised exercise recommendations based on a user's current
mood state and their exercise–mood correlation data.

Decision logic:
    1. Fetch the user's most recent mood check-in.
    2. Map the check-in data to a mood state string.
    3. If the user has statistically significant personal correlation data
       (p < 0.05, n ≥ 14), build a correlation-based recommendation.
    4. Otherwise, fall back to population-level rule-based defaults.
    5. Persist the prescription to mood_prescriptions and return it.

Regulatory note: all reasoning strings avoid clinical language (no
diagnose / treat / cure / symptoms / condition / disorder). Biometric data
never leaves our infrastructure — this service reads only exercise type,
mood scores, and mood labels, all stored within our own database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.supabase import get_supabase_client
from app.models.prescription import MoodPrescription

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PRESCRIPTION_SAMPLES = 14  # minimum n for a correlation to drive a prescription

# ---------------------------------------------------------------------------
# Rule-based defaults keyed by mood state
# ---------------------------------------------------------------------------

RULE_BASED_DEFAULTS: dict[str, dict] = {
    "anxiety": {
        "exercise_type": "walking",
        "suggested_duration_minutes": 25,
        "suggested_intensity": "moderate",
        "confidence": 0.60,
        "reasoning": (
            "A brisk walk is widely associated with reduced tension and supports "
            "a calmer mood. A 25-minute moderate-paced session outdoors is suggested "
            "for today's wellness support."
        ),
    },
    "stress": {
        "exercise_type": "yoga",
        "suggested_duration_minutes": 25,
        "suggested_intensity": "moderate",
        "confidence": 0.60,
        "reasoning": (
            "Yoga combines gentle movement with breathing focus, which is linked to "
            "lower perceived stress. A 25-minute moderate session is suggested to "
            "support your wellbeing today."
        ),
    },
    "low_mood": {
        "exercise_type": "jogging",
        "suggested_duration_minutes": 30,
        "suggested_intensity": "vigorous",
        "confidence": 0.65,
        "reasoning": (
            "Elevated-intensity aerobic exercise is associated with mood support "
            "through increased energy and focus. A 30-minute jog is suggested as "
            "a mood-positive activity for today."
        ),
    },
    "poor_sleep": {
        "exercise_type": "resistance training",
        "suggested_duration_minutes": 30,
        "suggested_intensity": "moderate",
        "confidence": 0.55,
        "reasoning": (
            "Moderate resistance training supports sleep quality over time. A "
            "30-minute session is suggested — avoid scheduling within 2 hours of "
            "bedtime to support restful sleep."
        ),
    },
    "low_energy": {
        "exercise_type": "walking",
        "suggested_duration_minutes": 17,
        "suggested_intensity": "low",
        "confidence": 0.55,
        "reasoning": (
            "Light movement is associated with a gentle energy lift when fatigue "
            "is present. A short 17-minute low-intensity walk is suggested to "
            "support your energy levels today."
        ),
    },
    "positive": {
        "exercise_type": "walking",
        "suggested_duration_minutes": 20,
        "suggested_intensity": "moderate",
        "confidence": 0.50,
        "reasoning": (
            "Maintaining an active habit on positive-mood days is associated with "
            "sustained wellbeing. A 20-minute moderate walk is suggested to build "
            "on today's good start."
        ),
    },
    "unknown": {
        "exercise_type": "walking",
        "suggested_duration_minutes": 20,
        "suggested_intensity": "moderate",
        "confidence": 0.45,
        "reasoning": (
            "A gentle 20-minute walk is a broadly beneficial starting point for "
            "daily wellness. It is suggested as a low-barrier activity to support "
            "your mood and energy today."
        ),
    },
}

# Mood-state defaults used to fill in duration/intensity when we have a
# correlation-based exercise_type but need contextually appropriate values.
_MOOD_STATE_PARAMS: dict[str, dict] = {
    state: {
        "suggested_duration_minutes": v["suggested_duration_minutes"],
        "suggested_intensity": v["suggested_intensity"],
    }
    for state, v in RULE_BASED_DEFAULTS.items()
}


# ---------------------------------------------------------------------------
# Mood state detection helper
# ---------------------------------------------------------------------------

def _detect_mood_state(checkin: dict) -> str:
    """Map check-in data to a mood state string.

    Priority order: ai_mood_label → ai_themes → manual_tags.
    Returns one of: 'anxiety', 'stress', 'low_mood', 'poor_sleep',
    'low_energy', 'positive', 'unknown'.
    """
    label = (checkin.get("ai_mood_label") or "").lower().strip()

    # --- ai_mood_label ---
    if label in {"anxious", "anxiety"}:
        return "anxiety"
    if label in {"stressed", "overwhelmed"}:
        return "stress"
    if label == "sad":
        return "low_mood"
    if label == "low_energy":
        return "low_energy"
    if label in {"calm", "happy", "energetic", "focused", "grateful"}:
        return "positive"

    # --- ai_themes ---
    themes: list[str] = checkin.get("ai_themes") or []
    themes_lower = [t.lower() for t in themes]

    if "sleep" in themes_lower:
        return "poor_sleep"
    if "anxiety" in themes_lower:
        return "anxiety"
    if any(t in themes_lower for t in ("stress", "work stress")):
        return "stress"
    if any(t in themes_lower for t in ("low energy", "fatigue")):
        return "low_energy"

    # --- manual_tags ---
    tags: list[str] = checkin.get("manual_tags") or []
    tags_lower = [t.lower() for t in tags]

    if "anxious" in tags_lower:
        return "anxiety"
    if any(t in tags_lower for t in ("stressed", "overwhelmed")):
        return "stress"
    if "sad" in tags_lower:
        return "low_mood"
    if "low_energy" in tags_lower:
        return "low_energy"
    if "restless" in tags_lower:
        return "poor_sleep"

    return "unknown"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PrescriptionService:
    """Generates and stores exercise prescriptions for users."""

    def __init__(self) -> None:
        self._db = get_supabase_client()

    async def generate_for_user(self, user_id: str) -> MoodPrescription | None:
        """Generate an exercise prescription for *user_id*.

        Returns a stored MoodPrescription, or None if no check-in data
        exists for the user.
        """
        # ------------------------------------------------------------------
        # Step 1: Fetch the user's latest mood check-in
        # ------------------------------------------------------------------
        checkin_result = (
            self._db.table("mood_checkins")
            .select("ai_mood_label, ai_themes, mood_score, manual_tags")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        checkin = checkin_result.data[0] if checkin_result.data else {}

        if not checkin:
            logger.info("No check-in data for user %s — cannot generate prescription", user_id)
            return None

        # ------------------------------------------------------------------
        # Step 2: Detect mood state
        # ------------------------------------------------------------------
        mood_state = _detect_mood_state(checkin)
        logger.debug("Detected mood state '%s' for user %s", mood_state, user_id)

        # ------------------------------------------------------------------
        # Step 3: Try correlation-based recommendation
        # ------------------------------------------------------------------
        corr_result = (
            self._db.table("user_correlations")
            .select("exercise_type, mood_change_pct, p_value, sample_size, insight_text")
            .eq("user_id", user_id)
            .lt("p_value", 0.05)
            .gte("sample_size", MIN_PRESCRIPTION_SAMPLES)
            .order("mood_change_pct", desc=True)
            .limit(1)
            .execute()
        )

        now = datetime.now(timezone.utc)

        if corr_result.data:
            corr = corr_result.data[0]
            exercise_type = corr["exercise_type"]
            pct = float(corr["mood_change_pct"])
            p_val = float(corr["p_value"])
            n = int(corr["sample_size"])

            state_params = _MOOD_STATE_PARAMS.get(mood_state, _MOOD_STATE_PARAMS["unknown"])
            duration = state_params["suggested_duration_minutes"]
            intensity = state_params["suggested_intensity"]

            pretty_type = exercise_type.replace("_", " ").title()
            reasoning = (
                f"Based on your personal data, {pretty_type} is linked to "
                f"{pct:.0f}% higher mood the following day "
                f"(p={p_val:.2f}, n={n}). "
                f"A {duration}-minute {intensity} session is suggested."
            )
            confidence = min(0.95, 0.75 + (n - MIN_PRESCRIPTION_SAMPLES) * 0.01)

            row = {
                "user_id": user_id,
                "created_at": now.isoformat(),
                "exercise_type": exercise_type,
                "suggested_duration_minutes": duration,
                "suggested_intensity": intensity,
                "reasoning": reasoning,
                "confidence": float(confidence),
                "source": "correlation",
            }
            logger.info(
                "Correlation-based prescription for user %s: %s (confidence=%.2f)",
                user_id, exercise_type, confidence,
            )

        # ------------------------------------------------------------------
        # Step 4: Rule-based fallback
        # ------------------------------------------------------------------
        else:
            defaults = RULE_BASED_DEFAULTS.get(mood_state, RULE_BASED_DEFAULTS["unknown"])
            row = {
                "user_id": user_id,
                "created_at": now.isoformat(),
                "exercise_type": defaults["exercise_type"],
                "suggested_duration_minutes": defaults["suggested_duration_minutes"],
                "suggested_intensity": defaults["suggested_intensity"],
                "reasoning": defaults["reasoning"],
                "confidence": float(defaults["confidence"]),
                "source": "rule_based",
            }
            logger.info(
                "Rule-based prescription for user %s: %s (mood_state=%s)",
                user_id, defaults["exercise_type"], mood_state,
            )

        # ------------------------------------------------------------------
        # Step 5: Store and return
        # ------------------------------------------------------------------
        insert_result = self._db.table("mood_prescriptions").insert(row).execute()
        stored = insert_result.data[0] if insert_result.data else row

        return MoodPrescription(**stored)

    async def get_latest_for_user(self, user_id: str) -> list[dict]:
        """Return all stored prescriptions for *user_id*, newest first."""
        result = (
            self._db.table("mood_prescriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default_service: PrescriptionService | None = None


def get_prescription_service() -> PrescriptionService:
    global _default_service
    if _default_service is None:
        _default_service = PrescriptionService()
    return _default_service
