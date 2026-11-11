"""Contract tests for every provider adapter, replaying recorded HTTP fixtures through httpx.MockTransport.

Checks request shape (endpoint, auth header, schema/tool fields), response normalisation, server-side schema
validation, tool loop, error classification (retry only retryable), refusal handling and capability probing."""

import json
from pathlib import Path

import httpx
import pytest

from oqumap.ai.llm.adapters import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIResponsesProvider,
    OpenRouterProvider,
    RecordedProvider,
)
from oqumap.ai.llm.base import LLMError, ToolSpec, validate_schema

FX = Path(__file__).parent / "fixtures" / "llm"
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}, "limitations": {"type": "array", "items": {"type": "string"}}},
          "required": ["text", "limitations"], "additionalProperties": False}
TOOLS = [ToolSpec("get_overview", "Сводка", {"type": "object", "properties": {}, "required": [], "additionalProperties": False})]
KEY = "test-key-should-only-appear-in-auth-header"


def fx(name):
    return json.loads((FX / f"{name}.json").read_text(encoding="utf-8"))


class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body, headers={"retry-after": "0"} if status == 429 else {})


def make(cls, rec, model, base, **kw):
    return cls(model, api_key=KEY, base_url=base, transport=httpx.MockTransport(rec), max_retries=2, **kw)


CASES = [
    (GeminiProvider, "gemini", "gemini-2.5-flash", "https://g.test/v1beta", "x-goog-api-key",
     lambda r: r.url.path.endswith(":generateContent")),
    (OpenRouterProvider, "openrouter", "google/gemini-2.5-flash", "https://or.test/api/v1", "authorization",
     lambda r: r.url.path.endswith("/chat/completions")),
    (OpenAIResponsesProvider, "openai", "gpt-5-mini", "https://oa.test/v1", "authorization",
     lambda r: r.url.path.endswith("/responses")),
    (AnthropicProvider, "anthropic", "claude-sonnet-5-5", "https://an.test", "x-api-key",
     lambda r: r.url.path.endswith("/v1/messages")),
]


@pytest.mark.parametrize("cls,name,model,base,auth,endpoint_ok", CASES, ids=[c[1] for c in CASES])
def test_structured_output_contract(cls, name, model, base, auth, endpoint_ok):
    f = fx(name)
    rec = Recorder([(200, f["structured"])])
    p = make(cls, rec, model, base)
    if name == "openrouter":
        p.capabilities.structured_output = True
    r = p.structured("sys", "user", SCHEMA, "explain_comparison")
    assert r.data == {"text": "Разница не определена.", "limitations": ["Наблюдательные данные."]}
    assert r.usage.input_tokens == 120 and r.usage.output_tokens == 30 and r.provider == name
    req = rec.requests[0]
    assert endpoint_ok(req) and KEY in req.headers[auth]
    body = json.loads(req.content)
    assert KEY not in req.content.decode()  # key only in the header
    if name == "gemini":
        assert body["generationConfig"]["responseJsonSchema"] == SCHEMA
    elif name == "openrouter":
        assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    elif name == "openai":
        assert body["text"]["format"]["type"] == "json_schema" and body["store"] is False
    else:
        assert body["output_config"]["format"]["schema"] == SCHEMA
        assert body["fallbacks"] == "default" and req.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"


@pytest.mark.parametrize("cls,name,model,base,auth,endpoint_ok", CASES, ids=[c[1] for c in CASES])
def test_tool_loop_contract(cls, name, model, base, auth, endpoint_ok):
    f = fx(name)
    rec = Recorder([(200, f["tool_1"]), (200, f["tool_2"])])
    p = make(cls, rec, model, base)
    if name == "openrouter":
        p.capabilities.tool_calling = True
    calls = []
    text, trace, r = p.tool_loop("sys", "Какая тема приоритетная?", TOOLS, lambda n, a: calls.append(n) or {"ok": 1})
    assert text == "Приоритетная тема — T3." and calls == ["get_overview"] and trace[0]["ok"]
    assert r.usage.total == 100 + 10 + 150 + 12
    second = json.loads(rec.requests[1].content)
    dumped = json.dumps(second, ensure_ascii=False)
    assert '"ok": 1' in dumped or '\\"ok\\": 1' in dumped  # tool result sent back to the model


@pytest.mark.parametrize("cls,name,model,base,auth,endpoint_ok", CASES, ids=[c[1] for c in CASES])
def test_errors_are_classified_and_only_retryable_ones_retried(cls, name, model, base, auth, endpoint_ok):
    f = fx(name)
    rec = Recorder([(429, {"error": "slow down"}), (200, f["structured"])])
    p = make(cls, rec, model, base)
    p.capabilities.structured_output = True
    assert p.structured("s", "u", SCHEMA).data["text"]
    assert len(rec.requests) == 2  # one retry after 429
    rec = Recorder([(401, {"error": "bad key"}), (200, f["structured"])])
    p = make(cls, rec, model, base)
    with pytest.raises(LLMError) as e:
        p.structured("s", "u", SCHEMA)
    assert e.value.kind == "auth" and not e.value.retryable and len(rec.requests) == 1
    rec = Recorder([(200, f["refusal"])])
    p = make(cls, rec, model, base)
    p.capabilities.structured_output = True
    with pytest.raises(LLMError) as e:
        p.structured("s", "u", SCHEMA)
    assert e.value.kind == "refusal"


def test_invalid_structured_output_is_rejected_by_server_validation():
    bad = fx("openai")["structured"]
    bad = json.loads(json.dumps(bad).replace("limitations", "extra_field"))
    rec = Recorder([(200, bad)])
    p = make(OpenAIResponsesProvider, rec, "gpt-5-mini", "https://oa.test/v1")
    with pytest.raises(LLMError) as e:
        p.structured("s", "u", SCHEMA)
    assert e.value.kind == "invalid_output"


def test_openrouter_capability_probe_and_validated_fallback():
    f = fx("openrouter")
    rec = Recorder([(200, f["models"])])
    p = make(OpenRouterProvider, rec, "vendor/plain-model", "https://or.test/api/v1")
    caps = p.probe()
    assert caps.probed and caps.structured_output is False and caps.tool_calling is False and caps.max_context_tokens == 8192
    # without schema support the adapter asks for JSON in the prompt and validates it on the server
    rec2 = Recorder([(200, f["structured"])])
    p._transport = httpx.MockTransport(rec2)
    r = p.structured("sys", "u", SCHEMA)
    assert r.structured_mode == "prompted_json" and "response_format" not in json.loads(rec2.requests[0].content)
    with pytest.raises(LLMError) as e:
        p.tool_loop("s", "u", TOOLS, lambda *a: {})
    assert e.value.kind == "capability"
    rec3 = Recorder([(200, f["models"])])
    p3 = make(OpenRouterProvider, rec3, "google/gemini-2.5-flash", "https://or.test/api/v1")
    assert p3.probe().tool_calling and p3.probe if True else None


def test_gemini_and_anthropic_probe():
    rec = Recorder([(200, fx("gemini")["model"])])
    caps = make(GeminiProvider, rec, "gemini-2.5-flash", "https://g.test/v1beta").probe()
    assert caps.max_context_tokens == 1048576 and caps.structured_output
    rec = Recorder([(200, fx("anthropic")["model"])])
    caps = make(AnthropicProvider, rec, "claude-sonnet-5-5", "https://an.test").probe()
    assert caps.max_output_tokens == 128000


def test_recorded_provider_replays_and_validates(tmp_path):
    import hashlib

    key = hashlib.sha256(("explain\n" + "u").encode()).hexdigest()[:24]
    (tmp_path / f"explain-{key}.json").write_text(json.dumps({"output": {"text": "x", "limitations": []}}), encoding="utf-8")
    p = RecordedProvider(tmp_path)
    assert p.structured("s", "u", SCHEMA, "explain").data["text"] == "x"
    with pytest.raises(LLMError):
        p.structured("s", "other", SCHEMA, "explain")


def test_schema_validator():
    assert validate_schema({"text": "a", "limitations": []}, SCHEMA) == []
    assert validate_schema({"text": 1}, SCHEMA)
