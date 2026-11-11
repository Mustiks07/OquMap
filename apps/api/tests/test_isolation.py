"""No cross-organisation leakage through API, worker jobs or the assistant."""


from conftest import login

from oqumap import db
from oqumap import models as m
from oqumap.services import jobs


def test_other_org_sees_nothing_of_demo_org(client, H, datasets, curriculum):
    O = login(client, "other_org")
    assert client.get("/api/v1/datasets", headers=O).json() == []
    ds = datasets["base"]["id"]
    t3 = next(t["id"] for t in curriculum["topics"] if t["code"] == "T3")
    A = next(e["id"] for e in curriculum["editions"] if e["code"] == "EDA")
    B = next(e["id"] for e in curriculum["editions"] if e["code"] == "EDB")
    ev = client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": ds}, headers=H).json()
    src = ev["result"]["sources"][0]["source_id"]
    link = ev["result"]["sources"][0]["link_id"]
    aid = ev["context"]["analysis_id"]
    checks = [
        client.get(f"/api/v1/datasets/{ds}", headers=O),
        client.get(f"/api/v1/datasets/{ds}/quality", headers=O),
        client.get("/api/v1/curriculum", params={"dataset_id": ds}, headers=O),
        client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": ds}, headers=O),
        client.post("/api/v1/comparisons", json={"dataset_id": ds, "topic_id": t3, "edition_a_id": A, "edition_b_id": B}, headers=O),
        client.get(f"/api/v1/sources/{src}", headers=O),
        client.get(f"/api/v1/analyses/{aid}", headers=O),
        client.post(f"/api/v1/mappings/{link}/review", json={"decision": "confirm"}, headers=O),
        client.post("/api/v1/assistant/query", json={"question": "Что по теме T3?", "context": {"dataset_id": ds}}, headers=O),
        client.post("/api/v1/ai/explain-comparison", json={"analysis_id": aid}, headers=O),
    ]
    for r in checks:
        assert r.status_code == 404, (r.request.url, r.status_code, r.text)
        assert "Демо" not in r.text
    docs = client.get("/api/v1/documents", headers=O).json()
    assert docs == []
    assert client.get("/api/v1/sources/search", params={"q": "дроби знаменатель"}, headers=O).json()["results"] == []


def test_worker_job_is_scoped_to_its_organisation(client, H):
    with db.session_factory()() as s:
        demo_doc = s.query(m.Document).first()
        other = s.query(m.Organization).filter(m.Organization.id != demo_doc.org_id).first()
        job = m.Job(org_id=other.id, kind="document_extract", payload={"document_id": demo_doc.id}, status="running")
        s.add(job)
        s.commit()
        jobs.execute(s, job)
        s.refresh(job)
        assert job.status == "failed" and job.error["code"] == "not_found"
        # the job of one org is invisible to another org through the API
    O = login(client, "other_org")
    assert client.get(f"/api/v1/jobs/{job.id}", headers=H).status_code == 404
    assert client.get(f"/api/v1/jobs/{job.id}", headers=O).status_code == 200


def test_assistant_tools_cannot_reach_foreign_dataset(client, H, datasets):
    from oqumap.ai.assistant import AssistantContext, AssistantQuery, _Executor
    from oqumap.errors import ApiError
    from oqumap.services.auth import resolve_token

    O = login(client, "other_org")
    with db.session_factory()() as s:
        p = resolve_token(s, O["Authorization"][7:])
        try:
            _Executor(s, p, AssistantQuery(question="x", context=AssistantContext(dataset_id=datasets["base"]["id"])))
            raise AssertionError("must not load a foreign dataset")
        except ApiError as e:
            assert e.code == "not_found"
