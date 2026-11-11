"""Runtime configuration. All secrets come from the environment; nothing here is logged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

CODE_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OQUMAP_", env_file=(".env", "../../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/oqumap"
    storage_dir: Path = REPO_ROOT / "storage"
    demo_data_dir: Path = REPO_ROOT / "data" / "demo"
    # Jobs: "worker" (separate process polls the DB) or "inline" (executed in a background thread
    # of the API process; convenient for development and tests).
    job_mode: str = "inline"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    max_upload_bytes: int = 15 * 1024 * 1024
    max_import_rows: int = 200_000

    # Model provider. "none" keeps the app fully functional via template / recorded_demo modes.
    llm_provider: str = "none"  # none | anthropic
    llm_model: str = "claude-opus-5-5"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = Field(default=None)
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_input_chars: int = 24_000
    llm_max_output_tokens: int = 1_500

    # OCR adapter: "none" or "tesseract" (requires the tesseract binary on PATH).
    ocr_engine: str = "none"

    session_ttl_hours: int = 12
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
