"""Runtime configuration. All secrets come from the environment; nothing here is logged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    # measurement & learning-loop demo inside a disposable tenant: background job (default), sync (tests), off
    demo_tenant_measurement: str = "background"
    demo_tenant_ttl_hours: float = 6.0
    demo_max_active_tenants: int = 300
    demo_tenants_per_ip_per_hour: int = 6
    demo_storage_quota_mb: int = 25
    org_storage_quota_mb: int = 500

    max_upload_bytes: int = 15 * 1024 * 1024
    max_import_rows: int = 200_000

    # Model provider (provider-agnostic). "none" keeps the app fully functional via template / recorded_demo modes.
    # none | recorded | gemini | openrouter | openai | anthropic
    llm_provider: str = "none"
    # Model ID of the selected provider (no runtime default: choose it with scripts/eval_llm_provider.py), e.g.
    # gemini: gemini-3.8-flash (fallback gemini:gemini-3.5-flash-lite) · openrouter/openai/anthropic: exact provider ID
    llm_model: str = ""
    # Provider-specific keys / endpoints (never one shared key)
    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_paid_tier: bool = False  # free tier: Google may use prompts to improve products
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_refusal_fallback: bool = True  # Anthropic server-side refusal fallback (beta)
    # Data protection: live calls for non-synthetic datasets are blocked unless explicitly allowed for a provider
    # whose data policy permits it (never for "may_train" policies such as the Gemini free tier).
    llm_real_data_allowed: bool = False
    llm_data_policy: str | None = None  # override: no_training | may_train | api_default
    # Explicit fallback chain "provider:model" (different provider = different privacy policy → opt-in + audit)
    llm_fallbacks: list[str] = []
    llm_allow_cross_provider_fallback: bool = False
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_input_chars: int = 24_000
    llm_max_output_tokens: int = 1_500
    # Who may trigger live model calls and how many (demo tenants never use live AI).
    llm_live_roles: list[str] = ["methodist", "approver"]
    llm_live_per_org_per_day: int = 200
    llm_live_per_user_per_hour: int = 40
    llm_max_tokens_per_org_per_day: int = 300_000
    llm_circuit_failures: int = 5
    llm_circuit_window_seconds: int = 120

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
