"""Model provider adapter.

* Keys live only on the server (``OQUMAP_LLM_API_KEY`` or the SDK's standard ``ANTHROPIC_API_KEY``); they are
  never logged, returned by the API or bundled into the frontend.
* Input size is limited (no silent truncation: oversize input => the caller falls back to ``template``).
* Timeouts and a bounded number of retries are delegated to the official SDK client.
* Responses are structured JSON (``output_config.format`` with a JSON schema) and validated by the caller.
* The provider is selected by configuration; ``none`` disables live calls entirely. Another provider can be
  added by implementing :class:`Provider`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

from ..config import get_settings

log = logging.getLogger("oqumap.ai")


class ModelUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class CallMeta:
    provider: str
    model: str | None
    latency_ms: int


MODEL_ID_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]{2,80}$")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def llm_config_problem() -> str | None:
    """Return a diagnostic code when the configured live provider cannot work, else None.

    Never includes the key itself."""
    s = get_settings()
    if s.llm_provider == "none":
        return None
    if s.llm_provider != "anthropic":
        return "unknown_provider"
    key = s.llm_api_key.get_secret_value().strip() if s.llm_api_key else os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("<"):
        return "api_key_missing"
    if not s.llm_model or not MODEL_ID_RE.match(s.llm_model.strip()):
        return "invalid_model_id"
    if s.llm_timeout_seconds <= 0 or s.llm_max_retries < 0 or s.llm_max_input_chars <= 0:
        return "invalid_limits"
    return None


class Provider:
    name = "none"
    model: str | None = None
    config_error: str | None = None

    @property
    def available(self) -> bool:
        return False

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> tuple[dict, CallMeta]:
        raise ModelUnavailable("provider_not_configured")

    def run_tools(self, system: str, messages: list[dict], tools: list[dict], execute, max_steps: int = 4
                  ) -> tuple[str, list[dict], CallMeta]:
        raise ModelUnavailable("provider_not_configured")


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, client=None):
        s = get_settings()
        self.model = s.llm_model
        self._settings = s
        self._client = client

    @property
    def available(self) -> bool:
        if self._client is not None:
            return True
        return llm_config_problem() is None

    def _get_client(self):
        if self._client is None:
            import anthropic

            s = self._settings
            kwargs = {"timeout": s.llm_timeout_seconds, "max_retries": min(s.llm_max_retries, 3)}
            if s.llm_api_key:
                kwargs["api_key"] = s.llm_api_key.get_secret_value()
            if s.llm_base_url:
                kwargs["base_url"] = s.llm_base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def _fallback_kwargs(self) -> dict:
        """Server-side refusal fallback: on a policy decline the API re-runs the request on a fallback model."""
        if not self._settings.llm_refusal_fallback:
            return {}
        return {"extra_headers": {"anthropic-beta": FALLBACK_BETA}, "extra_body": {"fallbacks": "default"}}

    def _check_size(self, *parts: str) -> None:
        if sum(len(p) for p in parts) > self._settings.llm_max_input_chars:
            raise ModelUnavailable("input_too_large")

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> tuple[dict, CallMeta]:
        if not self.available:
            raise ModelUnavailable("api_key_missing")
        self._check_size(system, user)
        t0 = time.monotonic()
        try:
            resp = self._get_client().messages.create(
                model=self.model,
                max_tokens=max_tokens or self._settings.llm_max_output_tokens * 4,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                **self._fallback_kwargs(),
            )
        except Exception as exc:  # SDK raises typed errors; we only need the class name, never the payload
            log.warning("model call failed: %s", type(exc).__name__)
            raise ModelUnavailable(f"provider_error:{type(exc).__name__}") from None
        latency = int((time.monotonic() - t0) * 1000)
        if getattr(resp, "stop_reason", None) == "refusal":
            raise ModelUnavailable("model_refusal")
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise ModelUnavailable("output_truncated")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ModelUnavailable("invalid_json") from None
        log.info("model call ok task_latency_ms=%s", latency)
        return data, CallMeta(self.name, getattr(resp, "model", self.model), latency)

    def run_tools(self, system: str, messages: list[dict], tools: list[dict], execute, max_steps: int = 4
                  ) -> tuple[str, list[dict], CallMeta]:
        """Manual tool loop limited to ``max_steps``. ``execute(name, input) -> dict`` runs allow-listed tools."""
        if not self.available:
            raise ModelUnavailable("api_key_missing")
        self._check_size(system, json.dumps(messages, ensure_ascii=False))
        client = self._get_client()
        trace: list[dict] = []
        t0 = time.monotonic()
        msgs = list(messages)
        for _ in range(max_steps):
            try:
                resp = client.messages.create(model=self.model, max_tokens=self._settings.llm_max_output_tokens * 4,
                                              system=system, messages=msgs, tools=tools,
                                              output_config={"effort": "low"}, **self._fallback_kwargs())
            except Exception as exc:
                raise ModelUnavailable(f"provider_error:{type(exc).__name__}") from None
            if resp.stop_reason == "refusal":
                raise ModelUnavailable("model_refusal")
            if resp.stop_reason != "tool_use":
                text = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
                return text, trace, CallMeta(self.name, getattr(resp, "model", self.model), int((time.monotonic() - t0) * 1000))
            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                try:
                    out = execute(block.name, dict(block.input))
                    trace.append({"tool": block.name, "input": dict(block.input), "ok": True})
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(out, ensure_ascii=False)[:12000]})
                except Exception as exc:  # tool errors go back to the model, never crash the request
                    trace.append({"tool": block.name, "input": dict(block.input), "ok": False, "error": type(exc).__name__})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": f"error: {getattr(exc, 'code', type(exc).__name__)}"})
            msgs.append({"role": "user", "content": results})
        raise ModelUnavailable("tool_loop_limit")


_provider_override: Provider | None = None


class MisconfiguredProvider(Provider):
    def __init__(self, name: str, problem: str):
        self.name = name
        self.model = get_settings().llm_model
        self.config_error = problem


def get_provider() -> Provider:
    if _provider_override is not None:
        return _provider_override
    s = get_settings()
    if s.llm_provider == "none":
        return Provider()
    problem = llm_config_problem()
    if problem:
        return MisconfiguredProvider(s.llm_provider, problem)
    return AnthropicProvider()


def set_provider_for_tests(p: Provider | None) -> None:
    global _provider_override
    _provider_override = p
