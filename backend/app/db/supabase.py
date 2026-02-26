"""
Supabase Client
===============
Thin wrapper that provides a configured Supabase client for
dependency injection into FastAPI routes.

Uses the service_role key (not the anon key) because the backend
needs to bypass RLS for operations like inserting mood check-ins
on behalf of authenticated users. RLS still protects direct client
access from the mobile app.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)
