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

    # dev: QA personas (shared demo org, other_org) enabled
    # public_demo: one-click demo creates a disposable tenant per visitor; no live AI for demo tenants
    # production: demo login disabled; only password accounts
    deployment_mode: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/oqumap"
    storage_dir: Path = REPO_ROOT / "storage"
    demo_data_dir: Path = REPO_ROOT / "data" / "demo"
    # Jobs: "worker" (separate process polls the DB) or "inline" (executed in a background thread
    # of the API process; convenient for development and tests).
    job_mode: str = "inline"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Host header allow-list ("*" only for local development).
    allowed_hosts: list[str] = ["*"]
    # Peers whose X-Forwarded-For is trusted (the reverse proxy); CIDR or IP.
    trusted_proxies: list[str] = ["127.0.0.1/32", "::1/128"]

    # Public demo tenants
    demo_tenant_ttl_hours: float = 6.0
    demo_max_active_tenants: int = 300
    demo_tenants_per_ip_per_hour: int = 6
    demo_storage_quota_mb: int = 25
    org_storage_quota_mb: int = 500

    max_upload_bytes: int = 15 * 1024 * 1024
    max_import_rows: int = 200_000

    # Model provider. "none" keeps the app fully functional via template / recorded_demo modes.
    llm_provider: str = "none"  # none | anthropic
    # Default: current Sonnet (latency/cost balance for the demo). Any Claude API model ID can be configured.
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = Field(default=None)
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_input_chars: int = 24_000
    llm_max_output_tokens: int = 1_500
    # Server-side refusal fallback (beta "server-side-fallback-2026-07-01", fallbacks="default").
    llm_refusal_fallback: bool = True
    # Who may trigger live model calls and how many (demo tenants never use live AI).
    llm_live_roles: list[str] = ["methodist", "approver"]
    llm_live_per_org_per_day: int = 200
    llm_live_per_user_per_hour: int = 40

    # OCR adapter: "none" or "tesseract" (requires the tesseract binary on PATH).
    ocr_engine: str = "none"

    session_ttl_hours: int = 12
    # Fixed-window rate limits: "<count>/<seconds>"
    rate_login: str = "20/600"
    rate_import: str = "30/3600"
    rate_document: str = "20/3600"
    rate_ai: str = "60/3600"
    rate_assistant: str = "40/600"
    rate_compute: str = "240/600"
    log_level: str = "INFO"


VALID_MODES = ("dev", "public_demo", "production")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.deployment_mode not in VALID_MODES:
        raise ValueError(f"OQUMAP_DEPLOYMENT_MODE must be one of {VALID_MODES}")
    return s


def parse_rate(spec: str) -> tuple[int, int]:
    count, seconds = spec.split("/")
    return int(count), int(seconds)
