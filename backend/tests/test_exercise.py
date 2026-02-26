"""
Tests for POST /api/v1/exercise
================================
Covers:
- Happy path: minimal required fields
- Happy path: all optional fields provided
- Happy path: source defaults to "manual"
- Happy path: response contains id and created_at
- Validation: invalid exercise_type rejected (422 + code + valid_types list)
- Validation: each valid exercise type accepted (parametrised)
- Validation: invalid intensity rejected (Pydantic Literal mismatch)
- Validation: duration below minimum rejected (ge=1)
- Validation: missing required fields rejected
- Auth: missing authorization header
- Auth: invalid token
- DB write: insert called with user_id

Run: pytest tests/test_exercise.py -v
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.exercise import VALID_EXERCISE_TYPES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())

_USER_DATA = {
    "id": _USER_ID,
    "email": "test@lse.ac.uk",
    "mood_data_consent": True,
    "mood_data_consent_at": "2026-02-01T00:00:00Z",
    "ai_processing_consent": True,
    "ai_processing_consent_at": "2026-02-01T00:00:00Z",
    "wearable_data_consent": True,
    "onboarding_completed": True,
}

_SESSION_ROW = {
    "id": str(uuid.uuid4()),
    "created_at": datetime.now(timezone.utc).isoformat(),
    "user_id": _USER_ID,
    "date": "2026-02-26",
    "exercise_type": "running",
    "duration_minutes": 30,
    "intensity": "moderate",
    "avg_heart_rate": None,
    "calories": None,
    "source": "manual",
    "notes": None,
}

AUTH_HEADER = {"Authorization": "Bearer fake-valid-token"}

_MINIMAL_BODY = {
    "date": "2026-02-26",
    "exercise_type": "running",
    "duration_minutes": 30,
    "intensity": "moderate",
}


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------

def _mock_exercise_db(
    user_data: Optional[dict] = None,
    insert_row: Optional[dict] = None,
) -> MagicMock:
    """Build a mock Supabase client for exercise endpoint tests."""
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

    row = insert_row or _SESSION_ROW
    insert_result = MagicMock()
    insert_result.data = [row]
    mock_db.table.return_value.insert.return_value.execute.return_value = insert_result

    return mock_db


def _make_client(mock_db: MagicMock) -> TestClient:
    with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
        from app.main import app
        return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_minimal_required_fields(self):
        """date, exercise_type, duration_minutes, intensity only — should succeed."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/exercise", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 201
        data = resp.json()
        assert data["exercise_type"] == "running"
        assert data["duration_minutes"] == 30
        assert data["intensity"] == "moderate"

    def test_all_optional_fields(self):
        """Including avg_heart_rate, calories, notes — all stored correctly."""
        full_row = {
            **_SESSION_ROW,
            "avg_heart_rate": 145.5,
            "calories": 320.0,
            "notes": "Felt strong today",
            "source": "apple_health",
        }
        mock_db = _mock_exercise_db(user_data=_USER_DATA, insert_row=full_row)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={
                    **_MINIMAL_BODY,
                    "avg_heart_rate": 145.5,
                    "calories": 320.0,
                    "notes": "Felt strong today",
                    "source": "apple_health",
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["avg_heart_rate"] == 145.5
        assert data["calories"] == 320.0
        assert data["notes"] == "Felt strong today"
        assert data["source"] == "apple_health"

    def test_source_defaults_to_manual(self):
        """When source is not provided, it should default to 'manual'."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/exercise", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 201
        # The mock row has source="manual" and the default in the model is "manual"
        assert resp.json()["source"] == "manual"

    def test_response_contains_id_and_created_at(self):
        """Response must always include id and created_at from the DB row."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/exercise", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "created_at" in data
        assert data["user_id"] == _USER_ID


class TestValidation:

    def test_invalid_exercise_type_rejected(self):
        """Unknown exercise_type → 422 with code and valid_types list."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={**_MINIMAL_BODY, "exercise_type": "zumba"},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_exercise_type"
        assert "zumba" in detail["message"]
        assert "valid_types" in detail
        assert "running" in detail["valid_types"]

    @pytest.mark.parametrize("exercise_type", sorted(VALID_EXERCISE_TYPES))
    def test_each_valid_exercise_type_accepted(self, exercise_type: str):
        """Every type in VALID_EXERCISE_TYPES must be accepted."""
        row = {**_SESSION_ROW, "exercise_type": exercise_type}
        mock_db = _mock_exercise_db(user_data=_USER_DATA, insert_row=row)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={**_MINIMAL_BODY, "exercise_type": exercise_type},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 201, f"Expected 201 for exercise_type='{exercise_type}', got {resp.status_code}"

    def test_invalid_intensity_rejected(self):
        """Intensity not in Literal['low','moderate','vigorous'] → 422 from Pydantic."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={**_MINIMAL_BODY, "intensity": "extreme"},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422

    def test_duration_below_minimum_rejected(self):
        """duration_minutes=0 violates ge=1 → 422."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={**_MINIMAL_BODY, "duration_minutes": 0},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422

    def test_missing_required_fields(self):
        """Missing 'date' field → 422 from Pydantic."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json={
                    "exercise_type": "running",
                    "duration_minutes": 30,
                    "intensity": "moderate",
                    # missing date
                },
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 422


class TestAuth:

    def test_missing_auth_header(self):
        """Request without Authorization header is rejected."""
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/v1/exercise", json=_MINIMAL_BODY)

        assert resp.status_code in (401, 422)

    def test_invalid_token(self):
        """Request with an invalid JWT is rejected with 401."""
        mock_db = _mock_exercise_db(user_data=None)  # triggers auth failure
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post(
                "/api/v1/exercise",
                json=_MINIMAL_BODY,
                headers={"Authorization": "Bearer totally-invalid-token"},
            )

        assert resp.status_code == 401


class TestDBWrite:

    def test_insert_called_with_user_id(self):
        """The DB insert must include user_id from the authenticated user."""
        mock_db = _mock_exercise_db(user_data=_USER_DATA)
        with patch("app.routers.exercise.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.post("/api/v1/exercise", json=_MINIMAL_BODY, headers=AUTH_HEADER)

        assert resp.status_code == 201
        # Verify insert was called on the exercise_sessions table
        insert_call_args = mock_db.table.return_value.insert.call_args
        assert insert_call_args is not None
        inserted_row = insert_call_args[0][0]
        assert inserted_row["user_id"] == _USER_ID
