"""
Correlation Service
===================
Computes per-exercise-type mood correlations for a user.

Answers: "Does this user's mood tend to be higher the day after running /
yoga / cycling?" using Pearson correlation on a lag-1 binary exercise signal
vs daily average mood score. Results are stored in the ``user_correlations``
table and consumed by the prescription service.

No PII leaves the infrastructure — this service reads mood_score (integer)
and exercise_type/date (categorical + date) only, all within our own DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_DATA_DAYS = 14
MIN_EXERCISE_SAMPLES = 3
RECOMPUTE_INTERVAL_DAYS = 7
NEW_DATA_THRESHOLD = 7
LAG_DAYS = 1


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CorrelationResult:
    exercise_type: str
    correlation_r: float
    p_value: float
    mood_change_avg: float
    mood_change_pct: float
    sample_size: int
    lag_days: int = LAG_DAYS
    insight_text: str = ""

    @property
    def is_significant(self) -> bool:
        return self.p_value < 0.05 and self.sample_size >= MIN_EXERCISE_SAMPLES


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CorrelationService:
    """Computes and stores exercise–mood correlations per user."""

    def __init__(self) -> None:
        self._db = get_supabase_client()

    async def compute_for_user(self, user_id: str) -> list[CorrelationResult]:
        """Recompute correlations for *user_id* and persist results.

        Returns the list of per-exercise-type results, or ``[]`` if
        there is not enough data or a recent computation is still fresh.
        """
        # --------------------------------------------------------------
        # Skip check — avoid redundant recomputation
        # --------------------------------------------------------------
        latest = (
            self._db.table("user_correlations")
            .select("computed_at")
            .eq("user_id", user_id)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )

        if latest.data:
            last_computed = datetime.fromisoformat(latest.data[0]["computed_at"])
            age = datetime.now(timezone.utc) - last_computed

            if age < timedelta(days=RECOMPUTE_INTERVAL_DAYS):
                # Check for new data since last computation
                new_checkins = (
                    self._db.table("mood_checkins")
                    .select("id", count="exact")
                    .eq("user_id", user_id)
                    .gt("created_at", latest.data[0]["computed_at"])
                    .execute()
                )
                new_exercises = (
                    self._db.table("exercise_sessions")
                    .select("id", count="exact")
                    .eq("user_id", user_id)
                    .gt("created_at", latest.data[0]["computed_at"])
                    .execute()
                )
                new_total = (new_checkins.count or 0) + (new_exercises.count or 0)

                if new_total < NEW_DATA_THRESHOLD:
                    logger.debug(
                        "Skipping correlation recompute for user %s — "
                        "last computed %s ago, %d new records",
                        user_id, age, new_total,
                    )
                    return []

        # --------------------------------------------------------------
        # Fetch data
        # --------------------------------------------------------------
        mood_result = (
            self._db.table("mood_checkins")
            .select("created_at, mood_score")
            .eq("user_id", user_id)
            .execute()
        )
        exercise_result = (
            self._db.table("exercise_sessions")
            .select("date, exercise_type")
            .eq("user_id", user_id)
            .execute()
        )

        if not mood_result.data or not exercise_result.data:
            logger.debug("Not enough data for user %s (mood=%d, exercise=%d)",
                         user_id,
                         len(mood_result.data or []),
                         len(exercise_result.data or []))
            return []

        # --------------------------------------------------------------
        # Build DataFrames
        # --------------------------------------------------------------
        mood_df = pd.DataFrame(mood_result.data)
        mood_df["date"] = pd.to_datetime(mood_df["created_at"]).dt.date
        daily_mood = mood_df.groupby("date")["mood_score"].mean().reset_index()
        daily_mood.columns = ["date", "mood_avg"]
        daily_mood["date"] = pd.to_datetime(daily_mood["date"])

        # Check minimum data span
        date_span = (daily_mood["date"].max() - daily_mood["date"].min()).days
        if date_span < MIN_DATA_DAYS:
            logger.debug("Data span %d days < %d minimum for user %s",
                         date_span, MIN_DATA_DAYS, user_id)
            return []

        ex_df = pd.DataFrame(exercise_result.data)
        ex_df["date"] = pd.to_datetime(ex_df["date"])

        # --------------------------------------------------------------
        # Per exercise_type correlation (lag = 1)
        # --------------------------------------------------------------
        results: list[CorrelationResult] = []
        now = datetime.now(timezone.utc)

        for exercise_type, group in ex_df.groupby("exercise_type"):
            exercise_dates = set(group["date"].dt.date)

            # Build a binary "had exercise yesterday" column aligned to daily_mood
            daily_mood["had_exercise"] = daily_mood["date"].apply(
                lambda d: 1 if (d.date() - timedelta(days=LAG_DAYS)) in exercise_dates else 0
            )

            # Guard: need enough exercise days with following-day mood data
            exercise_day_count = int(daily_mood["had_exercise"].sum())
            if exercise_day_count < MIN_EXERCISE_SAMPLES:
                logger.debug("Skipping %s for user %s — only %d exercise samples",
                             exercise_type, user_id, exercise_day_count)
                continue

            mood_col = daily_mood["mood_avg"].values
            exercise_col = daily_mood["had_exercise"].values

            # Guard: no variance in x means pearsonr is undefined
            if np.std(exercise_col) == 0:
                continue

            r, p = pearsonr(exercise_col, mood_col)

            mood_with = daily_mood.loc[daily_mood["had_exercise"] == 1, "mood_avg"].mean()
            mood_without = daily_mood.loc[daily_mood["had_exercise"] == 0, "mood_avg"].mean()
            mood_change_avg = mood_with - mood_without
            mood_change_pct = (mood_change_avg / mood_without * 100) if mood_without != 0 else 0.0

            # Insight text (regulatory-safe — no clinical language)
            pretty_type = str(exercise_type).replace("_", " ").title()
            direction = "higher" if mood_change_pct >= 0 else "lower"
            if p < 0.05:
                insight = (
                    f"{pretty_type} is linked to {abs(mood_change_pct):.0f}% "
                    f"{direction} mood the following day "
                    f"(n={exercise_day_count}, p={p:.2f})"
                )
            else:
                insight = (
                    f"{pretty_type} shows a small mood association the following day "
                    f"(n={exercise_day_count}, p={p:.2f})"
                )

            results.append(CorrelationResult(
                exercise_type=str(exercise_type),
                correlation_r=float(r),
                p_value=float(p),
                mood_change_avg=float(mood_change_avg),
                mood_change_pct=float(mood_change_pct),
                sample_size=exercise_day_count,
                insight_text=insight,
            ))

        # Clean up temporary column
        daily_mood.drop(columns=["had_exercise"], inplace=True, errors="ignore")

        # --------------------------------------------------------------
        # Store results
        # --------------------------------------------------------------
        if results:
            # Delete previous correlations for this user
            self._db.table("user_correlations").delete().eq("user_id", user_id).execute()

            rows = [
                {
                    "user_id": user_id,
                    "computed_at": now.isoformat(),
                    "exercise_type": r.exercise_type,
                    "mood_change_avg": float(r.mood_change_avg),
                    "mood_change_pct": float(r.mood_change_pct),
                    "correlation_r": float(r.correlation_r),
                    "p_value": float(r.p_value),
                    "sample_size": r.sample_size,
                    "lag_days": r.lag_days,
                    "insight_text": r.insight_text,
                }
                for r in results
            ]
            self._db.table("user_correlations").insert(rows).execute()

            logger.info(
                "Stored %d correlation results for user %s",
                len(results), user_id,
            )

        return results

    async def get_latest_for_user(self, user_id: str) -> list[dict]:
        """Return the most recently computed correlations for *user_id*."""
        result = (
            self._db.table("user_correlations")
            .select("*")
            .eq("user_id", user_id)
            .order("computed_at", desc=True)
            .execute()
        )
        return result.data or []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default_service: CorrelationService | None = None


def get_correlation_service() -> CorrelationService:
    global _default_service
    if _default_service is None:
        _default_service = CorrelationService()
    return _default_service
