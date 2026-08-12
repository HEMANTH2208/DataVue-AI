"""
LLMSQL Configuration Module

Loads environment variables from .env file using pydantic-settings.
All sensitive configuration (API keys, database paths, feature flags)
is managed here — never hardcoded anywhere else in the codebase.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the LLMSQL application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM Provider ---
    llm_provider: str = "gemini"  # openai | gemini | mock

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # --- Database ---
    default_db_path: str = "data/ecommerce.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
