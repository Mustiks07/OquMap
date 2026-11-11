"""Live LLM configuration diagnostics, gating (role/quota/cost/policy), explicit fallbacks and secret hygiene."""

import json
import logging

import httpx
from conftest import login
from pydantic import SecretStr

from oqumap.ai import provider as prov
from oqumap.ai.provider import CallMeta, Provider, build_adapter, get_provider, llm_config_problem
from oqumap.config import get_settings

SECRET = "sk-TEST-SECRET-0123456789abcdef"


def test_config_diagnostics_per_provider(monkeypatch):
    s = get_settings()
    assert s.llm_provider == "none" and llm_config_problem() is None
    for provider, model, key_attr in (("gemini", "gemini-2.5-flash", "gemini_api_key"),
                                      ("openrouter", "google/gemini-2.5-flash", "openrouter_api_key"),
                                      ("openai", "gpt-5-mini", "openai_api_key"),
                                      ("anthropic", "claude-sonnet-5-5", "anthropic_api_key")):
        monkeypatch.setattr(s, "llm_provider", provider)
        monkeypatch.setattr(s, "llm_model", model)
        monkeypatch.setattr(s, key_attr, None)
        assert llm_config_problem() == "api_key_missing", provider
        monkeypatch.setattr(s, key_attr, SecretStr(SECRET))
        assert llm_config_problem() is None, provider
        monkeypatch.setattr(s, "llm_model", "")
        assert llm_config_problem() == "invalid_model_id", provider
        monkeypatch.setattr(s, "llm_model", model)
    # a key of another provider is not accepted (no shared ambiguous key)
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", None)
    assert llm_config_problem() == "api_key_missing"
    monkeypatch.setattr(s, "llm_provider", "mystery")
    assert llm_config_problem() == "unknown_provider"
    # cross-provider fallback requires explicit permission
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "llm_fallbacks", ["anthropic:claude-sonnet-5-5"])
    assert llm_config_problem() == "cross_provider_fallback_not_allowed"
    monkeypatch.setattr(s, "llm_allow_cross_provider_fallback", True)
    assert llm_config_problem() is None


def test_gemini_free_tier_is_marked_may_train(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", SecretStr(SECRET))
    assert build_adapter("gemini", "gemini-2.5-flash").data_policy == "may_train"
    monkeypatch.setattr(s, "gemini_paid_tier", True)
    assert build_adapter("gemini", "gemini-2.5-flash").data_policy == "no_training"


def _comparison(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    eds = {e["code"]: e["id"] for e in curriculum["editions"]}
    return client.post("/api/v1/comparisons", json={"dataset_id": datasets["base"]["id"], "topic_id": t3,
                                                    "edition_a_id": eds["EDA"], "edition_b_id": eds["EDB"]}, headers=H).json()


def test_misconfigured_live_provider_degrades_with_diagnostic_not_500(client, H, datasets, curriculum, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "llm_model", "gemini-2.5-flash")
    monkeypatch.setattr(s, "gemini_api_key", None)
    comp = _comparison(client, H, datasets, curriculum)
    r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H)
    assert r.status_code == 200
    assert r.json()["mode"] == "template" and r.json()["fallback_reason"] == "llm_misconfigured:api_key_missing"
    st = client.get("/api/v1/ai/status", headers=H).json()
    assert st["config_error"] == "api_key_missing" and st["live_available"] is False and st["mode"] == "template"
    assert client.get("/health/ready").json()["checks"]["llm"] == "misconfigured:api_key_missing"


class Fake(Provider):
    name, model, calls, data_policy = "fake", "fake-model", 0, "api_default"

    @property
    def available(self):
        return True

    def complete_json(self, system, user, schema, name="result", **kw):
        Fake.calls += 1
        return {"text": "Разница не определена.", "limitations": []}, CallMeta("fake", "fake-model", 1, 500)


def test_live_calls_are_limited_by_role_quota_and_cost(client, H, datasets, curriculum, monkeypatch):
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
            tokens = ratelimit.peek(ss, "llm_tokens_org_day", me["org_id"], 86400)
        monkeypatch.setattr(get_settings(), "llm_live_per_user_per_hour", used + 1)
        monkeypatch.setattr(get_settings(), "llm_live_per_org_per_day", 100000)
        r1 = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=M).json()
        r2 = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=M).json()
        assert r1["mode"] == "live_model" and r2["fallback_reason"] == "live_quota_exceeded" and Fake.calls == 1
        monkeypatch.setattr(get_settings(), "llm_live_per_user_per_hour", 100000)
        monkeypatch.setattr(get_settings(), "llm_max_tokens_per_org_per_day", tokens + 500)  # used up by r1
        r3 = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=M).json()
        assert r3["fallback_reason"] == "live_cost_ceiling" and Fake.calls == 1
    finally:
        prov.set_provider_for_tests(None)


def test_real_data_is_never_sent_to_a_may_train_provider(monkeypatch):
    from oqumap.ai.gate import LiveGate

    s = get_settings()

    class _S:  # minimal session stub: quotas are not reached in this check
        pass

    g = LiveGate(_S(), "org", "user", ["methodist"], False, False)
    monkeypatch.setattr(s, "llm_real_data_allowed", True)
    assert g.acquire(synthetic=False, data_policy="may_train") == "provider_policy_blocks_real_data"
    monkeypatch.setattr(s, "llm_real_data_allowed", False)
    assert g.acquire(synthetic=False, data_policy="api_default") == "provider_policy_blocks_real_data"


def test_key_never_leaks_through_api_logs_or_records(client, H, datasets, curriculum, monkeypatch, caplog):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "llm_model", "gpt-5-mini")
    monkeypatch.setattr(s, "openai_api_key", SecretStr(SECRET))
    monkeypatch.setattr(s, "llm_max_retries", 0)
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(500, json={"error": {"message": f"upstream echo of {req.headers.get('authorization')}"}})

    chain = get_provider()
    chain.chain[0]._transport = httpx.MockTransport(handler)
    import oqumap.ai.tasks as tasks

    monkeypatch.setattr(tasks, "get_provider", lambda: chain)
    comp = _comparison(client, H, datasets, curriculum)
    caplog.set_level(logging.DEBUG)
    r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["fallback_reason"] == "server:http_500" and seen
    assert SECRET in seen[0].headers["authorization"]  # sent only to the provider
    for text in (r.text, client.get("/api/v1/ai/status", headers=H).text, client.get("/api/v1/config").text, caplog.text):
        assert SECRET not in text
    from sqlalchemy import select

    from oqumap import db
    from oqumap import models as m

    with db.session_factory()() as ss:
        for g in ss.scalars(select(m.AIGeneration)):
            assert SECRET not in json.dumps([g.context, g.output, g.verification, g.fallback_reason], ensure_ascii=False)
    assert SECRET not in repr(get_settings())


def test_explicit_cross_provider_fallback_is_audited(client, H, datasets, curriculum, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "llm_model", "gpt-5-mini")
    monkeypatch.setattr(s, "openai_api_key", SecretStr(SECRET))
    monkeypatch.setattr(s, "anthropic_api_key", SecretStr(SECRET))
    monkeypatch.setattr(s, "llm_fallbacks", ["anthropic:claude-sonnet-5-5"])
    monkeypatch.setattr(s, "llm_allow_cross_provider_fallback", True)
    monkeypatch.setattr(s, "llm_max_retries", 0)
    from pathlib import Path

    fx = json.loads((Path(__file__).parent / "fixtures/llm/anthropic.json").read_text(encoding="utf-8"))
    comp = _comparison(client, H, datasets, curriculum)
    raw = comp["result"]["adjusted"]["difference"]
    ok_body = dict(fx["structured"])
    ok_body["content"] = [{"type": "text", "text": json.dumps({"text": f"Разница {100 * raw:.1f} п.п.", "limitations": []}, ensure_ascii=False)}]
    chain = get_provider()
    chain.chain[0]._transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    chain.chain[1]._transport = httpx.MockTransport(lambda r: httpx.Response(200, json=ok_body))
    import oqumap.ai.tasks as tasks

    monkeypatch.setattr(tasks, "get_provider", lambda: chain)
    r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H).json()
    assert r["mode"] == "live_model" and r["provider"] == "anthropic"
    from sqlalchemy import select

    from oqumap import db
    from oqumap import models as m

    with db.session_factory()() as ss:
        ev = ss.scalars(select(m.AuditLog).where(m.AuditLog.action == "llm.fallback_provider")).all()
    assert ev and ev[-1].details == {"primary": "openai", "used": "anthropic"}
