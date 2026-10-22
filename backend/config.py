"""backend/config.py - Application configuration and environment variables."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Model integration
    NEBIUS_API_KEY: str = ""
    NEBIUS_BASE_URL: str = "https://api.studio.nebius.ai/v1"
    NEMOTRON_MODEL: str = "nvidia/nemotron-4-340b-instruct"

    # Perception / GitHub
    GITHUB_TOKEN: str = ""

    # Security & Sandbox
    APPROVAL_SECRET: str = "default-dev-approval-secret-32-chars-long"
    ALLOWED_ROOT: str = "."

    # Operational modes
    MOCK_MODE: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGIN: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
