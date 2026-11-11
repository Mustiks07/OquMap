"""Provider-neutral LLM contract used by all OquMap AI code.

Business logic (prompts, agent roles, tool schemas) depends only on this module: normalised structured output,
client-executed typed tools, usage/latency and classified errors. Provider adapters translate to their HTTP APIs.
The server always validates outputs against the JSON Schema itself; provider-native structured output is an
optimisation, never the only guarantee.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

RETRYABLE = {"rate_limit", "timeout", "server", "network"}


class LLMError(Exception):
    """kind: auth | rate_limit | timeout | server | network | bad_request | refusal | invalid_output |
    capability | config | quota | circuit_open | policy"""

    def __init__(self, kind: str, detail: str = "", status: int | None = None, retry_after: float | None = None):
        super().__init__(f"{kind}:{detail}"[:200])
        self.kind = kind
        self.detail = detail[:200]
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    @property
    def reason(self) -> str:  # compatibility with the previous ModelUnavailable
        return self.kind if not self.detail else f"{self.kind}:{self.detail}"


@dataclass
class Capabilities:
    structured_output: bool = False
    tool_calling: bool = False
    parallel_tools: bool = False
    vision_pdf: bool = False
    streaming: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None
    probed: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResult:
    provider: str
    model: str
    latency_ms: int
    usage: Usage
    text: str = ""
    data: dict | None = None
    structured_mode: str = "native"  # native | prompted_json (validated fallback)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)


ToolExecutor = Callable[[str, dict], dict]


# ---------------------------------------------------------------------------
# Server-side JSON Schema validation (subset used by OquMap schemas)
# ---------------------------------------------------------------------------


def validate_schema(data: Any, schema: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(data, dict):
            return [f"{path}: expected object"]
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in data:
                errs.append(f"{path}.{r}: required")
        if schema.get("additionalProperties") is False:
            for k in data:
                if k not in props:
                    errs.append(f"{path}.{k}: not allowed")
        for k, sub in props.items():
            if k in data:
                errs += validate_schema(data[k], sub, f"{path}.{k}")
    elif t == "array":
        if not isinstance(data, list):
            return [f"{path}: expected array"]
        for i, v in enumerate(data):
            errs += validate_schema(v, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(data, str):
            errs.append(f"{path}: expected string")
        elif "enum" in schema and data not in schema["enum"]:
            errs.append(f"{path}: not in enum")
    elif t == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            errs.append(f"{path}: expected number")
    elif t == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            errs.append(f"{path}: expected integer")
    elif t == "boolean":
        if not isinstance(data, bool):
            errs.append(f"{path}: expected boolean")
    return errs


def parse_json_text(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise LLMError("invalid_output", "no_json_object")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        raise LLMError("invalid_output", "json_decode") from None


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------


class LLMProvider:
    name = "none"
    data_policy = "none"  # no_training | may_train | depends_on_route | api_default | none

    def __init__(self, model: str = "", *, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 30.0, max_retries: int = 2, transport: httpx.BaseTransport | None = None,
                 max_output_tokens: int = 4000):
        self.model = model
        self._key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, min(max_retries, 4))
        self.max_output_tokens = max_output_tokens
        self._transport = transport
        self.capabilities = self.declared_capabilities()

    # -- to implement ---------------------------------------------------------------------------
    def declared_capabilities(self) -> Capabilities:
        return Capabilities()

    def probe(self) -> Capabilities:
        """Ask the provider about the configured model (limits / supported features). Defaults to declared."""
        return self.capabilities

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        raise LLMError("config", "provider_not_configured")

    def tool_loop(self, system: str, user: str, tools: list[ToolSpec], execute: ToolExecutor,
                  max_steps: int = 4) -> tuple[str, list[dict], LLMResult]:
        raise LLMError("capability", "tool_calling_not_supported")

    # -- shared HTTP ----------------------------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self._transport)

    def _post(self, url: str, headers: dict, body: dict) -> tuple[dict, int]:
        """POST with classified errors and bounded retries for retryable failures only."""
        attempt = 0
        while True:
            t0 = time.monotonic()
            try:
                with self._client() as c:
                    resp = c.post(url, headers=headers, json=body)
            except httpx.TimeoutException:
                err = LLMError("timeout", "request_timeout")
            except httpx.HTTPError as exc:
                err = LLMError("network", type(exc).__name__)
            else:
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code < 400:
                    try:
                        return resp.json(), latency
                    except ValueError:
                        raise LLMError("invalid_output", "non_json_response", resp.status_code) from None
                err = classify_http(resp)
            if not err.retryable or attempt >= self.max_retries:
                raise err
            attempt += 1
            wait = err.retry_after if err.retry_after is not None else 0.5 * (2 ** (attempt - 1))
            time.sleep(min(wait, 8.0) + random.uniform(0, 0.2))

    def _get(self, url: str, headers: dict) -> dict:
        try:
            with self._client() as c:
                resp = c.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError("network", type(exc).__name__) from None
        if resp.status_code >= 400:
            raise classify_http(resp)
        return resp.json()

    def _validated(self, data: dict, schema: dict) -> dict:
        errs = validate_schema(data, schema)
        if errs:
            raise LLMError("invalid_output", "schema:" + ";".join(errs[:3]))
        return data


def classify_http(resp: httpx.Response) -> LLMError:
    s = resp.status_code
    retry_after = None
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            retry_after = float(ra)
        except ValueError:
            retry_after = None
    if s in (401, 403):
        return LLMError("auth", f"http_{s}", s)
    if s == 429:
        return LLMError("rate_limit", "http_429", s, retry_after)
    if s in (408, 504):
        return LLMError("timeout", f"http_{s}", s)
    if s >= 500:
        return LLMError("server", f"http_{s}", s, retry_after)
    return LLMError("bad_request", f"http_{s}", s)


JSON_INSTRUCTION = ("Ответ — строго один JSON-объект, соответствующий схеме, без пояснений и без markdown. Схема: ")
