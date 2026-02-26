"""
Oura Ring Service
=================
OAuth2 token management and data sync for the Oura REST API v2.

Responsibilities:
- exchange_code(): trade OAuth auth code for access + refresh tokens, store in DB
- refresh_token(): use stored refresh token to obtain a new access token
- get_access_token(): return a valid (non-expired) token for a user, auto-refreshing
- sync_user_data(): fetch sleep/readiness/activity from Oura, normalise, upsert

Data protection rules (from CLAUDE.md):
- Biometric data NEVER leaves our infrastructure — all Oura data is pulled INTO
  our DB, never forwarded externally.
- HRV avg/min/max left null for MVP — Oura v2 daily endpoints return contributor
  scores (1–100), not raw metric values. Don't fabricate data.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import get_settings
from app.db.supabase import get_supabase_client
from app.models.oura import (
    OuraDailyActivityItem,
    OuraDailyReadinessItem,
    OuraDailySleepItem,
    OuraTokenResponse,
)
from app.models.wearable import WearableDailyCreate

OURA_BASE_URL = "https://api.ouraring.com"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"

# Refresh the access token this many minutes before it actually expires
_EXPIRY_BUFFER_MINUTES = 5


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OuraAPIError(Exception):
    """Non-2xx response from Oura API."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Oura API error {status_code}: {body}")


class OuraTokenError(Exception):
    """No token found or token refresh failed for user."""


# ---------------------------------------------------------------------------
# OuraClient — thin HTTP wrapper around the Oura v2 API
# ---------------------------------------------------------------------------


class OuraClient:
    """Makes authenticated requests to the Oura REST API v2."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    async def fetch_daily_sleep(
        self, start_date: date, end_date: date
    ) -> list[OuraDailySleepItem]:
        """GET /v2/usercollection/daily_sleep for the given date range."""
        data = await self._get(
            "/v2/usercollection/daily_sleep",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return [OuraDailySleepItem(**item) for item in data.get("data", [])]

    async def fetch_daily_readiness(
        self, start_date: date, end_date: date
    ) -> list[OuraDailyReadinessItem]:
        """GET /v2/usercollection/daily_readiness for the given date range."""
        data = await self._get(
            "/v2/usercollection/daily_readiness",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return [OuraDailyReadinessItem(**item) for item in data.get("data", [])]

    async def fetch_daily_activity(
        self, start_date: date, end_date: date
    ) -> list[OuraDailyActivityItem]:
        """GET /v2/usercollection/daily_activity for the given date range."""
        data = await self._get(
            "/v2/usercollection/daily_activity",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return [OuraDailyActivityItem(**item) for item in data.get("data", [])]

    async def _get(self, path: str, params: dict) -> dict:
        """Shared async GET call with Bearer auth. Raises OuraAPIError on non-2xx."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{OURA_BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        if not response.is_success:
            raise OuraAPIError(response.status_code, response.text)
        return response.json()


# ---------------------------------------------------------------------------
# OuraService — token management + data sync
# ---------------------------------------------------------------------------


class OuraService:
    """Manages Oura OAuth2 tokens and syncs data into wearable_daily."""

    def __init__(self) -> None:
        self._db = get_supabase_client()
        self._settings = get_settings()

    # ---- Token management ------------------------------------------------

    async def exchange_code(self, code: str, redirect_uri: str, user_id: str) -> OuraTokenResponse:
        """
        Trade an OAuth authorisation code for access + refresh tokens.
        Stores the token pair in oura_tokens (upsert on user_id).
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OURA_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._settings.oura_client_id,
                    "client_secret": self._settings.oura_client_secret,
                },
            )
        if not response.is_success:
            raise OuraAPIError(response.status_code, response.text)

        token = OuraTokenResponse(**response.json())
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.expires_in)

        self._db.table("oura_tokens").upsert(
            {
                "user_id": user_id,
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": expires_at.isoformat(),
                "scope": token.scope,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id",
        ).execute()

        return token

    async def refresh_token(self, user_id: str) -> str:
        """
        Use the stored refresh token to obtain a new access token.
        Updates the oura_tokens row and returns the new access_token.
        Raises OuraTokenError if no token row exists.
        """
        result = (
            self._db.table("oura_tokens")
            .select("refresh_token")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not result.data:
            raise OuraTokenError(f"No Oura token found for user {user_id}")

        stored_refresh = result.data["refresh_token"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                OURA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": stored_refresh,
                    "client_id": self._settings.oura_client_id,
                    "client_secret": self._settings.oura_client_secret,
                },
            )
        if not response.is_success:
            raise OuraAPIError(response.status_code, response.text)

        token = OuraTokenResponse(**response.json())
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.expires_in)

        self._db.table("oura_tokens").upsert(
            {
                "user_id": user_id,
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": expires_at.isoformat(),
                "scope": token.scope,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id",
        ).execute()

        return token.access_token

    async def get_access_token(self, user_id: str) -> str:
        """
        Return a valid access token for the user.
        Auto-refreshes if the token expires within the buffer window.
        Raises OuraTokenError if no token row exists.
        """
        result = (
            self._db.table("oura_tokens")
            .select("access_token, expires_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not result.data:
            raise OuraTokenError(f"No Oura token found for user {user_id}")

        row = result.data
        expires_at = datetime.fromisoformat(row["expires_at"])
        # Normalise to UTC if naive
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        buffer = timedelta(minutes=_EXPIRY_BUFFER_MINUTES)
        if datetime.now(timezone.utc) + buffer >= expires_at:
            return await self.refresh_token(user_id)

        return row["access_token"]

    # ---- Data sync -------------------------------------------------------

    async def sync_user_data(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[WearableDailyCreate]:
        """
        Fetch sleep, readiness, and activity from Oura for the date range,
        normalise into WearableDailyCreate, upsert into wearable_daily, and
        return the list of created/updated records.
        """
        access_token = await self.get_access_token(user_id)
        oura = OuraClient(access_token)

        sleep_items, readiness_items, activity_items = await asyncio.gather(
            oura.fetch_daily_sleep(start_date, end_date),
            oura.fetch_daily_readiness(start_date, end_date),
            oura.fetch_daily_activity(start_date, end_date),
        )

        records = _normalise(sleep_items, readiness_items, activity_items)

        for record in records:
            self._db.table("wearable_daily").upsert(
                {
                    "user_id": user_id,
                    **record.model_dump(),
                    "date": record.date.isoformat(),
                },
                on_conflict="user_id,date,source",
            ).execute()

        return records


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------


def _normalise(
    sleep_items: list[OuraDailySleepItem],
    readiness_items: list[OuraDailyReadinessItem],
    activity_items: list[OuraDailyActivityItem],
) -> list[WearableDailyCreate]:
    """
    Merge sleep, readiness, and activity data by date into WearableDailyCreate.

    Oura v2 daily_sleep and daily_readiness return contributor *scores* (1–100),
    not raw metric values (minutes of deep sleep, bpm). Raw values live on the
    verbose /sleep and /heartrate endpoints. For MVP we populate the score fields
    and leave raw metric fields null — we do not fabricate data.
    """
    sleep_by_date: dict[date, OuraDailySleepItem] = {s.day: s for s in sleep_items}
    readiness_by_date: dict[date, OuraDailyReadinessItem] = {r.day: r for r in readiness_items}
    activity_by_date: dict[date, OuraDailyActivityItem] = {a.day: a for a in activity_items}

    all_dates = sleep_by_date.keys() | readiness_by_date.keys() | activity_by_date.keys()

    results: list[WearableDailyCreate] = []
    for day in sorted(all_dates):
        sleep = sleep_by_date.get(day)
        readiness = readiness_by_date.get(day)
        activity = activity_by_date.get(day)

        results.append(
            WearableDailyCreate(
                date=day,
                source="oura",
                sleep_score=float(sleep.score) if sleep and sleep.score is not None else None,
                # Raw duration fields require the verbose /sleep endpoint — null for MVP
                sleep_duration_minutes=None,
                sleep_deep_minutes=None,
                sleep_rem_minutes=None,
                readiness_score=float(readiness.score) if readiness and readiness.score is not None else None,
                # resting_heart_rate in daily_readiness contributors is a 1-100 score, not bpm
                resting_hr=None,
                steps=activity.steps if activity else None,
                active_calories=float(activity.active_calories) if activity and activity.active_calories is not None else None,
                # HRV fields: null for MVP — raw HRV not available on daily summary endpoints
                hrv_avg=None,
                hrv_min=None,
                hrv_max=None,
            )
        )

    return results
