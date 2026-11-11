"""Safe recording of a real live-model run: ID normalisation and replay across tenants, secret scrubbing,
refusals, and the full probe → council → manifest pipeline with a scripted adapter writing to a temp dir only.
No recording is created in the repository by these tests."""

import json

import pytest
from pydantic import SecretStr

from oqumap import db
from oqumap.ai.llm.base import Capabilities, LLMError, LLMProvider, LLMResult, Usage
from oqumap.ai.llm.recording import RecordingProvider, normalize, replay, scrub
from oqumap.config import get_settings

A = "11111111-2222-3333-4444-555555555555"
B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Scripted(LLMProvider):
    """Test double standing in for a provider: answers from the request, cites only IDs it was given."""

    name = "scripted"
    data_policy = "api_default"

    def __init__(self, leak: str | None = None):
        super().__init__("scripted-1")
        self.leak = leak

    def probe(self):
        return Capabilities(structured_output=True, probed=True)

    def structured(self, system, user, schema, name="result"):
        req = json.loads(user)
        ids = req.get("allowed_evidence_ids", [])[:2]
        text = "Слабая цель требует внимания" + (f" {self.leak}" if self.leak else "")
        data = {"claims": [{"kind": "level", "text": text, "evidence_ids": ids}]} if "claims" in json.dumps(schema) else \
            {"text": "ok", "limitations": []}
        return LLMResult(self.name, self.model, 12, Usage(100, 20), json.dumps(data), self._validated(data, schema))


def test_ids_are_normalised_and_mapped_back_for_another_tenant(tmp_path):
    rec = RecordingProvider(Scripted(), tmp_path, [])
    schema = {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "object"}}}, "required": ["claims"]}
    rec.structured("s", json.dumps({"allowed_evidence_ids": [f"topic:{A}", f"objective:{B}"]}), schema, "council_analyst")
    stored = json.loads(next(tmp_path.glob("council_analyst-*.json")).read_text())
    assert A not in json.dumps(stored) and stored["output"]["claims"][0]["evidence_ids"] == ["topic:<ID1>", "objective:<ID2>"]
    # the same request in a disposable tenant has different IDs → same key, IDs mapped to the tenant's
    C, D = "99999999-8888-7777-6666-555555555555", "12345678-1234-1234-1234-123456789abc"
    out, model = replay(tmp_path, "council_analyst", json.dumps({"allowed_evidence_ids": [f"topic:{C}", f"objective:{D}"]}))
    assert out["claims"][0]["evidence_ids"] == [f"topic:{C}", f"objective:{D}"] and model == "scripted-1"
    assert replay(tmp_path, "council_analyst", json.dumps({"allowed_evidence_ids": ["other"]})) is None
    assert normalize(f"x {A} y {A} {B}")[0] == "x <ID1> y <ID1> <ID2>"


def test_scrub_refuses_secrets_credentials_and_emails():
    for bad, secrets in (({"t": "abc SECRET-VALUE-123"}, ["SECRET-VALUE-123"]), ({"t": "Bearer abcdefghijklmnop"}, []),
                         ({"t": "sk-abcdefghijklmnopqrstu"}, []), ({"t": "AIzaSyA1234567890abcdefghij"}, []), ({"t": "a.b@example.com"}, [])):
        with pytest.raises(LLMError):
            scrub(bad, secrets)
    scrub({"t": "Тема T3: 47,1%"}, ["SECRET-VALUE-123"])


def test_record_pipeline_with_scripted_adapter(client, H, tmp_path, monkeypatch):
    from oqumap.ai.record_live import record

    out = tmp_path / "llm"
    with db.session_factory()() as s:
        man = record(s, adapter=Scripted(), out_dir=out, topics=("T3",), langs=("ru",), run_eval=False)
    assert man["provider"] == "scripted" and man["dataset"]["is_synthetic"] and man["runs"][0]["topic"] == "T3"
    files = sorted(p.name for p in out.glob("*.json"))
    assert "MANIFEST.json" in files and any(f.startswith("council_analyst-") for f in files)
    assert not list(tmp_path.glob(".staging-*"))  # staging removed
    # replay through the recorded provider: the council runs in recorded_demo mode, not live_model
    from oqumap.ai import provider as prov
    from oqumap.ai.llm.adapters import RecordedProvider

    ds = {d["code"]: d for d in client.get("/api/v1/datasets", headers=H).json()}["base"]["id"]
    t3 = next(t for t in client.get("/api/v1/curriculum", params={"dataset_id": ds}, headers=H).json()["topics"] if t["code"] == "T3")
    with prov.use_provider(prov.ChainProvider([RecordedProvider(out)])):
        r = client.post("/api/v1/ai/council", json={"dataset_id": ds, "topic_id": t3["id"]}, headers=H).json()
    assert r["mode"] == "recorded_demo" and r["output"]["role_modes"]["analyst"]["mode"] == "recorded_demo"


def test_record_refuses_leaks_and_missing_provider(tmp_path, monkeypatch):
    from oqumap.ai.record_live import RecordingRefused, record

    monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr("SECRET-KEY-VALUE-42"))
    out = tmp_path / "llm"
    with db.session_factory()() as s, pytest.raises((LLMError, RecordingRefused)):
        record(s, adapter=Scripted(leak="SECRET-KEY-VALUE-42"), out_dir=out, langs=("ru",), run_eval=False)
    assert not out.exists() or not list(out.glob("*.json"))
    assert not list(tmp_path.glob(".staging-*"))
    monkeypatch.setattr(get_settings(), "llm_provider", "none")
    with db.session_factory()() as s, pytest.raises(RecordingRefused):
        record(s, out_dir=out)
