"""
Tests for GET /api/v1/prescriptions/today
==========================================
Covers:
- Happy path: returns prescription when check-in data exists
- Happy path: correlation-based prescription (source='correlation')
- Happy path: rule-based prescription (source='rule_based')
- Happy path: response always includes disclaimer
- No data: has_data=False, prescription=null when no check-in exists
- Auth: missing authorization header → 401/422
- Auth: invalid token → 401
- Response shape: all MoodPrescription fields present

Run: pytest tests/test_prescriptions.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.prescription import MoodPrescription

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())

_USER_DATA = {
    "id": _USER_ID,
    "email": "test@lse.ac.uk",
    "mood_data_consent": True,
    "ai_processing_consent": True,
    "wearable_data_consent": True,
    "onboarding_completed": True,
}

_PRESCRIPTION_ROW = {
    "id": str(uuid.uuid4()),
    "created_at": datetime.now(timezone.utc).isoformat(),
    "user_id": _USER_ID,
    "exercise_type": "walking",
    "suggested_duration_minutes": 25,
    "suggested_intensity": "moderate",
    "reasoning": "A brisk walk supports a calmer mood.",
    "confidence": 0.60,
    "source": "rule_based",
}

_CORRELATION_PRESCRIPTION_ROW = {
    **_PRESCRIPTION_ROW,
    "id": str(uuid.uuid4()),
    "exercise_type": "running",
    "suggested_duration_minutes": 30,
    "suggested_intensity": "vigorous",
    "reasoning": "Based on your personal data, Running is linked to 18% higher mood (p=0.03, n=16). A 30-minute vigorous session is suggested.",
    "confidence": 0.77,
    "source": "correlation",
}

AUTH_HEADER = {"Authorization": "Bearer fake-valid-token"}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_auth_db(user_data: dict | None = None) -> MagicMock:
    """Mock just the auth + users table calls for the router helper."""
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

    return mock_db


def _mock_prescription(row: dict | None) -> AsyncMock:
    """Return a mock PrescriptionService.generate_for_user."""
    mock_service = MagicMock()
    if row is not None:
        mock_service.generate_for_user = AsyncMock(return_value=MoodPrescription(**row))
    else:
        mock_service.generate_for_user = AsyncMock(return_value=None)
    return mock_service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_returns_prescription_with_check_in_data(self):
        """Standard rule-based prescription returned for a user with check-in data."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(_PRESCRIPTION_ROW)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_data"] is True
        assert data["prescription"] is not None
        assert data["prescription"]["exercise_type"] == "walking"

    def test_correlation_based_prescription(self):
        """When service returns a correlation-based prescription, source is 'correlation'."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(_CORRELATION_PRESCRIPTION_ROW)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["prescription"]["source"] == "correlation"
        assert data["prescription"]["exercise_type"] == "running"
        assert data["prescription"]["confidence"] == pytest.approx(0.77)

    def test_rule_based_prescription(self):
        """When service returns a rule-based prescription, source is 'rule_based'."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(_PRESCRIPTION_ROW)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        assert resp.status_code == 200
        assert resp.json()["prescription"]["source"] == "rule_based"

    def test_response_always_includes_disclaimer(self):
        """Regulatory disclaimer must always be present in the response."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(_PRESCRIPTION_ROW)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        data = resp.json()
        assert "disclaimer" in data
        assert len(data["disclaimer"]) > 0
        # Must not contain clinical language
        disclaimer_lower = data["disclaimer"].lower()
        for banned in ("diagnose", "treat", "cure", "therapy", "clinical"):
            assert banned not in disclaimer_lower, f"Banned term '{banned}' in disclaimer"


class TestNoData:

    def test_no_checkin_data_returns_null_prescription(self):
        """When user has no check-in data, prescription is null and has_data is False."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(None)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_data"] is False
        assert data["prescription"] is None

    def test_no_data_still_includes_disclaimer(self):
        """Disclaimer must be present even when there is no prescription."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(None)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        assert "disclaimer" in resp.json()


class TestResponseShape:

    def test_all_prescription_fields_present(self):
        """MoodPrescription must include all required fields."""
        mock_db = _mock_auth_db(_USER_DATA)
        mock_service = _mock_prescription(_PRESCRIPTION_ROW)

        with (
            patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db),
            patch("app.routers.prescriptions.get_prescription_service", return_value=mock_service),
        ):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/prescriptions/today", headers=AUTH_HEADER)

        p = resp.json()["prescription"]
        for field in (
            "id", "created_at", "exercise_type", "suggested_duration_minutes",
            "suggested_intensity", "reasoning", "confidence", "source",
        ):
            assert field in p, f"Missing field: {field}"


class TestAuth:

    def test_missing_auth_header(self):
        """Request without Authorization header is rejected."""
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/v1/prescriptions/today")
        assert resp.status_code in (401, 422)

    def test_invalid_token(self):
        """Request with an invalid JWT is rejected with 401."""
        mock_db = _mock_auth_db(None)

        with patch("app.routers.prescriptions.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get(
                "/api/v1/prescriptions/today",
                headers={"Authorization": "Bearer totally-invalid-token"},
            )

        assert resp.status_code == 401
