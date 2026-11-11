"""HTTP adapters for concrete providers. Each one translates the neutral contract to its API:

* GeminiProvider          — Google Gemini API (``generateContent``; JSON schema output; function declarations)
* OpenRouterProvider      — OpenRouter (OpenAI-compatible Chat Completions; response_format / tools when the route
                            supports them, otherwise a validated prompted-JSON fallback)
* OpenAIResponsesProvider — OpenAI Responses API (``text.format`` json_schema; function tools)
* AnthropicProvider       — Anthropic Messages API (``output_config.format``; client tools; optional server-side
                            refusal fallback)
* RecordedProvider        — replays pre-recorded outputs stored in the repository (labelled ``recorded_demo``)

Request/response shapes follow the public API documentation; the contract tests replay HTTP fixtures in
tests/fixtures/llm/. Keys are passed only in headers and never logged.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .base import (
    JSON_INSTRUCTION,
    Capabilities,
    LLMError,
    LLMProvider,
    LLMResult,
    ToolExecutor,
    ToolSpec,
    Usage,
    parse_json_text,
)


def _trace_ok(trace, name, args):
    trace.append({"tool": name, "input": args, "ok": True})


def _run_tool(execute: ToolExecutor, name: str, args: dict, trace: list) -> tuple[str, bool]:
    try:
        out = execute(name, args)
        _trace_ok(trace, name, args)
        return json.dumps(out, ensure_ascii=False)[:12000], False
    except Exception as exc:  # tool errors go back to the model, never crash the request
        trace.append({"tool": name, "input": args, "ok": False, "error": getattr(exc, "code", type(exc).__name__)})
        return f"error: {getattr(exc, 'code', type(exc).__name__)}", True


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    name = "gemini"
    data_policy = "may_train"  # free tier: Google may use prompts to improve products; override for paid tier

    def declared_capabilities(self) -> Capabilities:
        return Capabilities(structured_output=True, tool_calling=True, parallel_tools=True, vision_pdf=True,
                            streaming=True, notes=["declared defaults; run probe for model limits"])

    def _h(self) -> dict:
        return {"x-goog-api-key": self._key or "", "content-type": "application/json"}

    def probe(self) -> Capabilities:
        d = self._get(f"{self.base_url}/models/{self.model}", self._h())
        caps = self.declared_capabilities()
        caps.max_context_tokens = d.get("inputTokenLimit")
        caps.max_output_tokens = d.get("outputTokenLimit")
        methods = d.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            caps.structured_output = caps.tool_calling = False
            caps.notes.append("generateContent not supported by this model")
        caps.probed = True
        self.capabilities = caps
        return caps

    def _usage(self, d: dict) -> Usage:
        u = d.get("usageMetadata") or {}
        return Usage(u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))

    @staticmethod
    def _check_block(d: dict) -> list[dict]:
        if (d.get("promptFeedback") or {}).get("blockReason"):
            raise LLMError("refusal", "prompt_blocked")
        cands = d.get("candidates") or []
        if not cands:
            raise LLMError("invalid_output", "no_candidates")
        c = cands[0]
        if c.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"):
            raise LLMError("refusal", c["finishReason"].lower())
        if c.get("finishReason") == "MAX_TOKENS":
            raise LLMError("invalid_output", "output_truncated")
        return (c.get("content") or {}).get("parts") or []

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": self.max_output_tokens, "responseMimeType": "application/json",
                                     "responseJsonSchema": schema}}
        d, ms = self._post(f"{self.base_url}/models/{self.model}:generateContent", self._h(), body)
        parts = self._check_block(d)
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        data = self._validated(parse_json_text(text), schema)
        return LLMResult(self.name, self.model, ms, self._usage(d), text, data)

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        decl = [{"name": t.name, "description": t.description, "parametersJsonSchema": t.parameters} for t in tools]
        contents = [{"role": "user", "parts": [{"text": user}]}]
        trace: list[dict] = []
        usage = Usage()
        t0 = time.monotonic()
        for _ in range(max_steps):
            body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                    "tools": [{"functionDeclarations": decl}],
                    "generationConfig": {"maxOutputTokens": self.max_output_tokens}}
            d, _ = self._post(f"{self.base_url}/models/{self.model}:generateContent", self._h(), body)
            u = self._usage(d)
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
            parts = self._check_block(d)
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                return text, trace, LLMResult(self.name, self.model, int((time.monotonic() - t0) * 1000), usage, text)
            contents.append({"role": "model", "parts": parts})
            responses = []
            for c in calls:
                out, is_err = _run_tool(execute, c.get("name", ""), dict(c.get("args") or {}), trace)
                responses.append({"functionResponse": {"name": c.get("name", ""),
                                                       "response": {"error" if is_err else "result": out}}})
            contents.append({"role": "user", "parts": responses})
        raise LLMError("invalid_output", "tool_loop_limit")


# ---------------------------------------------------------------------------
# OpenAI-compatible Chat Completions (OpenRouter)
# ---------------------------------------------------------------------------


class OpenRouterProvider(LLMProvider):
    name = "openrouter"
    data_policy = "depends_on_route"

    def declared_capabilities(self) -> Capabilities:
        # unknown until probed: OpenRouter routes differ per model
        return Capabilities(structured_output=False, tool_calling=False, notes=["run probe: support depends on the model route"])

    def _h(self) -> dict:
        return {"authorization": f"Bearer {self._key or ''}", "content-type": "application/json",
                "x-title": "OquMap"}

    def probe(self) -> Capabilities:
        d = self._get(f"{self.base_url}/models", self._h())
        m = next((x for x in d.get("data", []) if x.get("id") == self.model), None)
        if m is None:
            raise LLMError("config", "model_not_found_on_openrouter")
        params = set(m.get("supported_parameters") or [])
        mods = set((m.get("architecture") or {}).get("input_modalities") or [])
        caps = Capabilities(structured_output="structured_outputs" in params or "response_format" in params,
                            tool_calling="tools" in params, parallel_tools="parallel_tool_calls" in params,
                            vision_pdf=bool(mods & {"image", "file"}), streaming=True,
                            max_context_tokens=m.get("context_length"),
                            max_output_tokens=(m.get("top_provider") or {}).get("max_completion_tokens"), probed=True)
        self.capabilities = caps
        return caps

    def _call(self, body: dict) -> tuple[dict, int]:
        return self._post(f"{self.base_url}/chat/completions", self._h(), body)

    @staticmethod
    def _usage(d: dict) -> Usage:
        u = d.get("usage") or {}
        return Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

    @staticmethod
    def _choice(d: dict) -> dict:
        ch = (d.get("choices") or [{}])[0]
        if ch.get("finish_reason") == "content_filter":
            raise LLMError("refusal", "content_filter")
        if ch.get("finish_reason") == "length":
            raise LLMError("invalid_output", "output_truncated")
        return ch.get("message") or {}

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        if self.capabilities.structured_output:
            body = {"model": self.model, "max_tokens": self.max_output_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
            mode = "native"
        else:  # validated prompted-JSON fallback for routes without schema support
            body = {"model": self.model, "max_tokens": self.max_output_tokens,
                    "messages": [{"role": "system", "content": system + "\n" + JSON_INSTRUCTION + json.dumps(schema, ensure_ascii=False)},
                                 {"role": "user", "content": user}]}
            mode = "prompted_json"
        d, ms = self._call(body)
        text = self._choice(d).get("content") or ""
        data = self._validated(parse_json_text(text), schema)
        return LLMResult(self.name, self.model, ms, self._usage(d), text, data, mode)

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        if not self.capabilities.tool_calling:
            raise LLMError("capability", "tool_calling_not_supported_by_route")
        fns = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
               for t in tools]
        msgs: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        trace: list[dict] = []
        usage = Usage()
        t0 = time.monotonic()
        for _ in range(max_steps):
            d, _ = self._call({"model": self.model, "max_tokens": self.max_output_tokens, "messages": msgs, "tools": fns,
                               "tool_choice": "auto"})
            u = self._usage(d)
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
            msg = self._choice(d)
            calls = msg.get("tool_calls") or []
            if not calls:
                text = (msg.get("content") or "").strip()
                return text, trace, LLMResult(self.name, self.model, int((time.monotonic() - t0) * 1000), usage, text)
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                fn = c.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                out, _ = _run_tool(execute, fn.get("name", ""), args, trace)
                msgs.append({"role": "tool", "tool_call_id": c.get("id"), "content": out})
        raise LLMError("invalid_output", "tool_loop_limit")


# ---------------------------------------------------------------------------
# OpenAI Responses API
# ---------------------------------------------------------------------------


class OpenAIResponsesProvider(LLMProvider):
    name = "openai"
    data_policy = "api_default"

    def declared_capabilities(self) -> Capabilities:
        return Capabilities(structured_output=True, tool_calling=True, parallel_tools=True, vision_pdf=True, streaming=True)

    def _h(self) -> dict:
        return {"authorization": f"Bearer {self._key or ''}", "content-type": "application/json"}

    def probe(self) -> Capabilities:
        self._get(f"{self.base_url}/models/{self.model}", self._h())  # existence + key check
        self.capabilities.probed = True
        return self.capabilities

    @staticmethod
    def _usage(d: dict) -> Usage:
        u = d.get("usage") or {}
        return Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))

    @staticmethod
    def _check(d: dict) -> list[dict]:
        if d.get("status") == "incomplete":
            raise LLMError("invalid_output", ((d.get("incomplete_details") or {}).get("reason") or "incomplete"))
        out = d.get("output") or []
        for item in out:
            for c in item.get("content") or []:
                if c.get("type") == "refusal":
                    raise LLMError("refusal", "model_refusal")
        return out

    @staticmethod
    def _text(out: list[dict]) -> str:
        return "".join(c.get("text", "") for item in out if item.get("type") == "message"
                       for c in item.get("content") or [] if c.get("type") == "output_text")

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        body = {"model": self.model, "instructions": system, "input": user, "max_output_tokens": self.max_output_tokens,
                "store": False, "text": {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}}
        d, ms = self._post(f"{self.base_url}/responses", self._h(), body)
        text = self._text(self._check(d))
        return LLMResult(self.name, self.model, ms, self._usage(d), text, self._validated(parse_json_text(text), schema))

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        fns = [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters, "strict": True}
               for t in tools]
        items: list[dict] = [{"role": "user", "content": user}]
        trace: list[dict] = []
        usage = Usage()
        t0 = time.monotonic()
        for _ in range(max_steps):
            d, _ = self._post(f"{self.base_url}/responses", self._h(),
                              {"model": self.model, "instructions": system, "input": items, "tools": fns, "store": False,
                               "max_output_tokens": self.max_output_tokens})
            u = self._usage(d)
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
            out = self._check(d)
            calls = [o for o in out if o.get("type") == "function_call"]
            if not calls:
                text = self._text(out).strip()
                return text, trace, LLMResult(self.name, self.model, int((time.monotonic() - t0) * 1000), usage, text)
            items += out
            for c in calls:
                try:
                    args = json.loads(c.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                res, _ = _run_tool(execute, c.get("name", ""), args, trace)
                items.append({"type": "function_call_output", "call_id": c.get("call_id"), "output": res})
        raise LLMError("invalid_output", "tool_loop_limit")


# ---------------------------------------------------------------------------
# Anthropic Messages API
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    data_policy = "api_default"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, *a, refusal_fallback: bool = True, **kw):
        super().__init__(*a, **kw)
        self.refusal_fallback = refusal_fallback

    def declared_capabilities(self) -> Capabilities:
        return Capabilities(structured_output=True, tool_calling=True, parallel_tools=True, vision_pdf=True, streaming=True)

    def _h(self) -> dict:
        h = {"x-api-key": self._key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
        if self.refusal_fallback:
            h["anthropic-beta"] = self.FALLBACK_BETA
        return h

    def _body(self, **kw) -> dict:
        body = {"model": self.model, "max_tokens": self.max_output_tokens, **kw}
        if self.refusal_fallback:
            body["fallbacks"] = "default"
        return body

    def probe(self) -> Capabilities:
        d = self._get(f"{self.base_url}/v1/models/{self.model}", self._h())
        self.capabilities.max_context_tokens = d.get("max_input_tokens")
        self.capabilities.max_output_tokens = d.get("max_tokens")
        self.capabilities.probed = True
        return self.capabilities

    @staticmethod
    def _usage(d: dict) -> Usage:
        u = d.get("usage") or {}
        return Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))

    @staticmethod
    def _check(d: dict) -> list[dict]:
        if d.get("stop_reason") == "refusal":
            raise LLMError("refusal", "model_refusal")
        if d.get("stop_reason") == "max_tokens":
            raise LLMError("invalid_output", "output_truncated")
        return d.get("content") or []

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        body = self._body(system=system, messages=[{"role": "user", "content": user}],
                          output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
        d, ms = self._post(f"{self.base_url}/v1/messages", self._h(), body)
        text = "".join(b.get("text", "") for b in self._check(d) if b.get("type") == "text")
        return LLMResult(self.name, d.get("model", self.model), ms, self._usage(d), text,
                         self._validated(parse_json_text(text), schema))

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        specs = [{"name": t.name, "description": t.description, "input_schema": t.parameters, "strict": True} for t in tools]
        msgs: list[dict] = [{"role": "user", "content": user}]
        trace: list[dict] = []
        usage = Usage()
        t0 = time.monotonic()
        for _ in range(max_steps):
            d, _ = self._post(f"{self.base_url}/v1/messages", self._h(),
                              self._body(system=system, messages=msgs, tools=specs, output_config={"effort": "low"}))
            u = self._usage(d)
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
            content = self._check(d)
            if d.get("stop_reason") != "tool_use":
                text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                return text, trace, LLMResult(self.name, d.get("model", self.model), int((time.monotonic() - t0) * 1000), usage, text)
            msgs.append({"role": "assistant", "content": content})
            results = []
            for b in content:
                if b.get("type") != "tool_use":
                    continue
                out, is_err = _run_tool(execute, b.get("name", ""), dict(b.get("input") or {}), trace)
                r = {"type": "tool_result", "tool_use_id": b.get("id"), "content": out}
                if is_err:
                    r["is_error"] = True
                results.append(r)
            msgs.append({"role": "user", "content": results})
        raise LLMError("invalid_output", "tool_loop_limit")


# ---------------------------------------------------------------------------
# Recorded replay
# ---------------------------------------------------------------------------


class RecordedProvider(LLMProvider):
    """Replays outputs recorded in data/demo/recorded/llm/<key>.json (key = task + input hash). Missing key →
    LLMError('capability'), and the caller falls back to template mode. Results are labelled recorded_demo."""

    name = "recorded"
    data_policy = "none"

    def __init__(self, directory: Path, **kw):
        super().__init__("recorded", **kw)
        self.dir = directory

    def declared_capabilities(self) -> Capabilities:
        return Capabilities(structured_output=True, tool_calling=False, notes=["replay of recorded outputs"])

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        import hashlib

        key = hashlib.sha256((name + "\n" + user).encode()).hexdigest()[:24]
        p = self.dir / f"{name}-{key}.json"
        if not p.exists():
            raise LLMError("capability", "no_recording")
        data = json.loads(p.read_text(encoding="utf-8"))
        return LLMResult(self.name, data.get("recorded_model", "recorded"), 0, Usage(), "", self._validated(data["output"], schema))

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        raise LLMError("capability", "recorded_provider_has_no_tool_loop")


ToolSpec = ToolSpec  # re-export
