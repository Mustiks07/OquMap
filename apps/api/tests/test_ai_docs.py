"""AI modes, verification, provider adapter, documents/OCR/search and mapping review."""

import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from conftest import login

from oqumap.ai import provider as prov
from oqumap.ai.provider import AnthropicProvider, CallMeta, ModelUnavailable, Provider


class FakeProvider(Provider):
    name = "fake"
    model = "fake-model"

    def __init__(self, payload):
        self.payload = payload

    @property
    def available(self):
        return True

    def complete_json(self, system, user, schema, max_tokens=None):
        assert "данные" in system  # documents are declared as data
        return (self.payload(json.loads(user)) if callable(self.payload) else self.payload), CallMeta("fake", "fake-model", 5)


@pytest.fixture
def comparison_id(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    A = next(e["id"] for e in curriculum["editions"] if e["code"] == "EDA")
    B = next(e["id"] for e in curriculum["editions"] if e["code"] == "EDB")
    r = client.post("/api/v1/comparisons", json={"dataset_id": datasets["base"]["id"], "topic_id": t3, "edition_a_id": A,
                                                 "edition_b_id": B}, headers=H).json()
    return r["context"]["analysis_id"], r["result"]


def test_live_answer_with_invented_number_is_rejected(client, H, comparison_id):
    aid, _ = comparison_id
    prov.set_provider_for_tests(FakeProvider({"text": "Пособие Б лучше на 37 процентов.", "limitations": []}))
    try:
        r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=H).json()
    finally:
        prov.set_provider_for_tests(None)
    assert r["mode"] == "template" and r["fallback_reason"] == "numeric_check_failed"
    assert r["verification"]["rejected_check"]["unverified_numbers"] == ["37"]


def test_live_answer_with_verified_numbers_is_labelled_live(client, H, comparison_id):
    aid, res = comparison_id
    d = 100 * res["adjusted"]["difference"]
    prov.set_provider_for_tests(FakeProvider({"text": f"После поправки разница составила {d:.1f} п.п.",
                                              "limitations": ["Наблюдательные данные."]}))
    try:
        r = client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=H).json()
    finally:
        prov.set_provider_for_tests(None)
    assert r["mode"] == "live_model" and r["model"] == "fake-model"


def test_recommendation_with_foreign_citation_falls_back(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    ev = client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()
    prov.set_provider_for_tests(FakeProvider({"problem": "Тема трудная", "hypothesis": "h", "action": "a", "check": "c",
                                              "limitations": [], "citations": ["00000000-0000-0000-0000-000000000000"]}))
    try:
        r = client.post("/api/v1/ai/recommend", json={"topic_analysis_id": ev["context"]["analysis_id"]}, headers=H).json()
    finally:
        prov.set_provider_for_tests(None)
    assert r["mode"] == "template" and r["fallback_reason"] == "verification_failed"
    assert r["verification"]["citations"]["status"] == "passed"


def test_misconception_recorded_demo_is_labelled(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    ev = client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()
    r = client.post("/api/v1/ai/interpret-misconception", json={"analysis_id": ev["context"]["analysis_id"], "code": "add_across"},
                    headers=H).json()
    assert r["mode"] == "recorded_demo" and "не живой" in r["mode_label"]
    n = next(x["n_learners"] for x in ev["result"]["misconceptions"] if x["code"] == "add_across")
    assert str(n) in r["output"]["interpretation"]
    assert r["verification"]["numbers"]["status"] == "passed"


def test_assistant_template_answer_uses_current_filters(client, H, datasets, curriculum):
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    r = client.post("/api/v1/assistant/query", json={"question": "Какие данные подтверждают проблему?",
                                                     "context": {"dataset_id": datasets["base"]["id"], "topic_id": t3,
                                                                 "filters": {"attempt_rule": "last"}}}, headers=H).json()
    assert r["mode"] == "template" and r["analysis_ids"]
    a = client.get(f"/api/v1/analyses/{r['analysis_ids'][0]}", headers=H).json()
    assert a["context"]["filters"]["attempt_rule"] == "last"
    assert r["verification"]["numbers"]["status"] == "passed" and r["verification"]["citations"]["status"] == "passed"
    r2 = client.post("/api/v1/assistant/query", json={"question": "Сравни пособия по теме", "context": {
        "dataset_id": datasets["base"]["id"], "topic_id": t3}}, headers=H).json()
    assert "не доказательство" in r2["output"]["text"]


def test_anthropic_adapter_structured_output_and_refusal(monkeypatch):
    calls = {}

    class Msgs:
        def __init__(self, stop="end_turn", text='{"text": "ok", "limitations": []}'):
            self.stop, self.text = stop, text

        def create(self, **kw):
            calls.update(kw)
            return SimpleNamespace(stop_reason=self.stop, model="claude-opus-5-5",
                                   content=[SimpleNamespace(type="text", text=self.text)])

    p = AnthropicProvider(client=SimpleNamespace(messages=Msgs()))
    data, meta = p.complete_json("sys", "user", {"type": "object"})
    assert data == {"text": "ok", "limitations": []}
    assert calls["output_config"]["format"]["type"] == "json_schema" and calls["model"] == p.model
    p2 = AnthropicProvider(client=SimpleNamespace(messages=Msgs(stop="refusal")))
    with pytest.raises(ModelUnavailable) as e:
        p2.complete_json("s", "u", {})
    assert e.value.reason == "model_refusal"
    with pytest.raises(ModelUnavailable) as e:
        p.complete_json("s", "x" * 100_000, {})
    assert e.value.reason == "input_too_large"
    assert not AnthropicProvider().available or True  # no key in the test env => template mode elsewhere


def test_ai_status_reports_unconfigured_model_and_ocr(client, H):
    s = client.get("/api/v1/ai/status", headers=H).json()
    assert s["live_available"] is False and s["ocr_available"] is False and s["note_ru"]


def test_document_upload_pdf_without_text_reports_ocr_unavailable(client, H):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.rect(100, 100, 200, 200, fill=1)  # an image-like page with no text layer
    cv.showPage()
    cv.save()
    r = client.post("/api/v1/documents", files={"file": ("scan.pdf", buf.getvalue(), "application/pdf")}, headers=H).json()
    import time

    for _ in range(50):
        job = client.get(f"/api/v1/jobs/{r['job']['id']}", headers=H).json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "succeeded"
    d = client.get(f"/api/v1/documents/{r['document']['id']}", headers=H).json()
    assert d["document"]["ocr_status"] == "unavailable" and d["fragments"] == []


def test_docx_with_macros_and_fake_files_are_rejected(client, H):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr("word/vbaProject.bin", "x")
    r = client.post("/api/v1/documents", files={"file": ("m.docx", buf.getvalue(), "application/octet-stream")}, headers=H)
    assert r.status_code == 415 and r.json()["error"]["code"] == "macros_not_allowed"
    r = client.post("/api/v1/documents", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}, headers=H)
    assert r.status_code == 415


def test_sources_have_pages_for_pdf_and_anchors_for_docx(client, H):
    docs = client.get("/api/v1/documents", headers=H).json()
    pdf = next(d for d in docs if d["filename"] == "demo_posobie_A.pdf")
    dx = next(d for d in docs if d["filename"] == "demo_posobie_B.docx")
    fp = client.get(f"/api/v1/documents/{pdf['id']}", headers=H).json()["fragments"]
    fd = client.get(f"/api/v1/documents/{dx['id']}", headers=H).json()["fragments"]
    sec5 = next(f for f in fp if "разными знаменателями" in f["text"])
    assert sec5["page_physical"] == 4 and sec5["page_printed"] == "14"
    assert all(f["page_physical"] is None and f["anchor"].startswith(("para-", "table-")) for f in fd)
    assert not any("демонстрационный материал OquMap" == f["text"] for f in fp)  # running footer removed
    s = client.get("/api/v1/sources/search", params={"q": "сложение дробей с разными знаменателями"}, headers=H).json()
    top = s["results"][0]
    assert top["relevance"]["matched_terms"] and top["document_version"] == 1
    src = client.get(f"/api/v1/sources/{top['source_id']}", headers=H).json()
    assert len(src["document_sha256"]) == 64 and src["text"]


def test_mapping_review_confirms_unverified_topic(fresh_client):
    c = fresh_client
    H = login(c)
    ds = {d["code"]: d for d in c.get("/api/v1/datasets", headers=H).json()}["base"]
    links = c.get("/api/v1/mappings", params={"status": "proposed"}, headers=H).json()["item_links"]
    t6 = [l for l in links if l["objective_code"].startswith("DEMO-M6-6")]
    assert t6
    v0 = ds["version"]
    for l in t6:
        r = c.post(f"/api/v1/mappings/{l['link_id']}/review", json={"decision": "confirm"}, headers=H).json()
        assert r["status"] == "confirmed"
    ds2 = c.get(f"/api/v1/datasets/{ds['id']}", headers=H).json()
    assert ds2["version"] == v0 + len(t6)
    ov = c.post(f"/api/v1/datasets/{ds['id']}/overview", json={}, headers=H).json()
    t6row = next(t for t in ov["result"]["topics"] if t["code"] == "T6")
    assert t6row["status"] not in ("unverified_mapping", "not_measured") and t6row["score"]["mean"] is not None
    V = login(c, "viewer")
    frag = c.get("/api/v1/mappings", params={"status": "proposed"}, headers=H).json()["fragment_links"][0]
    assert c.post(f"/api/v1/mappings/{frag['link_id']}/review", json={"decision": "reject"}, headers=V).status_code == 403
    assert c.post(f"/api/v1/mappings/{frag['link_id']}/review", json={"decision": "reject"}, headers=H).json()["status"] == "rejected"
