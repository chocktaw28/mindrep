"""
Tests for Oura Service
======================
Covers:
- OuraClient: HTTP response parsing, error handling, auth header
- OuraService token management: valid token return, auto-refresh, DB update, missing token
- OuraService sync: merge by date, upsert calls, source field, null HRV, missing days
- Normalisation: score fields, steps/calories, null duration fields

Run: pytest tests/test_oura.py -v
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import respx
from httpx import Response

from app.models.oura import (
    OuraDailyActivityItem,
    OuraDailyReadinessItem,
    OuraDailySleepItem,
)
from app.models.wearable import WearableDailyCreate
from app.services.oura import (
    OuraAPIError,
    OuraClient,
    OuraService,
    OuraTokenError,
    _normalise,
)

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())
_ACCESS_TOKEN = "test-access-token"
_REFRESH_TOKEN = "test-refresh-token"
_NEW_ACCESS_TOKEN = "new-access-token"

_START = date(2026, 2, 20)
_END = date(2026, 2, 22)

_SLEEP_RESPONSE = {
    "data": [
        {"day": "2026-02-20", "score": 78, "contributors": {}},
        {"day": "2026-02-21", "score": 82, "contributors": {}},
    ]
}

_READINESS_RESPONSE = {
    "data": [
        {"day": "2026-02-20", "score": 71, "contributors": {}},
        {"day": "2026-02-21", "score": 75, "contributors": {}},
    ]
}

_ACTIVITY_RESPONSE = {
    "data": [
        {"day": "2026-02-20", "steps": 8500, "active_calories": 420},
        {"day": "2026-02-21", "steps": 6200, "active_calories": 310},
    ]
}

_TOKEN_RESPONSE = {
    "access_token": _NEW_ACCESS_TOKEN,
    "refresh_token": "new-refresh-token",
    "expires_in": 86400,
    "token_type": "Bearer",
    "scope": "daily",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_expires_at() -> str:
    """ISO timestamp well in the future (token is valid)."""
    return (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()


def _expired_expires_at() -> str:
    """ISO timestamp in the past (token needs refresh)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


def _mock_db_with_token(expires_at: str | None = None, has_token: bool = True) -> MagicMock:
    """Return a mock Supabase client with a token row."""
    mock_db = MagicMock()

    if has_token:
        token_row = {
            "access_token": _ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN,
            "expires_at": expires_at or _future_expires_at(),
        }
    else:
        token_row = None

    # Chain: .table().select().eq().maybe_single().execute()
    mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = token_row
    # Chain: .table().upsert().execute()
    mock_db.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    return mock_db


# ---------------------------------------------------------------------------
# TestOuraClient
# ---------------------------------------------------------------------------

class TestOuraClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_daily_sleep_parses_response(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json=_SLEEP_RESPONSE)
        )
        client = OuraClient(access_token=_ACCESS_TOKEN)
        result = await client.fetch_daily_sleep(_START, _END)

        assert len(result) == 2
        assert result[0].score == 78
        assert result[0].day == date(2026, 2, 20)
        assert result[1].score == 82

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_daily_readiness_parses_response(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json=_READINESS_RESPONSE)
        )
        client = OuraClient(access_token=_ACCESS_TOKEN)
        result = await client.fetch_daily_readiness(_START, _END)

        assert len(result) == 2
        assert result[0].score == 71
        assert result[0].day == date(2026, 2, 20)

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_daily_activity_parses_response(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json=_ACTIVITY_RESPONSE)
        )
        client = OuraClient(access_token=_ACCESS_TOKEN)
        result = await client.fetch_daily_activity(_START, _END)

        assert len(result) == 2
        assert result[0].steps == 8500
        assert result[0].active_calories == 420

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_2xx_raises_OuraAPIError(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(401, text="Unauthorized")
        )
        client = OuraClient(access_token="bad-token")
        with pytest.raises(OuraAPIError) as exc_info:
            await client.fetch_daily_sleep(_START, _END)

        assert exc_info.value.status_code == 401
        assert "Unauthorized" in exc_info.value.body

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_token_sent_in_header(self):
        route = respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json={"data": []})
        )
        client = OuraClient(access_token=_ACCESS_TOKEN)
        await client.fetch_daily_sleep(_START, _END)

        assert route.called
        request = route.calls[0].request
        assert request.headers["Authorization"] == f"Bearer {_ACCESS_TOKEN}"


# ---------------------------------------------------------------------------
# TestTokenManagement
# ---------------------------------------------------------------------------

class TestTokenManagement:

    @pytest.mark.asyncio
    async def test_get_access_token_returns_valid_token(self):
        mock_db = _mock_db_with_token(expires_at=_future_expires_at())
        with patch("app.services.oura.get_supabase_client", return_value=mock_db), \
             patch("app.services.oura.get_settings", return_value=MagicMock()):
            service = OuraService()
            token = await service.get_access_token(_USER_ID)

        assert token == _ACCESS_TOKEN

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_access_token_refreshes_when_expired(self):
        """If expires_at is in the past, the service should call the refresh endpoint."""
        respx.post("https://api.ouraring.com/oauth/token").mock(
            return_value=Response(200, json=_TOKEN_RESPONSE)
        )
        mock_db = _mock_db_with_token(expires_at=_expired_expires_at())
        with patch("app.services.oura.get_supabase_client", return_value=mock_db), \
             patch("app.services.oura.get_settings", return_value=MagicMock(oura_client_id="id", oura_client_secret="secret")):
            service = OuraService()
            token = await service.get_access_token(_USER_ID)

        assert token == _NEW_ACCESS_TOKEN

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_token_updates_db_row(self):
        """refresh_token() should upsert the new token into oura_tokens."""
        respx.post("https://api.ouraring.com/oauth/token").mock(
            return_value=Response(200, json=_TOKEN_RESPONSE)
        )
        mock_db = _mock_db_with_token()
        with patch("app.services.oura.get_supabase_client", return_value=mock_db), \
             patch("app.services.oura.get_settings", return_value=MagicMock(oura_client_id="id", oura_client_secret="secret")):
            service = OuraService()
            new_token = await service.refresh_token(_USER_ID)

        assert new_token == _NEW_ACCESS_TOKEN
        # upsert should have been called on oura_tokens
        mock_db.table.assert_called_with("oura_tokens")
        mock_db.table.return_value.upsert.assert_called_once()
        upsert_payload = mock_db.table.return_value.upsert.call_args[0][0]
        assert upsert_payload["access_token"] == _NEW_ACCESS_TOKEN
        assert upsert_payload["user_id"] == _USER_ID

    @pytest.mark.asyncio
    async def test_get_access_token_raises_when_no_token_row(self):
        mock_db = _mock_db_with_token(has_token=False)
        with patch("app.services.oura.get_supabase_client", return_value=mock_db), \
             patch("app.services.oura.get_settings", return_value=MagicMock()):
            service = OuraService()
            with pytest.raises(OuraTokenError):
                await service.get_access_token(_USER_ID)


# ---------------------------------------------------------------------------
# TestSyncUserData
# ---------------------------------------------------------------------------

class TestSyncUserData:

    def _make_service_with_mocks(self, mock_db: MagicMock) -> OuraService:
        with patch("app.services.oura.get_supabase_client", return_value=mock_db), \
             patch("app.services.oura.get_settings", return_value=MagicMock()):
            return OuraService()

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_merges_sleep_readiness_activity_by_date(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json=_SLEEP_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json=_READINESS_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json=_ACTIVITY_RESPONSE)
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        assert len(results) == 2
        feb20 = next(r for r in results if r.date == date(2026, 2, 20))
        assert feb20.sleep_score == 78.0
        assert feb20.readiness_score == 71.0
        assert feb20.steps == 8500

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_upserts_each_day_into_wearable_daily(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json=_SLEEP_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json=_READINESS_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json=_ACTIVITY_RESPONSE)
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        # 2 dates → 2 upsert calls on wearable_daily
        upsert_calls = [
            c for c in mock_db.table.call_args_list
            if c.args == ("wearable_daily",)
        ]
        assert len(upsert_calls) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_sets_source_to_oura(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json={"data": [{"day": "2026-02-20", "score": 80, "contributors": {}}]})
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json={"data": []})
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json={"data": []})
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        assert all(r.source == "oura" for r in results)

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_leaves_hrv_fields_null(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json=_SLEEP_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json=_READINESS_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json=_ACTIVITY_RESPONSE)
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        for r in results:
            assert r.hrv_avg is None
            assert r.hrv_min is None
            assert r.hrv_max is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_handles_missing_days_gracefully(self):
        """Sleep data for Feb 20, but no activity for same date — should still produce a record."""
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json={"data": [{"day": "2026-02-20", "score": 78, "contributors": {}}]})
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json={"data": []})
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json={"data": []})  # no activity
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        assert len(results) == 1
        assert results[0].date == date(2026, 2, 20)
        assert results[0].steps is None
        assert results[0].sleep_score == 78.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_returns_list_of_wearable_daily_create(self):
        respx.get("https://api.ouraring.com/v2/usercollection/daily_sleep").mock(
            return_value=Response(200, json=_SLEEP_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_readiness").mock(
            return_value=Response(200, json=_READINESS_RESPONSE)
        )
        respx.get("https://api.ouraring.com/v2/usercollection/daily_activity").mock(
            return_value=Response(200, json=_ACTIVITY_RESPONSE)
        )

        mock_db = _mock_db_with_token()
        service = self._make_service_with_mocks(mock_db)
        results = await service.sync_user_data(_USER_ID, _START, _END)

        assert isinstance(results, list)
        assert all(isinstance(r, WearableDailyCreate) for r in results)


# ---------------------------------------------------------------------------
# TestNormalisation
# ---------------------------------------------------------------------------

class TestNormalisation:

    def _sleep(self, day: date, score: int) -> OuraDailySleepItem:
        return OuraDailySleepItem(day=day, score=score, contributors={})

    def _readiness(self, day: date, score: int) -> OuraDailyReadinessItem:
        return OuraDailyReadinessItem(day=day, score=score, contributors={})

    def _activity(self, day: date, steps: int, calories: int) -> OuraDailyActivityItem:
        return OuraDailyActivityItem(day=day, steps=steps, active_calories=calories)

    def test_sleep_score_mapped_correctly(self):
        day = date(2026, 2, 20)
        results = _normalise([self._sleep(day, 85)], [], [])
        assert results[0].sleep_score == 85.0

    def test_readiness_score_mapped_correctly(self):
        day = date(2026, 2, 20)
        results = _normalise([], [self._readiness(day, 72)], [])
        assert results[0].readiness_score == 72.0

    def test_steps_and_active_calories_mapped(self):
        day = date(2026, 2, 20)
        results = _normalise([], [], [self._activity(day, 9000, 500)])
        assert results[0].steps == 9000
        assert results[0].active_calories == 500.0

    def test_raw_duration_fields_are_null(self):
        """sleep_duration_minutes, sleep_deep_minutes, sleep_rem_minutes must be null."""
        day = date(2026, 2, 20)
        results = _normalise([self._sleep(day, 80)], [], [])
        r = results[0]
        assert r.sleep_duration_minutes is None
        assert r.sleep_deep_minutes is None
        assert r.sleep_rem_minutes is None

    def test_resting_hr_is_null(self):
        """resting_hr must be null — contributors score is not bpm."""
        day = date(2026, 2, 20)
        results = _normalise([], [self._readiness(day, 70)], [])
        assert results[0].resting_hr is None

    def test_all_three_sources_merged_for_same_date(self):
        day = date(2026, 2, 20)
        results = _normalise(
            [self._sleep(day, 78)],
            [self._readiness(day, 71)],
            [self._activity(day, 8500, 420)],
        )
        assert len(results) == 1
        r = results[0]
        assert r.sleep_score == 78.0
        assert r.readiness_score == 71.0
        assert r.steps == 8500

    def test_source_is_oura(self):
        day = date(2026, 2, 20)
        results = _normalise([self._sleep(day, 80)], [], [])
        assert results[0].source == "oura"

    def test_none_sleep_score_stays_none(self):
        day = date(2026, 2, 20)
        sleep = OuraDailySleepItem(day=day, score=None, contributors={})
        results = _normalise([sleep], [], [])
        assert results[0].sleep_score is None
