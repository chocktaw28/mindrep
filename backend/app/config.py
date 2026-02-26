"""
MindRep Configuration
=====================
All environment variables in one place. Pydantic Settings validates
types at startup so misconfigurations fail fast, not at 2am in prod.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Loaded from environment variables or a .env file."""

    # --- Supabase ---
    supabase_url: str = "http://localhost:54321"
    supabase_service_key: str = ""  # service_role key for backend operations

    # --- Anthropic / Claude API ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    # Max tokens for mood classification — structured JSON is small
    anthropic_max_tokens: int = 256

    # --- Oura Ring API ---
    oura_client_id: str = ""
    oura_client_secret: str = ""

    # --- App settings ---
    environment: str = "development"  # development | staging | production
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:8081", "http://localhost:19006"]

    # --- Feature flags ---
    # Kill switch: if False, skip Claude API and use manual tags only.
    # Useful for testing, dev without an API key, or if a user declines
    # AI processing consent.
    enable_ai_classification: bool = True

    # --- Data protection ---
    # Minimum age to use MindRep (UK/US — 18 as per product plan)
    minimum_age_years: int = 18

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
