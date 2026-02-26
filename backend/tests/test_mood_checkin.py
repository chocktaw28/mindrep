"""
Tests for POST /api/v1/mood/checkin
====================================
Covers:
- Happy path: score-only check-in
- Happy path: score + journal text with AI classification
- Happy path: score + manual tags (no journal)
- Consent enforcement: mood_data_consent required
- Consent enforcement: AI skipped without ai_processing_consent
- AI kill switch: classification skipped when disabled
- AI failure: check-in still succeeds if Claude API fails
- Validation: mood_score bounds (1-10)
- Validation: invalid manual tags rejected
- Auth: missing/invalid token rejected
- Empty journal text: treated as no journal

Run: pytest tests/test_mood_checkin.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.mood import MoodClassification

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A reusable fake user record with all consents granted
_USER_ALL_CONSENT = {
    "id": str(uuid.uuid4()),
    "email": "test@lse.ac.uk",
    "mood_data_consent": True,
    "mood_data_consent_at": "2026-02-01T00:00:00Z",
    "ai_processing_consent": True,
    "ai_processing_consent_at": "2026-02-01T00:00:00Z",
    "wearable_data_consent": True,
    "onboarding_completed": True,
}

_USER_NO_AI_CONSENT = {
    **_USER_ALL_CONSENT,
    "id": str(uuid.uuid4()),
    "ai_processing_consent": False,
    "ai_processing_consent_at": None,
}

_USER_NO_MOOD_CONSENT = {
    **_USER_ALL_CONSENT,
    "id": str(uuid.uuid4()),
    "mood_data_consent": False,
    "mood_data_consent_at": None,
}

_CHECKIN_ROW = {
    "id": str(uuid.uuid4()),
    "created_at": datetime.now(timezone.utc).isoformat(),
    "mood_score": 5,
    "journal_text": None,
    "manual_tags": None,
    "ai_processed": False,
}

_MOCK_CLASSIFICATION = MoodClassification(
    mood_label="anxious",
    intensity=7,
    themes=["work stress", "sleep"],
    confidence=0.92,
)

AUTH_HEADER = {"Authorization": "Bearer fake-valid-token"}


# ---------------------------------------------------------------------------
# Helpers to mock the dependency chain
# ---------------------------------------------------------------------------

def _mock_supabase(user_data: Optional[dict] = None, checkin_row: Optional[dict] = None):
    """Create a mock Supabase client with chained method calls."""
    mock_db = MagicMock()

    # Auth: get_user returns a user object
    if user_data:
        mock_user = MagicMock()
        mock_user.user = MagicMock()
        mock_user.user.id = user_data["id"]
        mock_db.auth.get_user.return_value = mock_user

        # users.select().eq().maybe_single().execute()
        user_select = MagicMock()
        user_select.data = user_data
        mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = user_select
    else:
        mock_db.auth.get_user.side_effect = Exception("Invalid token")

    # mood_checkins.insert().execute()
    row = checkin_row or _CHECKIN_ROW
    insert_result = MagicMock()
    insert_result.data = [row]
    mock_db.table.return_value.insert.return_value.execute.return_value = insert_result

    # mood_checkins.update().eq().execute()
    update_result = MagicMock()
    update_result.data = [row]
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = update_result

    return mock_db


def _make_client(
    mock_db: MagicMock,
    mock_classifier: Optional[AsyncMock] = None,
    ai_enabled: bool = True,
) -> TestClient:
    """Build a TestClient with mocked dependencies."""
    with (
        patch("app.routers.mood.get_supabase_client", return_value=mock_db),
        patch("app.routers.mood.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.enable_ai_classification = ai_enabled
        mock_settings.return_value = settings

        if mock_classifier:
            with patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier):
                from app.main import app
                return TestClient(app)
        else:
            from app.main import app
            return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_score_only_checkin(self):
        """Simplest check-in: just a mood score, no journal, no tags."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 7},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["mood_score"] == 7
        assert data["ai_processed"] is False
        assert data["journal_text_stored"] is False
        assert data["classification"] is None

    def test_score_with_journal_and_ai(self):
        """Check-in with journal text — should trigger AI classification."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=_MOCK_CLASSIFICATION)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 4,
                    "journal_text": "Feeling really anxious about the deadline",
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["ai_processed"] is True
        assert data["journal_text_stored"] is True
        assert data["classification"]["mood_label"] == "anxious"
        assert data["classification"]["intensity"] == 7
        assert data["classification"]["confidence"] == 0.92
        assert "work stress" in data["classification"]["themes"]

        # Verify the classifier received the raw text (it handles anonymisation internally)
        mock_classifier.classify.assert_awaited_once_with(
            "Feeling really anxious about the deadline"
        )

    def test_score_with_manual_tags(self):
        """Check-in with manual tags — no AI needed."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 3,
                    "manual_tags": ["anxious", "stressed", "low_energy"],
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["manual_tags"] == ["anxious", "stressed", "low_energy"]
        assert data["ai_processed"] is False


class TestConsentEnforcement:

    def test_rejects_without_mood_consent(self):
        """Users MUST grant mood_data_consent before any check-in."""
        mock_db = _mock_supabase(user_data=_USER_NO_MOOD_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 5},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"]["message"].lower()

    def test_skips_ai_without_ai_consent(self):
        """Journal text is stored but NOT classified if ai_processing_consent is False."""
        mock_db = _mock_supabase(user_data=_USER_NO_AI_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=_MOCK_CLASSIFICATION)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 4,
                    "journal_text": "Stressed about exams",
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        # Journal stored but NOT sent to Claude
        assert data["journal_text_stored"] is True
        assert data["ai_processed"] is False
        assert data["classification"] is None
        # Classifier should never have been called
        mock_classifier.classify.assert_not_awaited()


class TestAIKillSwitch:

    def test_skips_ai_when_disabled(self):
        """Global kill switch disables AI classification for all users."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=_MOCK_CLASSIFICATION)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=False)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 6,
                    "journal_text": "Good day but tired",
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        assert resp.json()["ai_processed"] is False
        mock_classifier.classify.assert_not_awaited()


class TestAIFailureResilience:

    def test_checkin_succeeds_when_claude_fails(self):
        """If Claude API is down, the check-in must still be saved."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(side_effect=Exception("API timeout"))

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 3,
                    "journal_text": "Terrible day, everything went wrong",
                },
                headers=AUTH_HEADER,
            )

        # Check-in saved successfully despite classification failure
        assert resp.status_code == 201
        data = resp.json()
        assert data["journal_text_stored"] is True
        assert data["ai_processed"] is False
        assert data["classification"] is None

    def test_checkin_succeeds_when_classifier_returns_none(self):
        """Classifier may return None for unparseable text — check-in still works."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=None)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 5, "journal_text": "..."},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        assert resp.json()["ai_processed"] is False


class TestValidation:

    def test_mood_score_too_low(self):
        """Mood score below 1 is rejected."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 0},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422

    def test_mood_score_too_high(self):
        """Mood score above 10 is rejected."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 11},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422

    def test_invalid_manual_tags_rejected(self):
        """Tags not in the allowed set are rejected with a helpful error."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 5,
                    "manual_tags": ["anxious", "totally_vibing"],
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "totally_vibing" in detail["message"]
        assert "valid_tags" in detail  # includes the allowed set

    def test_journal_text_length_enforced(self):
        """Journal text over 1000 chars is rejected."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 5,
                    "journal_text": "a" * 1001,
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422


class TestAuth:

    def test_missing_auth_header(self):
        """Request without Authorization header is rejected."""
        from app.main import app
        client = TestClient(app)

        resp = client.post(
            "/api/v1/mood/checkin",
            json={"mood_score": 5},
            # no Authorization header
        )

        assert resp.status_code in (401, 422)  # 422 if FastAPI rejects missing header

    def test_invalid_token(self):
        """Request with an invalid JWT is rejected."""
        mock_db = _mock_supabase(user_data=None)  # triggers auth failure

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 5},
                headers={"Authorization": "Bearer totally-invalid-token"},
            )

        assert resp.status_code == 401


class TestEdgeCases:

    def test_empty_journal_text_treated_as_no_journal(self):
        """Whitespace-only journal text should not trigger AI classification."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=_MOCK_CLASSIFICATION)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={"mood_score": 6, "journal_text": "   "},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        # Whitespace-only counts as "no journal"
        assert resp.json()["ai_processed"] is False
        mock_classifier.classify.assert_not_awaited()

    def test_journal_with_tags_both_stored(self):
        """User can provide BOTH journal text and manual tags."""
        mock_db = _mock_supabase(user_data=_USER_ALL_CONSENT)
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(return_value=_MOCK_CLASSIFICATION)

        with (
            patch("app.routers.mood.get_supabase_client", return_value=mock_db),
            patch("app.routers.mood.get_settings") as mock_settings,
            patch("app.routers.mood.get_mood_classifier", return_value=mock_classifier),
        ):
            mock_settings.return_value = MagicMock(enable_ai_classification=True)
            from app.main import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/mood/checkin",
                json={
                    "mood_score": 4,
                    "journal_text": "Stressed about work",
                    "manual_tags": ["stressed"],
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["ai_processed"] is True
        assert data["manual_tags"] == ["stressed"]
        assert data["classification"] is not None
