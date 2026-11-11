"""Live LLM configuration diagnostics, gating by role/quota, refusal fallback parameters and secret hygiene."""

import logging
from types import SimpleNamespace

from conftest import login
from pydantic import SecretStr

from oqumap.ai import provider as prov
from oqumap.ai.provider import AnthropicProvider, CallMeta, Provider, llm_config_problem
from oqumap.config import get_settings

SECRET = "sk-ant-TEST-SECRET-0123456789"


def test_default_model_is_current_sonnet_and_configurable(monkeypatch):
    s = get_settings()
    assert s.llm_model == "claude-sonnet-5-5"
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "llm_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_config_problem() == "api_key_missing"
    monkeypatch.setattr(s, "llm_api_key", SecretStr(SECRET))
    monkeypatch.setattr(s, "llm_model", "")
    assert llm_config_problem() == "invalid_model_id"
    monkeypatch.setattr(s, "llm_model", "gpt-4o")
    assert llm_config_problem() == "invalid_model_id"
    monkeypatch.setattr(s, "llm_model", "claude-opus-5-5")
    assert llm_config_problem() is None
    monkeypatch.setattr(s, "llm_provider", "openai")
    assert llm_config_problem() == "unknown_provider"


def _comparison(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    eds = {e["code"]: e["id"] for e in curriculum["editions"]}
    return client.post("/api/v1/comparisons", json={"dataset_id": datasets["base"]["id"], "topic_id": t3,
                                                    "edition_a_id": eds["EDA"], "edition_b_id": eds["EDB"]}, headers=H).json()


def test_misconfigured_live_provider_degrades_with_diagnostic_not_500(client, H, datasets, curriculum, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "llm_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    comp = _comparison(client, H, datasets, curriculum)
    r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H)
    assert r.status_code == 200
    assert r.json()["mode"] == "template" and r.json()["fallback_reason"] == "llm_misconfigured:api_key_missing"
    st = client.get("/api/v1/ai/status", headers=H).json()
    assert st["config_error"] == "api_key_missing" and st["live_available"] is False
    ready = client.get("/health/ready").json()
    assert ready["checks"]["llm"] == "misconfigured:api_key_missing"


class Fake(Provider):
    name, model, calls = "fake", "fake-model", 0

    @property
    def available(self):
        return True

    def complete_json(self, system, user, schema, max_tokens=None):
        Fake.calls += 1
        return {"text": "Разница не определена.", "limitations": []}, CallMeta("fake", "fake-model", 1)


def test_live_calls_are_limited_by_role_and_quota(client, H, datasets, curriculum, monkeypatch):
    comp = _comparison(client, H, datasets, curriculum)
    aid = comp["context"]["analysis_id"]
    prov.set_provider_for_tests(Fake())
    Fake.calls = 0
    try:
        V = login(client, "viewer")
        r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=V).json()
        assert r["fallback_reason"] == "live_not_allowed_for_role" and Fake.calls == 0
        M = login(client)
        from oqumap import db
        from oqumap.services import ratelimit

        me = client.get("/api/v1/auth/me", headers=M).json()
        with db.session_factory()() as ss:
            used = ratelimit.peek(ss, "llm_user_hour", me["id"], 3600)
        monkeypatch.setattr(get_settings(), "llm_live_per_user_per_hour", used + 1)  # exactly one call left
        monkeypatch.setattr(get_settings(), "llm_live_per_org_per_day", 100000)
        r1 = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=M).json()
        r2 = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=M).json()
        assert r1["mode"] == "live_model" and r2["fallback_reason"] == "live_quota_exceeded" and Fake.calls == 1
    finally:
        prov.set_provider_for_tests(None)


def test_adapter_sends_refusal_fallback_and_never_leaks_the_key(client, H, datasets, curriculum, monkeypatch, caplog):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "llm_api_key", SecretStr(SECRET))
    seen = {}

    class Msgs:
        def create(self, **kw):
            seen.update(kw)
            raise RuntimeError(f"upstream failure for key {SECRET}")  # hostile error text containing the key

    fake = AnthropicProvider(client=SimpleNamespace(messages=Msgs()))
    monkeypatch.setattr(prov, "get_provider", lambda: fake)
    import oqumap.ai.tasks as tasks

    monkeypatch.setattr(tasks, "get_provider", lambda: fake)
    comp = _comparison(client, H, datasets, curriculum)
    caplog.set_level(logging.DEBUG)
    r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["fallback_reason"] == "provider_error:RuntimeError"
    assert seen["extra_headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert seen["extra_body"] == {"fallbacks": "default"} and seen["model"] == "claude-sonnet-5-5"
    for text in (r.text, client.get("/api/v1/ai/status", headers=H).text, client.get("/api/v1/config").text, caplog.text):
        assert SECRET not in text
    from sqlalchemy import select

    from oqumap import db
    from oqumap import models as m

    with db.session_factory()() as ss:
        for g in ss.scalars(select(m.AIGeneration)):
            assert SECRET not in str(g.context) + str(g.output) + str(g.verification) + str(g.fallback_reason)
    assert SECRET not in repr(get_settings())
