"""
Tests for PrescriptionService
==============================
Covers:
- _detect_mood_state: all mood states via ai_mood_label, ai_themes, manual_tags;
  priority ordering (label > themes > tags)
- Correlation path: user with n≥14 significant correlations → correlation-based
  prescription (source, exercise_type, duration/intensity from mood-state defaults,
  confidence formula, reasoning format)
- Rule-based fallback: all 7 mood states → correct exercise, duration, intensity,
  confidence, source
- No check-in data → generate_for_user returns None
- Confidence formula: min(0.95, 0.75 + (n-14)*0.01), capped at 0.95
- DB write: insert called; returned MoodPrescription is valid
- Reasoning strings: no banned clinical language across all defaults
- poor_sleep reasoning includes bedtime warning
- low_mood reasoning uses 'mood support', not 'depression'
- get_latest_for_user: returns stored rows, empty list when none

Run: pytest tests/test_prescription.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.prescription import MoodPrescription
from app.services.prescription import (
    MIN_PRESCRIPTION_SAMPLES,
    RULE_BASED_DEFAULTS,
    PrescriptionService,
    _detect_mood_state,
)

USER_ID = str(uuid.uuid4())

# Banned terms per CLAUDE.md regulatory rules — checked in reasoning strings only
_BANNED_TERMS = {
    "diagnose", "treat", "cure", "therapy", "clinical",
    "symptoms", "condition", "disorder", "depression",
}

# Checkin payload that triggers each of the 7 mood states.
# Used by the parametrised rule-based fallback tests.
_STATE_CHECKINS: dict[str, dict] = {
    "anxiety":    {"ai_mood_label": "anxious"},
    "stress":     {"ai_mood_label": "stressed"},
    "low_mood":   {"ai_mood_label": "sad"},
    "poor_sleep": {"ai_mood_label": "", "ai_themes": ["sleep"]},
    "low_energy": {"ai_mood_label": "low_energy"},
    "positive":   {"ai_mood_label": "calm"},
    "unknown":    {"mood_score": 5},  # non-empty but no recognisable label/theme/tag
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_checkin(
    ai_mood_label: str = "",
    ai_themes: list[str] | None = None,
    manual_tags: list[str] | None = None,
    mood_score: int = 5,
) -> dict:
    return {
        "ai_mood_label": ai_mood_label,
        "ai_themes": ai_themes or [],
        "manual_tags": manual_tags or [],
        "mood_score": mood_score,
    }


def _make_correlation(
    exercise_type: str = "running",
    mood_change_pct: float = 15.0,
    p_value: float = 0.03,
    sample_size: int = 20,
) -> dict:
    return {
        "exercise_type": exercise_type,
        "mood_change_pct": mood_change_pct,
        "p_value": p_value,
        "sample_size": sample_size,
        "insight_text": (
            f"{exercise_type} is linked to {mood_change_pct:.0f}% higher mood "
            f"(n={sample_size}, p={p_value:.2f})"
        ),
    }


class _FakeTableRouter:
    """Dispatches table() calls to per-table mock data for PrescriptionService.

    Simulates Supabase insert by appending a UUID 'id' to the inserted row,
    matching real database behaviour. The inserted row is accessible via
    ``last_inserted`` for post-call assertions.
    """

    def __init__(
        self,
        checkin_data: list[dict],
        correlation_data: list[dict],
        latest_prescription_data: list[dict] | None = None,
    ) -> None:
        self._checkin = checkin_data
        self._correlation = correlation_data
        self._latest = latest_prescription_data or []
        self.last_inserted: dict = {}

    def table(self, name: str) -> MagicMock:
        mock = MagicMock()
        chain = mock
        for method in ("select", "eq", "lt", "gte", "order", "limit"):
            getattr(chain, method).return_value = chain

        if name == "mood_checkins":
            result = MagicMock()
            result.data = self._checkin
            chain.execute.return_value = result

        elif name == "user_correlations":
            result = MagicMock()
            result.data = self._correlation
            chain.execute.return_value = result

        elif name == "mood_prescriptions":
            router = self

            def do_insert(row: dict) -> MagicMock:
                # Simulate Supabase returning the row with a generated id
                stored = {**row, "id": str(uuid.uuid4())}
                router.last_inserted = stored
                ins_mock = MagicMock()
                ins_mock.execute.return_value.data = [stored]
                return ins_mock

            mock.insert = do_insert

            # SELECT path — used by get_latest_for_user
            sel_result = MagicMock()
            sel_result.data = self._latest
            chain.execute.return_value = sel_result

        return mock


def _build_service(router: _FakeTableRouter) -> PrescriptionService:
    """Instantiate PrescriptionService with a mocked Supabase client."""
    with patch("app.services.prescription.get_supabase_client") as mock_get:
        mock_db = MagicMock()
        mock_db.table = router.table
        mock_get.return_value = mock_db
        svc = PrescriptionService()
    return svc


# ---------------------------------------------------------------------------
# _detect_mood_state unit tests
# ---------------------------------------------------------------------------

class TestDetectMoodState:
    """Pure unit tests — no DB, no async."""

    # --- ai_mood_label mappings ---

    def test_anxious_label_maps_to_anxiety(self):
        assert _detect_mood_state({"ai_mood_label": "anxious"}) == "anxiety"

    def test_anxiety_label_maps_to_anxiety(self):
        assert _detect_mood_state({"ai_mood_label": "anxiety"}) == "anxiety"

    def test_stressed_label_maps_to_stress(self):
        assert _detect_mood_state({"ai_mood_label": "stressed"}) == "stress"

    def test_overwhelmed_label_maps_to_stress(self):
        assert _detect_mood_state({"ai_mood_label": "overwhelmed"}) == "stress"

    def test_sad_label_maps_to_low_mood(self):
        assert _detect_mood_state({"ai_mood_label": "sad"}) == "low_mood"

    def test_low_energy_label_maps_to_low_energy(self):
        assert _detect_mood_state({"ai_mood_label": "low_energy"}) == "low_energy"

    @pytest.mark.parametrize("label", ["calm", "happy", "energetic", "focused", "grateful"])
    def test_positive_labels_map_to_positive(self, label: str):
        assert _detect_mood_state({"ai_mood_label": label}) == "positive"

    # --- ai_themes fallback ---

    def test_sleep_theme_maps_to_poor_sleep(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["sleep"]}) == "poor_sleep"

    def test_anxiety_theme_maps_to_anxiety(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["anxiety"]}) == "anxiety"

    def test_stress_theme_maps_to_stress(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["stress"]}) == "stress"

    def test_work_stress_theme_maps_to_stress(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["work stress"]}) == "stress"

    def test_low_energy_theme_maps_to_low_energy(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["low energy"]}) == "low_energy"

    def test_fatigue_theme_maps_to_low_energy(self):
        assert _detect_mood_state({"ai_mood_label": "", "ai_themes": ["fatigue"]}) == "low_energy"

    # --- manual_tags fallback ---

    def test_anxious_tag_maps_to_anxiety(self):
        assert _detect_mood_state({"manual_tags": ["anxious"]}) == "anxiety"

    def test_stressed_tag_maps_to_stress(self):
        assert _detect_mood_state({"manual_tags": ["stressed"]}) == "stress"

    def test_overwhelmed_tag_maps_to_stress(self):
        assert _detect_mood_state({"manual_tags": ["overwhelmed"]}) == "stress"

    def test_sad_tag_maps_to_low_mood(self):
        assert _detect_mood_state({"manual_tags": ["sad"]}) == "low_mood"

    def test_low_energy_tag_maps_to_low_energy(self):
        assert _detect_mood_state({"manual_tags": ["low_energy"]}) == "low_energy"

    def test_restless_tag_maps_to_poor_sleep(self):
        assert _detect_mood_state({"manual_tags": ["restless"]}) == "poor_sleep"

    # --- fallthrough ---

    def test_empty_dict_is_unknown(self):
        assert _detect_mood_state({}) == "unknown"

    def test_unrecognised_label_falls_to_unknown(self):
        assert _detect_mood_state({"ai_mood_label": "confused"}) == "unknown"

    def test_none_label_falls_through(self):
        assert _detect_mood_state({"ai_mood_label": None}) == "unknown"

    # --- priority ordering ---

    def test_ai_mood_label_beats_themes(self):
        """A recognised label should win even when themes point elsewhere."""
        result = _detect_mood_state({"ai_mood_label": "stressed", "ai_themes": ["sleep"]})
        assert result == "stress"

    def test_themes_beat_tags(self):
        """Themes should win over manual_tags when label is absent."""
        result = _detect_mood_state({
            "ai_mood_label": "",
            "ai_themes": ["sleep"],
            "manual_tags": ["anxious"],
        })
        assert result == "poor_sleep"


# ---------------------------------------------------------------------------
# Correlation path
# ---------------------------------------------------------------------------

class TestCorrelationPath:
    """User with n≥14, p<0.05 correlations → personalised prescription."""

    @pytest.mark.asyncio
    async def test_source_is_correlation(self):
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[_make_correlation(sample_size=20)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert isinstance(result, MoodPrescription)
        assert result.source == "correlation"

    @pytest.mark.asyncio
    async def test_exercise_type_comes_from_correlation(self):
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="stressed")],
            correlation_data=[_make_correlation(exercise_type="cycling", sample_size=18)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert result.exercise_type == "cycling"

    @pytest.mark.asyncio
    async def test_duration_and_intensity_from_mood_state_defaults(self):
        """Duration/intensity are sourced from mood-state defaults, not the correlation row."""
        # anxiety mood state → 25 min, moderate (from RULE_BASED_DEFAULTS)
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[_make_correlation(exercise_type="running", sample_size=16)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        anxiety_defaults = RULE_BASED_DEFAULTS["anxiety"]
        assert result.suggested_duration_minutes == anxiety_defaults["suggested_duration_minutes"]
        assert result.suggested_intensity == anxiety_defaults["suggested_intensity"]

    @pytest.mark.asyncio
    async def test_confidence_formula(self):
        """confidence = min(0.95, 0.75 + (n - 14) * 0.01)"""
        n = 20
        expected = 0.75 + (n - MIN_PRESCRIPTION_SAMPLES) * 0.01  # 0.81

        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="stressed")],
            correlation_data=[_make_correlation(sample_size=n)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert result.confidence == pytest.approx(expected, abs=1e-9)

    @pytest.mark.asyncio
    async def test_confidence_capped_at_0_95(self):
        """Confidence must not exceed 0.95 regardless of sample size."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="stressed")],
            correlation_data=[_make_correlation(sample_size=100)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert result.confidence <= 0.95

    @pytest.mark.asyncio
    async def test_reasoning_mentions_exercise_pct_p_n(self):
        """Correlation reasoning must reference the key data points shown to the user."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[_make_correlation(
                exercise_type="running",
                mood_change_pct=15.0,
                p_value=0.03,
                sample_size=20,
            )],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        reasoning = router.last_inserted["reasoning"]
        assert "running" in reasoning.lower()
        assert "15%" in reasoning
        assert "p=0.03" in reasoning
        assert "n=20" in reasoning

    @pytest.mark.asyncio
    async def test_returns_valid_mood_prescription_model(self):
        """Return value must deserialise cleanly into MoodPrescription."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="calm")],
            correlation_data=[_make_correlation(exercise_type="yoga", sample_size=14)],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert isinstance(result, MoodPrescription)
        assert result.id  # non-empty UUID
        assert result.exercise_type == "yoga"


# ---------------------------------------------------------------------------
# Rule-based fallback — all 7 mood states
# ---------------------------------------------------------------------------

class TestRuleBasedFallback:
    """No qualifying correlations → population-level defaults used."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", list(RULE_BASED_DEFAULTS.keys()))
    async def test_each_state_maps_to_correct_defaults(self, state: str):
        expected = RULE_BASED_DEFAULTS[state]
        checkin = _STATE_CHECKINS[state]

        router = _FakeTableRouter(
            checkin_data=[checkin],
            correlation_data=[],  # no qualifying correlations
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert result.source == "rule_based"
        assert result.exercise_type == expected["exercise_type"]
        assert result.suggested_duration_minutes == expected["suggested_duration_minutes"]
        assert result.suggested_intensity == expected["suggested_intensity"]
        assert result.confidence == pytest.approx(expected["confidence"])

    @pytest.mark.asyncio
    async def test_returns_valid_mood_prescription_model(self):
        """Rule-based result must deserialise cleanly into MoodPrescription."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[],
        )
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert isinstance(result, MoodPrescription)
        assert result.id
        assert result.source == "rule_based"


# ---------------------------------------------------------------------------
# No check-in data
# ---------------------------------------------------------------------------

class TestNoCheckinData:

    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkin(self):
        """generate_for_user should return None if the user has no check-ins."""
        router = _FakeTableRouter(checkin_data=[], correlation_data=[])
        svc = _build_service(router)
        result = await svc.generate_for_user(USER_ID)

        assert result is None


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

class TestDBWrite:

    @pytest.mark.asyncio
    async def test_insert_called_with_user_id(self):
        """The prescription must be persisted with the correct user_id."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="stressed")],
            correlation_data=[],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        assert router.last_inserted["user_id"] == USER_ID

    @pytest.mark.asyncio
    async def test_insert_contains_required_fields(self):
        """Inserted row must contain all fields MoodPrescription needs."""
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="sad")],
            correlation_data=[],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        row = router.last_inserted
        for field in ("id", "user_id", "created_at", "exercise_type",
                      "suggested_duration_minutes", "suggested_intensity",
                      "reasoning", "confidence", "source"):
            assert field in row, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_correlation_path_insert_stores_correct_source(self):
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[_make_correlation(sample_size=16)],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        assert router.last_inserted["source"] == "correlation"

    @pytest.mark.asyncio
    async def test_rule_based_path_insert_stores_correct_source(self):
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="anxious")],
            correlation_data=[],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        assert router.last_inserted["source"] == "rule_based"


# ---------------------------------------------------------------------------
# Regulatory language
# ---------------------------------------------------------------------------

class TestRegulatoryLanguage:
    """Reasoning strings must not contain banned clinical language."""

    @pytest.mark.parametrize("state", list(RULE_BASED_DEFAULTS.keys()))
    def test_rule_based_reasoning_no_banned_terms(self, state: str):
        reasoning = RULE_BASED_DEFAULTS[state]["reasoning"].lower()
        found = {term for term in _BANNED_TERMS if term in reasoning}
        assert not found, f"Banned term(s) {found} found in {state!r} reasoning"

    @pytest.mark.asyncio
    async def test_correlation_reasoning_no_banned_terms(self):
        router = _FakeTableRouter(
            checkin_data=[_make_checkin(ai_mood_label="stressed")],
            correlation_data=[_make_correlation(
                exercise_type="running", mood_change_pct=12.0, p_value=0.04, sample_size=18,
            )],
        )
        svc = _build_service(router)
        await svc.generate_for_user(USER_ID)

        reasoning = router.last_inserted["reasoning"].lower()
        found = {term for term in _BANNED_TERMS if term in reasoning}
        assert not found, f"Banned term(s) {found} found in correlation reasoning"

    def test_poor_sleep_reasoning_includes_bedtime_warning(self):
        reasoning = RULE_BASED_DEFAULTS["poor_sleep"]["reasoning"].lower()
        assert "bedtime" in reasoning

    def test_low_mood_reasoning_does_not_mention_depression(self):
        reasoning = RULE_BASED_DEFAULTS["low_mood"]["reasoning"].lower()
        assert "depression" not in reasoning

    def test_low_mood_reasoning_uses_mood_support_language(self):
        reasoning = RULE_BASED_DEFAULTS["low_mood"]["reasoning"].lower()
        assert "mood" in reasoning


# ---------------------------------------------------------------------------
# get_latest_for_user
# ---------------------------------------------------------------------------

class TestGetLatest:

    @pytest.mark.asyncio
    async def test_returns_stored_prescriptions(self):
        stored = [
            {"id": str(uuid.uuid4()), "exercise_type": "walking", "source": "rule_based"},
            {"id": str(uuid.uuid4()), "exercise_type": "yoga",    "source": "correlation"},
        ]
        router = _FakeTableRouter(
            checkin_data=[],
            correlation_data=[],
            latest_prescription_data=stored,
        )
        svc = _build_service(router)
        rows = await svc.get_latest_for_user(USER_ID)

        assert len(rows) == 2
        assert rows[0]["exercise_type"] == "walking"
        assert rows[1]["exercise_type"] == "yoga"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_prescriptions(self):
        router = _FakeTableRouter(
            checkin_data=[],
            correlation_data=[],
            latest_prescription_data=[],
        )
        svc = _build_service(router)
        rows = await svc.get_latest_for_user(USER_ID)

        assert rows == []
