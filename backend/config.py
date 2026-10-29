"""backend/config.py - Application configuration and environment variables."""

import os
import secrets
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Model integration
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NEMOTRON_MODEL: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    # Perception / GitHub
    GITHUB_TOKEN: str = ""
    TESSERACT_PATH: str = ""

    # Security & Sandbox
    APPROVAL_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    ALLOWED_ROOT: str = "./demo-workspace"
    API_SESSION_TOKEN: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=32, repr=False)
    SANDBOX_IMAGE: str = "prism-sandbox:local"
    ACTION_TIMEOUT_SECONDS: float = 30
    MODEL_TIMEOUT_SECONDS: float = 90
    SCREENSHOT_TTL_SECONDS: int = 3600
    TASK_TTL_SECONDS: int = Field(default=3600, ge=60)
    MAX_RETAINED_TASKS: int = Field(default=100, ge=1, le=1000)
    STATE_DIR: str = str(APP_ROOT / '.prism')

    # Operational modes
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    CORS_ORIGIN: str = "http://localhost:5173"
    DEV_FRONTEND: bool = False

    model_config = SettingsConfigDict(
        env_file=os.environ.get('PRISM_ENV_FILE', str(APP_ROOT / '.env')),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
settings.ALLOWED_ROOT = str(Path(settings.ALLOWED_ROOT).resolve())
settings.STATE_DIR = str(Path(settings.STATE_DIR).resolve())

# Expose .env values to M1's environment-based collectors and redactor.
for _name in ("GITHUB_TOKEN", "TESSERACT_PATH", "APPROVAL_SECRET", "ALLOWED_ROOT", "NVIDIA_API_KEY"):
    os.environ.setdefault(_name, str(getattr(settings, _name)))
