"""
Tests for GET /api/v1/insights/weekly
=======================================
Covers:
- Happy path: returns all three sections with real data
- Happy path: mood_trend is sorted ascending by date
- Happy path: multiple check-ins on the same day are averaged
- Happy path: top_correlations up to 5, ordered by mood_change_pct desc
- Happy path: exercise_summary counts per type
- Edge case: new user — all sections empty, still 200
- Edge case: only correlations, no check-ins this week → mood_trend empty
- Edge case: no correlations yet → top_correlations empty list
- Auth: missing authorization header → 401/422
- Auth: invalid token → 401
- Response shape: week_start, week_end, all section keys present

Run: pytest tests/test_insights.py -v
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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

AUTH_HEADER = {"Authorization": "Bearer fake-valid-token"}

# Dates within the last 7 days (relative to a stable past date to avoid
# test brittleness — we'll build them dynamically in tests)
def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT12:00:00+00:00")

def _date_days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_insights_db(
    checkin_rows: list[dict] | None = None,
    corr_rows: list[dict] | None = None,
    exercise_rows: list[dict] | None = None,
    user_data: dict | None = None,
) -> MagicMock:
    """Build a mock Supabase client for insights tests.

    The DB mock routes calls via the table name captured in table() calls.
    We build a smart side_effect on .table() to return different mock chains
    depending on the table name.
    """
    mock_db = MagicMock()

    ud = user_data if user_data is not None else _USER_DATA

    if ud:
        mock_user = MagicMock()
        mock_user.user = MagicMock()
        mock_user.user.id = ud["id"]
        mock_db.auth.get_user.return_value = mock_user
    else:
        mock_db.auth.get_user.side_effect = Exception("Invalid token")

    checkins = checkin_rows if checkin_rows is not None else []
    corrs = corr_rows if corr_rows is not None else []
    exercises = exercise_rows if exercise_rows is not None else []

    def _table_side_effect(table_name: str):
        mock_table = MagicMock()

        if table_name == "users":
            # Auth helper: select().eq().maybe_single().execute()
            user_result = MagicMock()
            user_result.data = ud
            mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = user_result

        elif table_name == "mood_checkins":
            result = MagicMock()
            result.data = checkins
            # select().eq().gte().order().execute()
            mock_table.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = result

        elif table_name == "user_correlations":
            result = MagicMock()
            result.data = corrs
            # select().eq().order().limit().execute()
            mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = result

        elif table_name == "exercise_sessions":
            result = MagicMock()
            result.data = exercises
            # select().eq().gte().execute()
            mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = result

        return mock_table

    mock_db.table.side_effect = _table_side_effect
    return mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_returns_all_three_sections(self):
        """Response must contain mood_trend, top_correlations, exercise_summary."""
        checkins = [{"created_at": _days_ago(1), "mood_score": 7}]
        corrs = [
            {
                "exercise_type": "running",
                "mood_change_pct": 18.5,
                "p_value": 0.03,
                "sample_size": 16,
                "insight_text": "Running is linked to 18% higher mood (n=16, p=0.03)",
            }
        ]
        exercises = [{"exercise_type": "running"}, {"exercise_type": "yoga"}]

        mock_db = _mock_insights_db(checkins, corrs, exercises)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert "mood_trend" in data
        assert "top_correlations" in data
        assert "exercise_summary" in data

    def test_mood_trend_sorted_ascending(self):
        """mood_trend entries must be in ascending date order."""
        checkins = [
            {"created_at": _days_ago(3), "mood_score": 5},
            {"created_at": _days_ago(1), "mood_score": 8},
            {"created_at": _days_ago(2), "mood_score": 6},
        ]
        mock_db = _mock_insights_db(checkins)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        trend = resp.json()["mood_trend"]
        assert len(trend) == 3
        dates = [t["date"] for t in trend]
        assert dates == sorted(dates), "mood_trend not sorted ascending"

    def test_multiple_checkins_same_day_averaged(self):
        """Two check-ins on the same day must be averaged into one trend point."""
        today_str = _days_ago(0)
        checkins = [
            {"created_at": today_str, "mood_score": 4},
            {"created_at": today_str, "mood_score": 8},
        ]
        mock_db = _mock_insights_db(checkins)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        trend = resp.json()["mood_trend"]
        assert len(trend) == 1
        assert trend[0]["mood_score"] == pytest.approx(6.0)

    def test_top_correlations_limit_and_order(self):
        """top_correlations must have at most 5 entries (DB side-effect handles order)."""
        corrs = [
            {"exercise_type": "running", "mood_change_pct": 20.0, "p_value": 0.02, "sample_size": 18, "insight_text": "Running..."},
            {"exercise_type": "yoga", "mood_change_pct": 15.0, "p_value": 0.04, "sample_size": 14, "insight_text": "Yoga..."},
            {"exercise_type": "cycling", "mood_change_pct": 10.0, "p_value": 0.04, "sample_size": 12, "insight_text": "Cycling..."},
        ]
        mock_db = _mock_insights_db(corr_rows=corrs)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        top = resp.json()["top_correlations"]
        assert len(top) == 3
        assert top[0]["exercise_type"] == "running"
        assert top[0]["mood_change_pct"] == pytest.approx(20.0)

    def test_exercise_summary_counts_per_type(self):
        """exercise_summary must count sessions per type correctly."""
        exercises = [
            {"exercise_type": "running"},
            {"exercise_type": "running"},
            {"exercise_type": "yoga"},
        ]
        mock_db = _mock_insights_db(exercise_rows=exercises)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        summary = resp.json()["exercise_summary"]
        assert summary["running"] == 2
        assert summary["yoga"] == 1


class TestEdgeCases:

    def test_new_user_all_sections_empty(self):
        """New user with no data should get 200 with all sections empty/empty."""
        mock_db = _mock_insights_db([], [], [])

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["mood_trend"] == []
        assert data["top_correlations"] == []
        assert data["exercise_summary"] == {}

    def test_no_checkins_this_week_mood_trend_empty(self):
        """If there are no check-ins this week, mood_trend must be empty."""
        mock_db = _mock_insights_db(checkin_rows=[], corr_rows=[], exercise_rows=[])

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        assert resp.json()["mood_trend"] == []

    def test_no_correlations_returns_empty_list(self):
        """No correlations computed yet → top_correlations is empty list, not null."""
        mock_db = _mock_insights_db(corr_rows=[])

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        assert resp.json()["top_correlations"] == []


class TestResponseShape:

    def test_week_start_and_week_end_present(self):
        """Response must include week_start and week_end date strings."""
        mock_db = _mock_insights_db()

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        data = resp.json()
        assert "week_start" in data
        assert "week_end" in data
        # week_start should be 6 days before week_end
        ws = date.fromisoformat(data["week_start"])
        we = date.fromisoformat(data["week_end"])
        assert (we - ws).days == 6

    def test_correlation_summary_fields_present(self):
        """Each correlation entry must include all CorrelationSummary fields."""
        corrs = [
            {
                "exercise_type": "running",
                "mood_change_pct": 18.5,
                "p_value": 0.03,
                "sample_size": 16,
                "insight_text": "Running is linked to 18% higher mood",
            }
        ]
        mock_db = _mock_insights_db(corr_rows=corrs)

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get("/api/v1/insights/weekly", headers=AUTH_HEADER)

        top = resp.json()["top_correlations"]
        assert len(top) == 1
        for field in ("exercise_type", "mood_change_pct", "p_value", "sample_size", "insight_text"):
            assert field in top[0], f"Missing field: {field}"


class TestAuth:

    def test_missing_auth_header(self):
        """Request without Authorization header is rejected."""
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/v1/insights/weekly")
        assert resp.status_code in (401, 422)

    def test_invalid_token(self):
        """Request with an invalid JWT is rejected with 401."""
        mock_db = _mock_insights_db(user_data=None)
        # Override auth to fail
        mock_db.auth.get_user.side_effect = Exception("Invalid token")

        with patch("app.routers.insights.get_supabase_client", return_value=mock_db):
            from app.main import app
            client = TestClient(app)
            resp = client.get(
                "/api/v1/insights/weekly",
                headers={"Authorization": "Bearer totally-invalid-token"},
            )

        assert resp.status_code == 401
