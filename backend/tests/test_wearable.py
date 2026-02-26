"""
Tests for POST /api/v1/wearable/sync
======================================
Covers:
- Happy path: minimal sync (date + source only, all metrics None)
- Happy path: full sync with all metrics populated
- Happy path: response shape matches WearableDailyResponse
- Consent: rejects if wearable_data_consent is False (403)
- Auth: missing authorization header
- Auth: invalid token
- Upsert behaviour: .upsert() is called (not .insert())

Run: pytest tests/test_wearable.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())

_USER_WITH_CONSENT = {
    "id": _USER_ID,
    "email": "test@lse.ac.uk",
    "mood_data_consent": True,
    "mood_data_consent_at": "2026-02-01T00:00:00Z",
    "ai_processing_consent": True,
    "ai_processing_consent_at": "2026-02-01T00:00:00Z",
    "wearable_data_consent": True,
    "onboarding_completed": True,
}

_USER_NO_WEARABLE_CONSENT = {
    **_USER_WITH_CONSENT,
    "id": str(uuid.uuid4()),
    "wearable_data_consent": False,
}

_UPSERT_ROW = {
    "id": str(uuid.uuid4()),
    "created_at": datetime.now(timezone.utc).isoformat(),
    "user_id": _USER_ID,
    "date": "2026-02-26",
    "source": "apple_health",
    "hrv_avg": None,
    "hrv_min": None,
    "hrv_max": None,
    "resting_hr": None,
    "sleep_duration_minutes": None,
    "sleep_deep_minutes": None,
    "sleep_rem_minutes": None,
    "sleep_score": None,
    "readiness_score": None,
    "steps": None,
    "active_calories": None,
}

AUTH_HEADER = {"Authorization": "Bearer fake-valid-token"}

_MINIMAL_BODY = {
    "date": "2026-02-26",
    "source": "apple_health",
}


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------

def _mock_wearable_db(
    user_data: Optional[dict] = None,
    upsert_row: Optional[dict] = None,
) -> MagicMock:
    """Build a mock Supabase client for wearable endpoint tests."""
    mock_db = MagicMock()

    if user_data:
        mock_user = MagicMock()
        mock_user.user = MagicMock()
        mock_user.user.id = user_data["id"]
        mock_db.auth.get_user.return_value = mock_user

        user_select = MagicMock()
        user_select.data = user_data
        mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = user_select
    else:
        mock_db.auth.get_user.side_effect = Exception("Invalid token")

    row = upsert_row or _UPSERT_ROW
    upsert_result = MagicMock()
    upsert_result.data = [row]
    mock_db.table.return_value.upsert.return_value.execute.return_value = upsert_result

    return mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_minimal_sync(self):
        """date + source only, all metrics None — should succeed with 200."""
        mock_db = _mock_wearable_db(user_data=_USER_WITH_CONSENT)
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/wearable/sync", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "apple_health"
        assert data["hrv_avg"] is None
        assert data["steps"] is None

    def test_full_sync(self):
        """All metrics populated — all should round-trip correctly."""
        full_row = {
            **_UPSERT_ROW,
            "hrv_avg": 55.3,
            "hrv_min": 42.1,
            "hrv_max": 68.9,
            "resting_hr": 58.0,
            "sleep_duration_minutes": 450,
            "sleep_deep_minutes": 90,
            "sleep_rem_minutes": 120,
            "sleep_score": 82.0,
            "readiness_score": 78.0,
            "steps": 8500,
            "active_calories": 420.0,
        }
        mock_db = _mock_wearable_db(user_data=_USER_WITH_CONSENT, upsert_row=full_row)
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/wearable/sync",
                json={
                    **_MINIMAL_BODY,
                    "hrv_avg": 55.3,
                    "hrv_min": 42.1,
                    "hrv_max": 68.9,
                    "resting_hr": 58.0,
                    "sleep_duration_minutes": 450,
                    "sleep_deep_minutes": 90,
                    "sleep_rem_minutes": 120,
                    "sleep_score": 82.0,
                    "readiness_score": 78.0,
                    "steps": 8500,
                    "active_calories": 420.0,
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["hrv_avg"] == 55.3
        assert data["sleep_duration_minutes"] == 450
        assert data["steps"] == 8500

    def test_response_shape(self):
        """Response must include all WearableDailyResponse fields."""
        mock_db = _mock_wearable_db(user_data=_USER_WITH_CONSENT)
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/wearable/sync", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        # All required response fields must be present
        for field in ("id", "created_at", "user_id", "date", "source"):
            assert field in data, f"Missing field: {field}"
        # All optional metric fields must be present (even if None)
        for field in (
            "hrv_avg", "hrv_min", "hrv_max", "resting_hr",
            "sleep_duration_minutes", "sleep_deep_minutes", "sleep_rem_minutes",
            "sleep_score", "readiness_score", "steps", "active_calories",
        ):
            assert field in data, f"Missing optional field: {field}"


class TestConsentEnforcement:

    def test_rejects_without_wearable_data_consent(self):
        """Users without wearable_data_consent get 403 with consent_required code."""
        mock_db = _mock_wearable_db(user_data=_USER_NO_WEARABLE_CONSENT)
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/wearable/sync", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "consent" in detail["message"].lower()
        assert detail["code"] == "consent_required"


class TestAuth:

    def test_missing_auth_header(self):
        """Request without Authorization header is rejected."""
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/v1/wearable/sync", json=_MINIMAL_BODY)

        assert resp.status_code in (401, 422)

    def test_invalid_token(self):
        """Request with an invalid JWT is rejected with 401."""
        mock_db = _mock_wearable_db(user_data=None)  # triggers auth failure
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/wearable/sync",
                json=_MINIMAL_BODY,
                headers={"Authorization": "Bearer totally-invalid-token"},
            )

        assert resp.status_code == 401


class TestUpsertBehaviour:

    def test_upsert_called_not_insert(self):
        """The endpoint must call .upsert() not .insert() — idempotent re-syncs."""
        mock_db = _mock_wearable_db(user_data=_USER_WITH_CONSENT)
        with patch("app.routers.wearable.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/wearable/sync", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 200
        # upsert must have been called
        mock_db.table.return_value.upsert.assert_called_once()
        # insert must NOT have been called
        mock_db.table.return_value.insert.assert_not_called()
