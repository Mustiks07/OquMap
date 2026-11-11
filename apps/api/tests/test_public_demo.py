"""Public demo mode: disposable tenants, no shared mutable state, quotas, rate limits, cleanup."""

import io
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from oqumap import db
from oqumap import models as m
from oqumap.ai import provider as prov
from oqumap.ai.provider import CallMeta, Provider
from oqumap.config import get_settings
from oqumap.db import utcnow
from oqumap.demo.seed import DEMO_ORG_ID


@pytest.fixture
def public(monkeypatch, fresh_client):
    s = get_settings()
    monkeypatch.setattr(s, "deployment_mode", "public_demo")
    return fresh_client


def demo(c, ip="10.0.0.1"):
    r = c.post("/api/v1/auth/demo-login", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body


def test_each_visitor_gets_an_own_tenant_and_template_is_untouched(public):
    c = public
    with db.session_factory()() as s:
        template_versions = {d.code: d.version for d in s.scalars(select(m.Dataset).where(m.Dataset.org_id == DEMO_ORG_ID))}
    h1, b1 = demo(c)
    h2, b2 = demo(c)
    assert b1["user"]["org_id"] != b2["user"]["org_id"] and b1["user"]["org_is_ephemeral"]
    ds1 = c.get("/api/v1/datasets", headers=h1).json()
    assert {d["code"] for d in ds1} == {"base", "illustration"}
    assert b1["recommended_dataset_id"] == next(d["id"] for d in ds1 if d["code"] == "base")
    # visitor 1 changes its own data (import a follow-up) — visitor 2 and the template see nothing of it
    from pathlib import Path

    data = (Path(__file__).resolve().parents[3] / "data/demo/imports/followup_2026_2027.csv").read_bytes()
    v = c.post("/api/v1/imports/validate", files={"file": ("f.csv", data, "text/csv")},
               data={"dataset_id": b1["recommended_dataset_id"]}, headers=h1).json()
    job = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=h1).json()
    assert job["status"] == "succeeded"
    assert c.get(f"/api/v1/datasets/{b1['recommended_dataset_id']}", headers=h1).json()["version"] == 2
    assert c.get(f"/api/v1/datasets/{b2['recommended_dataset_id']}", headers=h2).json()["version"] == 1
    with db.session_factory()() as s:
        now = {d.code: d.version for d in s.scalars(select(m.Dataset).where(m.Dataset.org_id == DEMO_ORG_ID))}
    assert now == template_versions
    # cross-tenant reads are 404
    for path in (f"/api/v1/datasets/{b1['recommended_dataset_id']}", f"/api/v1/imports/{v['id']}",
                 f"/api/v1/jobs/{job['id']}"):
        assert c.get(path, headers=h2).status_code == 404
    docs1 = c.get("/api/v1/documents", headers=h1).json()
    assert c.get(f"/api/v1/documents/{docs1[0]['id']}/file", headers=h2).status_code == 404


def test_qa_personas_and_template_are_not_reachable_in_public_demo(public):
    r = public.post("/api/v1/auth/demo-login", json={"persona": "other_org"})
    assert r.status_code == 403
    h, _ = demo(public)
    template_ds = select(m.Dataset.id).where(m.Dataset.org_id == DEMO_ORG_ID, m.Dataset.code == "base")
    with db.session_factory()() as s:
        tid = s.scalar(template_ds)
    assert public.get(f"/api/v1/datasets/{tid}", headers=h).status_code == 404
    cfg = public.get("/api/v1/config").json()
    assert cfg["deployment_mode"] == "public_demo" and cfg["qa_personas_enabled"] is False


class CountingProvider(Provider):
    name = "fake"
    model = "fake-model"
    calls = 0

    @property
    def available(self):
        return True

    def complete_json(self, system, user, schema, name="result", **kw):
        CountingProvider.calls += 1
        return {"text": "x", "limitations": []}, CallMeta("fake", "fake-model", 1)


def test_public_demo_never_spends_live_model_budget(public):
    h, b = demo(public)
    cur = public.get("/api/v1/curriculum", params={"dataset_id": b["recommended_dataset_id"]}, headers=h).json()
    t3 = next(t["id"] for t in cur["topics"] if t["code"] == "T3")
    eds = {e["code"]: e["id"] for e in cur["editions"]}
    comp = public.post("/api/v1/comparisons", json={"dataset_id": b["recommended_dataset_id"], "topic_id": t3,
                                                    "edition_a_id": eds["EDA"], "edition_b_id": eds["EDB"]}, headers=h).json()
    prov.set_provider_for_tests(CountingProvider())
    CountingProvider.calls = 0
    try:
        r = public.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=h).json()
        a = public.post("/api/v1/assistant/query", json={"question": "Сравни пособия по теме T3",
                                                         "context": {"dataset_id": b["recommended_dataset_id"]}}, headers=h).json()
    finally:
        prov.set_provider_for_tests(None)
    assert CountingProvider.calls == 0
    assert r["mode"] == "template" and r["fallback_reason"] == "live_disabled_for_public_demo"
    assert a["mode"] == "template" and a["fallback_reason"] == "live_disabled_for_public_demo"


def test_rate_limits_and_quotas(public, monkeypatch):
    s = get_settings()
    h, b = demo(public)
    monkeypatch.setattr(s, "rate_assistant", "2/3600")
    body = {"question": "Достаточно ли данных?", "context": {"dataset_id": b["recommended_dataset_id"]}}
    assert public.post("/api/v1/assistant/query", json=body, headers=h).status_code == 200
    assert public.post("/api/v1/assistant/query", json=body, headers=h).status_code == 200
    r = public.post("/api/v1/assistant/query", json=body, headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) > 0
    # tiny storage quota → uploads refused
    with db.session_factory()() as ss:
        org = ss.get(m.Organization, b["user"]["org_id"])
        org.storage_quota_bytes = 10
        ss.commit()
    r = public.post("/api/v1/documents", files={"file": ("x.pdf", b"%PDF-1.4 " + b"0" * 100, "application/pdf")}, headers=h)
    assert r.status_code == 413 and r.json()["error"]["code"] == "storage_quota_exceeded"
    # demo tenants per IP per hour
    monkeypatch.setattr(s, "demo_tenants_per_ip_per_hour", 0)
    r = public.post("/api/v1/auth/demo-login", json={})
    assert r.status_code == 429
    monkeypatch.setattr(s, "demo_tenants_per_ip_per_hour", 1000)
    monkeypatch.setattr(s, "demo_max_active_tenants", 0)
    r = public.post("/api/v1/auth/demo-login", json={})
    assert r.status_code == 503 and r.json()["error"]["code"] == "demo_capacity"


def test_login_rate_limit(public, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_login", "1/3600")
    codes = [public.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"}).status_code for _ in range(3)]
    assert codes[0] == 401 and 429 in codes


def test_expired_tenant_is_rejected_and_fully_removed(public):
    h, b = demo(public)
    org_id = b["user"]["org_id"]
    # user-created artefacts (quiz with versions, sandbox analysis) must also be removed
    ds = next(d for d in public.get("/api/v1/datasets", headers=h).json() if d["code"] == "base")
    t3 = next(t for t in public.get("/api/v1/curriculum", params={"dataset_id": ds["id"]}, headers=h).json()["topics"] if t["code"] == "T3")
    assert public.post("/api/v1/quizzes/generate", json={"dataset_id": ds["id"], "topic_id": t3["id"]}, headers=h).status_code == 200
    with db.session_factory()() as s:
        assert s.scalar(select(func.count()).select_from(m.QuizVersion)) >= 1
        before = s.scalar(select(func.count()).select_from(m.Response).where(m.Response.org_id == org_id))
        assert before > 1000
        s.get(m.Organization, org_id).expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    r = public.get("/api/v1/datasets", headers=h)
    assert r.status_code == 401 and r.json()["error"]["code"] == "demo_expired"
    from oqumap.maintenance import cleanup

    stats = cleanup()
    assert stats["tenants_deleted"] >= 1
    with db.session_factory()() as s:
        for table in db.Base.metadata.sorted_tables:
            if "org_id" in table.c:
                n = s.scalar(select(func.count()).select_from(table).where(table.c.org_id == org_id))
                assert n == 0, table.name
        assert s.get(m.Organization, org_id) is None
        assert s.scalar(select(func.count()).select_from(m.QuizVersion).join(m.Quiz, m.Quiz.id == m.QuizVersion.quiz_id)
                        .where(m.Quiz.org_id == org_id)) == 0
        assert s.scalar(select(func.count()).select_from(m.Response).where(m.Response.org_id == DEMO_ORG_ID)) > 1000


def test_lab_scenario_is_cloned_on_demand(public):
    h, _ = demo(public)
    r = public.post("/api/v1/demo/scenarios/confounded", headers=h)
    assert r.status_code == 200 and r.json()["code"] == "confounded"
    assert public.post("/api/v1/demo/scenarios/../../etc", headers=h).status_code in (404, 405)
    assert public.post("/api/v1/demo/scenarios/unknown", headers=h).status_code == 404


def test_production_mode_disables_demo_login(public, monkeypatch):
    monkeypatch.setattr(get_settings(), "deployment_mode", "production")
    assert public.post("/api/v1/auth/demo-login", json={}).status_code == 404


_ = io


def test_demo_tenant_gets_the_measurement_loop_isolated_and_fully_cleaned(public, monkeypatch):
    """Integration: the measurement & learning-loop demo (Claude 2) is built natively in each disposable tenant."""
    monkeypatch.setattr(get_settings(), "demo_tenant_measurement", "sync")
    h, b = demo(public)
    org_id = b["user"]["org_id"]
    pilots = public.get("/api/v1/pilots", headers=h).json()
    codes = {p["code"] for p in pilots["items"]}
    assert {"PIL-M01", "PIL-M02", "PIL-M03", "PIL-M04"} <= codes
    by = {p["code"]: p for p in pilots["items"]}
    assert public.get(f"/api/v1/pilots/{by['PIL-M01']['id']}", headers=h).status_code == 200
    port = public.get("/api/v1/portfolio/interventions", headers=h)
    assert port.status_code == 200
    # another visitor cannot see this tenant's pilots
    h2, _ = demo(public)
    assert public.get(f"/api/v1/pilots/{by['PIL-M01']['id']}", headers=h2).status_code == 404
    with db.session_factory()() as s:
        s.get(m.Organization, org_id).expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    from oqumap.maintenance import cleanup

    cleanup()
    with db.session_factory()() as s:
        for table in db.Base.metadata.sorted_tables:
            if "org_id" in table.c:
                assert s.scalar(select(func.count()).select_from(table).where(table.c.org_id == org_id)) == 0, table.name


def test_demo_measurement_runs_as_a_background_job(public, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "demo_tenant_measurement", "background")
    monkeypatch.setattr(s, "job_mode", "worker")  # queue only; executed below like the worker does
    h, b = demo(public)
    assert public.get("/api/v1/pilots", headers=h).json()["total"] == 0  # not ready yet, login was not delayed
    waiting = public.get("/api/v1/demo/measurement-readiness", headers=h)
    assert waiting.status_code == 200
    assert waiting.json() == {
        "status": "preparing", "dataset_id": None, "job_status": "queued", "error": None,
    }
    from oqumap.services.jobs import claim_next, execute

    with db.session_factory()() as ss:
        job = ss.scalar(select(m.Job).where(m.Job.org_id == b["user"]["org_id"], m.Job.kind == "demo_measurement"))
        assert job is not None and job.status == "queued"
        while (j := claim_next(ss)) is not None:
            execute(ss, j)
        assert ss.get(m.Job, job.id).status == "succeeded"
    assert public.get("/api/v1/pilots", headers=h).json()["total"] >= 4
    # The dataset row is committed before all assessments and pilots are seeded. A
    # running job must therefore remain "preparing" even when that row is visible.
    with db.session_factory()() as ss:
        job = ss.get(m.Job, job.id)
        job.status = "running"
        ss.commit()
    partial = public.get("/api/v1/demo/measurement-readiness", headers=h).json()
    assert partial == {"status": "preparing", "dataset_id": None, "job_status": "running", "error": None}
    with db.session_factory()() as ss:
        job = ss.get(m.Job, job.id)
        job.status = "succeeded"
        ss.commit()
    ready = public.get("/api/v1/demo/measurement-readiness", headers=h).json()
    assert ready["status"] == "ready" and ready["dataset_id"] and ready["error"] is None


def test_failed_demo_measurement_can_be_requeued(public, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "demo_tenant_measurement", "background")
    monkeypatch.setattr(s, "job_mode", "worker")
    h, b = demo(public)
    with db.session_factory()() as ss:
        job = ss.scalar(select(m.Job).where(m.Job.org_id == b["user"]["org_id"], m.Job.kind == "demo_measurement"))
        job.status = "failed"
        job.error = {"code": "internal_error", "message": "Внутренняя ошибка обработки"}
        ss.commit()
    failed = public.get("/api/v1/demo/measurement-readiness", headers=h).json()
    assert failed["status"] == "failed" and failed["error"]["code"] == "internal_error"
    retried = public.post("/api/v1/demo/measurement-readiness/retry", headers=h)
    assert retried.status_code == 200
    assert retried.json()["status"] == "preparing" and retried.json()["job_status"] == "queued"
