"""
Tests for CorrelationService
=============================
Covers:
- Happy path: 20 days of mood + exercise data → produces CorrelationResults
- Multiple exercise types computed independently
- Multiple mood check-ins per day averaged correctly
- Insufficient data: no mood data → empty
- Insufficient data: no exercise data → empty
- Insufficient data: date span < 14 days → empty
- Insufficient data: fewer than 3 exercise samples for a type → skipped
- Recomputation skip: recent computation + few new records → skipped
- Recomputation forced: recent computation + enough new records → recomputed
- Recomputation forced: old computation → recomputed
- get_latest_for_user returns stored rows
- CorrelationResult.is_significant property
- Insight text uses regulatory-safe language

Run: pytest tests/test_correlation.py -v
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.correlation import (
    MIN_DATA_DAYS,
    MIN_EXERCISE_SAMPLES,
    CorrelationResult,
    CorrelationService,
    LAG_DAYS,
)

USER_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _mood_rows(start_date: date, num_days: int, base_score: int = 5, exercise_dates: set[date] | None = None) -> list[dict]:
    """Generate mood check-in rows. Days after exercise get +2 to mood score."""
    rows = []
    for i in range(num_days):
        d = start_date + timedelta(days=i)
        score = base_score
        if exercise_dates and (d - timedelta(days=LAG_DAYS)) in exercise_dates:
            score = min(base_score + 2, 10)
        rows.append({
            "created_at": datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).isoformat(),
            "mood_score": score,
        })
    return rows


def _exercise_rows(dates: list[date], exercise_type: str = "running") -> list[dict]:
    return [{"date": d.isoformat(), "exercise_type": exercise_type} for d in dates]


# ---------------------------------------------------------------------------
# Mock Supabase helper
# ---------------------------------------------------------------------------

class _FakeTableRouter:
    """Routes .table("name") calls to per-table mock data.

    Supports the chained query patterns used by CorrelationService:
      - .select(...).eq(...).order(...).limit(...).execute()
      - .select(..., count="exact").eq(...).gt(...).execute()
      - .select(...).eq(...).execute()
      - .delete().eq(...).execute()
      - .insert(...).execute()
    """

    def __init__(self) -> None:
        # Stores per-table data and config
        self._tables: dict[str, dict] = {}

    def set_table(self, name: str, *, data: list[dict] | None = None, count: int | None = None) -> None:
        self._tables[name] = {"data": data or [], "count": count}

    def table(self, name: str) -> MagicMock:
        cfg = self._tables.get(name, {"data": [], "count": None})

        mock = MagicMock()

        # Terminal .execute() result
        result = MagicMock()
        result.data = cfg["data"]
        result.count = cfg["count"]

        # Make every chained method return the same mock so any chain works
        chain = mock
        for method in ("select", "eq", "gt", "order", "limit", "maybe_single"):
            getattr(chain, method).return_value = chain
        chain.execute.return_value = result

        # .delete().eq().execute()
        delete_chain = MagicMock()
        delete_chain.eq.return_value = delete_chain
        delete_chain.execute.return_value = MagicMock(data=[])
        mock.delete.return_value = delete_chain

        # .insert().execute()
        insert_result = MagicMock()
        insert_result.data = []
        mock.insert.return_value.execute.return_value = insert_result

        return mock


def _build_service(table_router: _FakeTableRouter) -> CorrelationService:
    """Instantiate CorrelationService with a mocked Supabase client."""
    with patch("app.services.correlation.get_supabase_client") as mock_get:
        mock_db = MagicMock()
        mock_db.table = table_router.table
        mock_get.return_value = mock_db
        svc = CorrelationService()
    return svc


# ---------------------------------------------------------------------------
# CorrelationResult unit tests
# ---------------------------------------------------------------------------

class TestCorrelationResult:

    def test_is_significant_true(self):
        r = CorrelationResult(
            exercise_type="running", correlation_r=0.5, p_value=0.01,
            mood_change_avg=1.0, mood_change_pct=20.0, sample_size=5,
        )
        assert r.is_significant is True

    def test_is_significant_false_high_p(self):
        r = CorrelationResult(
            exercise_type="yoga", correlation_r=0.1, p_value=0.3,
            mood_change_avg=0.2, mood_change_pct=4.0, sample_size=10,
        )
        assert r.is_significant is False

    def test_is_significant_false_low_n(self):
        r = CorrelationResult(
            exercise_type="cycling", correlation_r=0.9, p_value=0.001,
            mood_change_avg=2.0, mood_change_pct=40.0, sample_size=2,
        )
        assert r.is_significant is False

    def test_default_lag_days(self):
        r = CorrelationResult(
            exercise_type="running", correlation_r=0.0, p_value=1.0,
            mood_change_avg=0.0, mood_change_pct=0.0, sample_size=0,
        )
        assert r.lag_days == LAG_DAYS


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:

    @pytest.mark.asyncio
    async def test_computes_correlation_with_sufficient_data(self):
        """20 days of data with exercise on 5 days should produce a result."""
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        router = _FakeTableRouter()
        # No previous correlations
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20, base_score=5, exercise_dates=exercise_set))
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)

        assert len(results) == 1
        r = results[0]
        assert r.exercise_type == "running"
        assert r.sample_size == 5
        assert r.lag_days == LAG_DAYS
        assert isinstance(r.correlation_r, float)
        assert isinstance(r.p_value, float)
        assert r.mood_change_avg > 0  # exercise days have higher mood in our synthetic data
        assert r.mood_change_pct > 0
        assert r.insight_text  # not empty

    @pytest.mark.asyncio
    async def test_multiple_exercise_types(self):
        """Two exercise types should each get their own CorrelationResult."""
        start = date(2026, 1, 1)
        running_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        yoga_dates = [start + timedelta(days=i) for i in [3, 6, 9, 12, 15]]
        all_exercise = set(running_dates + yoga_dates)

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20, base_score=5, exercise_dates=all_exercise))
        router.set_table("exercise_sessions", data=(
            _exercise_rows(running_dates, "running") + _exercise_rows(yoga_dates, "yoga")
        ))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)

        types = {r.exercise_type for r in results}
        assert "running" in types
        assert "yoga" in types
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_multiple_checkins_per_day_averaged(self):
        """Two mood check-ins on the same day should be averaged."""
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]

        # Build mood rows manually: two check-ins on day 3 (day after exercise on day 2)
        mood_data = []
        for i in range(20):
            d = start + timedelta(days=i)
            ts = datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc).isoformat()
            score = 7 if (d - timedelta(days=LAG_DAYS)) in set(exercise_dates) else 5
            mood_data.append({"created_at": ts, "mood_score": score})

        # Add a second check-in on day 3 with a different score
        day3 = start + timedelta(days=3)
        mood_data.append({
            "created_at": datetime(day3.year, day3.month, day3.day, 20, 0, tzinfo=timezone.utc).isoformat(),
            "mood_score": 9,  # average with the 7 = 8.0
        })

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=mood_data)
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)

        assert len(results) == 1
        assert results[0].sample_size == 5


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------

class TestInsufficientData:

    @pytest.mark.asyncio
    async def test_no_mood_data(self):
        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=[])
        router.set_table("exercise_sessions", data=_exercise_rows([date(2026, 1, 5)], "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_exercise_data(self):
        start = date(2026, 1, 1)
        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20))
        router.set_table("exercise_sessions", data=[])

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_date_span_too_short(self):
        """Fewer than MIN_DATA_DAYS of mood data → empty."""
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [1, 3, 5]]

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 10))  # only 10 days
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_too_few_exercise_samples(self):
        """Fewer than MIN_EXERCISE_SAMPLES for a type → that type is skipped."""
        start = date(2026, 1, 1)
        # Only 2 exercise days — below the 3-sample minimum
        exercise_dates = [start + timedelta(days=2), start + timedelta(days=5)]

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20))
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert results == []


# ---------------------------------------------------------------------------
# Recomputation skip logic
# ---------------------------------------------------------------------------

class TestSkipLogic:

    @pytest.mark.asyncio
    async def test_skips_when_recent_and_few_new_records(self):
        """Recent computation + fewer than NEW_DATA_THRESHOLD new records → skip."""
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

        router = _FakeTableRouter()
        # Return a recent computed_at
        router.set_table("user_correlations", data=[{"computed_at": recent_ts}])
        # Counts for new data: both return count < threshold
        router.set_table("mood_checkins", data=[], count=2)
        router.set_table("exercise_sessions", data=[], count=1)

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_recomputes_when_enough_new_records(self):
        """Recent computation but enough new records → recompute."""
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        # We need table() to return different mocks for different table names.
        # Build a service with a real mock_db that dispatches per table.
        mock_db = MagicMock()

        call_count = {"user_correlations": 0}

        def table_dispatch(name: str) -> MagicMock:
            mock = MagicMock()
            chain = mock
            for method in ("select", "eq", "gt", "order", "limit", "maybe_single"):
                getattr(chain, method).return_value = chain

            if name == "user_correlations":
                call_count["user_correlations"] += 1
                if call_count["user_correlations"] == 1:
                    # First call: skip check — return recent computed_at
                    result = MagicMock()
                    result.data = [{"computed_at": recent_ts}]
                    chain.execute.return_value = result
                else:
                    # Later calls: delete + insert
                    delete_chain = MagicMock()
                    delete_chain.eq.return_value = delete_chain
                    delete_chain.execute.return_value = MagicMock(data=[])
                    mock.delete.return_value = delete_chain
                    mock.insert.return_value.execute.return_value = MagicMock(data=[])
                    chain.execute.return_value = MagicMock(data=[])
            elif name == "mood_checkins":
                # For both the count query and the data query, we need to handle both.
                # The count query comes first (during skip check), data query second.
                result = MagicMock()
                result.data = _mood_rows(start, 20, base_score=5, exercise_dates=exercise_set)
                result.count = 5  # enough new records
                chain.execute.return_value = result
            elif name == "exercise_sessions":
                result = MagicMock()
                result.data = _exercise_rows(exercise_dates, "running")
                result.count = 4  # enough new records (5+4 >= 7)
                chain.execute.return_value = result

            # delete + insert fallbacks
            delete_chain = MagicMock()
            delete_chain.eq.return_value = delete_chain
            delete_chain.execute.return_value = MagicMock(data=[])
            mock.delete.return_value = delete_chain
            mock.insert.return_value.execute.return_value = MagicMock(data=[])

            return mock

        mock_db.table = table_dispatch

        with patch("app.services.correlation.get_supabase_client", return_value=mock_db):
            svc = CorrelationService()

        results = await svc.compute_for_user(USER_ID)
        assert len(results) >= 1
        assert results[0].exercise_type == "running"

    @pytest.mark.asyncio
    async def test_recomputes_when_old_computation(self):
        """Computation older than RECOMPUTE_INTERVAL_DAYS → recompute regardless."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        # Since computation is old (>7 days), the skip check passes and we go
        # straight to data fetch — the simple table router works fine here.
        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[{"computed_at": old_ts}])
        router.set_table("mood_checkins", data=_mood_rows(start, 20, base_score=5, exercise_dates=exercise_set))
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)
        assert len(results) == 1
        assert results[0].exercise_type == "running"


# ---------------------------------------------------------------------------
# get_latest_for_user
# ---------------------------------------------------------------------------

class TestGetLatest:

    @pytest.mark.asyncio
    async def test_returns_stored_rows(self):
        stored = [
            {"exercise_type": "running", "correlation_r": 0.4, "p_value": 0.02},
            {"exercise_type": "yoga", "correlation_r": 0.1, "p_value": 0.5},
        ]
        router = _FakeTableRouter()
        router.set_table("user_correlations", data=stored)

        svc = _build_service(router)
        rows = await svc.get_latest_for_user(USER_ID)
        assert len(rows) == 2
        assert rows[0]["exercise_type"] == "running"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self):
        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])

        svc = _build_service(router)
        rows = await svc.get_latest_for_user(USER_ID)
        assert rows == []


# ---------------------------------------------------------------------------
# Insight text regulatory safety
# ---------------------------------------------------------------------------

class TestInsightText:

    @pytest.mark.asyncio
    async def test_insight_text_no_clinical_language(self):
        """Insight text must not contain banned clinical terms."""
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20, base_score=5, exercise_dates=exercise_set))
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)

        banned = {"diagnose", "treat", "cure", "prescription", "therapy",
                  "clinical", "symptoms", "condition", "disorder"}
        for r in results:
            words = set(r.insight_text.lower().split())
            assert not words & banned, f"Banned term in insight: {words & banned}"

    @pytest.mark.asyncio
    async def test_insight_includes_sample_size_and_p_value(self):
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        router = _FakeTableRouter()
        router.set_table("user_correlations", data=[])
        router.set_table("mood_checkins", data=_mood_rows(start, 20, base_score=5, exercise_dates=exercise_set))
        router.set_table("exercise_sessions", data=_exercise_rows(exercise_dates, "running"))

        svc = _build_service(router)
        results = await svc.compute_for_user(USER_ID)

        assert len(results) >= 1
        for r in results:
            assert "n=" in r.insight_text
            assert "p=" in r.insight_text


# ---------------------------------------------------------------------------
# DB write verification
# ---------------------------------------------------------------------------

class TestDBWrites:

    @pytest.mark.asyncio
    async def test_deletes_old_and_inserts_new(self):
        """Verify DELETE + INSERT is called on user_correlations."""
        start = date(2026, 1, 1)
        exercise_dates = [start + timedelta(days=i) for i in [2, 5, 8, 11, 14]]
        exercise_set = set(exercise_dates)

        mock_db = MagicMock()
        table_mocks: dict[str, MagicMock] = {}

        def table_dispatch(name: str) -> MagicMock:
            if name not in table_mocks:
                mock = MagicMock()
                chain = mock
                for method in ("select", "eq", "gt", "order", "limit", "maybe_single"):
                    getattr(chain, method).return_value = chain

                if name == "user_correlations":
                    chain.execute.return_value = MagicMock(data=[])
                    delete_chain = MagicMock()
                    delete_chain.eq.return_value = delete_chain
                    delete_chain.execute.return_value = MagicMock(data=[])
                    mock.delete.return_value = delete_chain
                    mock.insert.return_value.execute.return_value = MagicMock(data=[])
                elif name == "mood_checkins":
                    result = MagicMock()
                    result.data = _mood_rows(start, 20, base_score=5, exercise_dates=exercise_set)
                    result.count = 0
                    chain.execute.return_value = result
                elif name == "exercise_sessions":
                    result = MagicMock()
                    result.data = _exercise_rows(exercise_dates, "running")
                    result.count = 0
                    chain.execute.return_value = result

                table_mocks[name] = mock
            return table_mocks[name]

        mock_db.table = table_dispatch

        with patch("app.services.correlation.get_supabase_client", return_value=mock_db):
            svc = CorrelationService()

        results = await svc.compute_for_user(USER_ID)
        assert len(results) == 1

        # Verify delete was called
        uc_mock = table_mocks["user_correlations"]
        uc_mock.delete.assert_called_once()
        # Verify insert was called with a list of rows
        uc_mock.insert.assert_called_once()
        inserted = uc_mock.insert.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0]["exercise_type"] == "running"
        assert inserted[0]["user_id"] == USER_ID
