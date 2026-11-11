"""Facade between OquMap AI tasks and the provider-neutral LLM layer (oqumap/ai/llm).

* ``get_provider()`` builds the configured chain (primary + optional explicit fallbacks) or returns a
  ``Provider`` that is unavailable (none) / misconfigured (diagnostic code, never a 500).
* Keys come only from provider-specific settings (OQUMAP_GEMINI_API_KEY, OQUMAP_OPENROUTER_API_KEY,
  OQUMAP_OPENAI_API_KEY, OQUMAP_ANTHROPIC_API_KEY); they are never logged, returned or stored.
* Resilience: bounded retries for retryable errors (inside adapters), a database-backed circuit breaker per
  provider, a per-organisation token ceiling, and cross-provider fallback only when explicitly allowed
  (it sends data to a different processor, so it is audited).
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass

from ..config import REPO_ROOT, get_settings
from .llm.adapters import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIResponsesProvider,
    OpenRouterProvider,
    RecordedProvider,
)
from .llm.base import Capabilities, LLMError, LLMProvider, ToolSpec

log = logging.getLogger("oqumap.ai")

PROVIDERS = ("none", "recorded", "gemini", "openrouter", "openai", "anthropic")
MODEL_PATTERNS = {
    "gemini": re.compile(r"^(models/)?gemini-[a-z0-9.\-]{1,80}$"),
    "openrouter": re.compile(r"^[a-z0-9][a-z0-9_\-.]*/[a-zA-Z0-9_\-.:]{1,100}$"),
    "openai": re.compile(r"^[a-z0-9][a-z0-9_\-.:]{1,100}$"),
    "anthropic": re.compile(r"^claude-[a-z0-9][a-z0-9.\-]{2,80}$"),
}


class ModelUnavailable(LLMError):
    def __init__(self, reason: str):
        super().__init__(reason)


@dataclass
class CallMeta:
    provider: str
    model: str | None
    latency_ms: int
    tokens: int = 0
    structured_mode: str = "native"


def _key(provider: str) -> str | None:
    s = get_settings()
    v = getattr(s, f"{provider}_api_key", None)
    if v is None:
        return None
    k = v.get_secret_value().strip()
    return None if (not k or k.startswith("<")) else k


def _problem_for(provider: str, model: str) -> str | None:
    if provider not in PROVIDERS:
        return "unknown_provider"
    if provider in ("none", "recorded"):
        return None
    if not _key(provider):
        return "api_key_missing"
    if not model or not MODEL_PATTERNS[provider].match(model.strip()):
        return "invalid_model_id"
    return None


def llm_config_problem() -> str | None:
    """Diagnostic code when the configured live provider/fallbacks cannot work; None when usable."""
    s = get_settings()
    p = _problem_for(s.llm_provider, s.llm_model)
    if p:
        return p
    if s.llm_timeout_seconds <= 0 or s.llm_max_retries < 0 or s.llm_max_input_chars <= 0:
        return "invalid_limits"
    for fb in s.llm_fallbacks:
        prov, _, model = fb.partition(":")
        if _problem_for(prov, model):
            return f"fallback_{prov}_{_problem_for(prov, model)}"
        if prov != s.llm_provider and not s.llm_allow_cross_provider_fallback:
            return "cross_provider_fallback_not_allowed"
    return None


def build_adapter(provider: str, model: str, transport=None) -> LLMProvider:
    s = get_settings()
    common = {"timeout": s.llm_timeout_seconds, "max_retries": s.llm_max_retries, "transport": transport,
              "max_output_tokens": s.llm_max_output_tokens * 4}
    if provider == "gemini":
        a = GeminiProvider(model, api_key=_key("gemini"), base_url=s.gemini_base_url, **common)
        a.data_policy = "no_training" if s.gemini_paid_tier else "may_train"
    elif provider == "openrouter":
        a = OpenRouterProvider(model, api_key=_key("openrouter"), base_url=s.openrouter_base_url, **common)
    elif provider == "openai":
        a = OpenAIResponsesProvider(model, api_key=_key("openai"), base_url=s.openai_base_url, **common)
    elif provider == "anthropic":
        a = AnthropicProvider(model, api_key=_key("anthropic"), base_url=s.anthropic_base_url,
                              refusal_fallback=s.llm_refusal_fallback, **common)
    elif provider == "recorded":
        a = RecordedProvider(REPO_ROOT / "data" / "demo" / "recorded" / "llm")
    else:
        raise LLMError("config", "unknown_provider")
    if s.llm_data_policy:
        a.data_policy = s.llm_data_policy
    return a


class Provider:
    """What AI tasks see. Base class = no provider configured."""

    name = "none"
    model: str | None = None
    config_error: str | None = None
    data_policy = "none"
    capabilities = Capabilities()

    @property
    def available(self) -> bool:
        return False

    @property
    def is_recorded(self) -> bool:
        return self.name == "recorded"

    def complete_json(self, system: str, user: str, schema: dict, name: str = "result") -> tuple[dict, CallMeta]:
        raise ModelUnavailable("provider_not_configured")

    def run_tools(self, system: str, user: str, tools: list[ToolSpec], execute, max_steps: int = 4):
        raise ModelUnavailable("provider_not_configured")


class MisconfiguredProvider(Provider):
    def __init__(self, name: str, problem: str):
        self.name = name
        self.model = get_settings().llm_model or None
        self.config_error = problem


_PROBE_CACHE: dict[str, tuple[float, Capabilities]] = {}


class ChainProvider(Provider):
    """Primary adapter plus explicitly configured fallbacks."""

    def __init__(self, chain: list[LLMProvider]):
        self.chain = chain
        self.name = chain[0].name
        self.model = chain[0].model
        self.data_policy = chain[0].data_policy
        cached = _PROBE_CACHE.get(f"{self.name}:{self.model}")
        self.capabilities = cached[1] if cached and time.monotonic() - cached[0] < 600 else chain[0].capabilities

    @property
    def available(self) -> bool:
        return True

    def probe(self) -> Capabilities:
        caps = self.chain[0].probe()
        _PROBE_CACHE[f"{self.name}:{self.model}"] = (time.monotonic(), caps)
        self.capabilities = caps
        return caps

    def _check_size(self, *parts: str) -> None:
        if sum(len(p) for p in parts) > get_settings().llm_max_input_chars:
            raise ModelUnavailable("input_too_large")

    def _each(self):
        from .gate import circuit_open, record_failure, record_fallback

        for i, adapter in enumerate(self.chain):
            if circuit_open(adapter.name):
                if i + 1 < len(self.chain):
                    continue
                raise LLMError("circuit_open", adapter.name)
            if i > 0:
                record_fallback(self.chain[0].name, adapter.name)
            yield adapter, (lambda a=adapter: record_failure(a.name))

    def complete_json(self, system: str, user: str, schema: dict, name: str = "result") -> tuple[dict, CallMeta]:
        self._check_size(system, user)
        last: LLMError | None = None
        for adapter, fail in self._each():
            try:
                r = adapter.structured(system, user, schema, name)
                return r.data or {}, CallMeta(r.provider, r.model, r.latency_ms, r.usage.total, r.structured_mode)
            except LLMError as exc:
                log.warning("llm %s structured failed: %s", adapter.name, exc.kind)  # kind only, never payloads
                if exc.retryable or exc.kind in ("server", "auth"):
                    fail()
                last = exc
                if exc.kind in ("refusal", "invalid_output", "bad_request", "policy"):
                    break  # do not shop the same content around providers
        raise ModelUnavailable(last.reason if last else "unavailable")

    def run_tools(self, system: str, user: str, tools: list[ToolSpec], execute, max_steps: int = 4):
        self._check_size(system, user)
        last: LLMError | None = None
        for adapter, fail in self._each():
            if not adapter.capabilities.tool_calling:
                last = LLMError("capability", "tool_calling_not_supported")
                continue
            try:
                text, trace, r = adapter.tool_loop(system, user, tools, execute, max_steps)
                return text, trace, CallMeta(r.provider, r.model, r.latency_ms, r.usage.total)
            except LLMError as exc:
                log.warning("llm %s tool loop failed: %s", adapter.name, exc.kind)
                if exc.retryable or exc.kind in ("server", "auth"):
                    fail()
                last = exc
                if exc.kind in ("refusal", "bad_request", "policy"):
                    break
        raise ModelUnavailable(last.reason if last else "unavailable")


_provider_override: Provider | None = None


def get_provider() -> Provider:
    if _provider_override is not None:
        return _provider_override
    s = get_settings()
    if s.llm_provider == "none":
        return Provider()
    problem = llm_config_problem()
    if problem:
        return MisconfiguredProvider(s.llm_provider, problem)
    chain = [build_adapter(s.llm_provider, s.llm_model)]
    for fb in s.llm_fallbacks:
        prov, _, model = fb.partition(":")
        chain.append(build_adapter(prov, model))
    return ChainProvider(chain)


@contextmanager
def use_provider(p: Provider):
    """Temporarily route AI tasks through ``p`` (operator recording command, tests)."""
    global _provider_override
    prev, _provider_override = _provider_override, p
    try:
        yield
    finally:
        _provider_override = prev


def set_provider_for_tests(p: Provider | None) -> None:
    global _provider_override
    _provider_override = p
