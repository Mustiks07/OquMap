"""Intervention library: versioning, immutability, archive instead of delete, targets, explainable suggestions,
permissions and tenant isolation."""

from conftest import login
from mhelpers import curriculum, dataset, intervention_body, objective, topic, user_headers


def test_seeded_library_has_levels_statuses_and_versions(fresh_client):
    c = fresh_client
    H = login(c)
    rows = {r["code"]: r for r in c.get("/api/v1/interventions", headers=H).json()}
    assert {"INT-STRIPS", "INT-PEER", "INT-NUMLINE", "INT-ERRDIAG", "INT-WORKED", "INT-OLDDRILL"} <= set(rows)
    assert {r["evidence_level"] for r in rows.values()} == {"practice_based", "observational", "experimental"}
    assert rows["INT-OLDDRILL"]["status"] == "archived"
    assert rows["INT-ERRDIAG"]["current_status"] == "draft" and rows["INT-ERRDIAG"]["reviewed_version"] is None
    strips = c.get(f"/api/v1/interventions/{rows['INT-STRIPS']['id']}", headers=H).json()
    assert [v["version"] for v in strips["versions"]] == [2, 1] and strips["reviewed_version"] == 2
    # the seeded pilot is synthetic: its accepted entry is demo evidence, not real evidence
    assert strips["evidence_summary"]["accepted_entries"] == 0 and strips["evidence_summary"]["accepted_synthetic_entries"] == 1
    # filters
    assert {r["code"] for r in c.get("/api/v1/interventions", params={"evidence_level": "experimental"}, headers=H).json()} == {"INT-NUMLINE"}
    assert "INT-STRIPS" in {r["code"] for r in c.get("/api/v1/interventions", params={"misconception": "add_across"}, headers=H).json()}
    assert {r["code"] for r in c.get("/api/v1/interventions", params={"status": "archived"}, headers=H).json()} == {"INT-OLDDRILL"}


def test_crud_versioning_and_immutability(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "base")
    cur = curriculum(c, H, ds["id"])
    r = c.post("/api/v1/interventions", json=intervention_body("T-VER", cur, title_ru="  Черновик\x07 ", dataset_id=ds["id"]), headers=H)
    assert r.status_code == 200, r.text
    iv = r.json()
    assert iv["current"]["title_ru"] == "Черновик"  # control chars and whitespace stripped
    assert iv["current"]["status"] == "draft" and iv["current"]["total_minutes"] == 160
    assert c.post("/api/v1/interventions", json=intervention_body("T-VER", cur), headers=H).status_code == 409
    # draft is editable; content hash follows content
    h1 = iv["current"]["content_sha256"]
    r = c.patch(f"/api/v1/interventions/{iv['id']}", json={"duration_weeks": 6, "expected_version": 1}, headers=H)
    assert r.status_code == 200 and r.json()["current"]["total_minutes"] == 240 and r.json()["current"]["content_sha256"] != h1
    assert c.patch(f"/api/v1/interventions/{iv['id']}", json={"duration_weeks": 7, "expected_version": 9}, headers=H).status_code == 409
    # link an objective target to the draft
    r = c.post(f"/api/v1/interventions/{iv['id']}/targets", json={"target_type": "objective", "target_id": objective(cur, "DEMO-M6-3.1")}, headers=H)
    assert any(t["code"] == "DEMO-M6-3.1" for t in r.json()["current"]["targets"])
    assert c.post(f"/api/v1/interventions/{iv['id']}/targets", json={"target_type": "misconception", "misconception_code": "nope"},
                  headers=H).status_code == 422
    # review → immutable
    rev = c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={"note": "ok"}, headers=H)
    assert rev.status_code == 200 and rev.json()["current"]["status"] == "reviewed"
    frozen = rev.json()["current"]["content_sha256"]
    for resp in (c.patch(f"/api/v1/interventions/{iv['id']}", json={"title_ru": "Подмена"}, headers=H),
                 c.post(f"/api/v1/interventions/{iv['id']}/targets", json={"target_type": "topic", "target_id": topic(cur, "T2")}, headers=H),
                 c.delete(f"/api/v1/interventions/{iv['id']}/versions/1", headers=H)):
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "version_immutable", resp.text
    # change = new version; v1 unchanged
    v2 = c.post(f"/api/v1/interventions/{iv['id']}/versions", json={"title_ru": "Версия 2", "change_note": "уточнение"}, headers=H).json()
    assert v2["latest_version"] == 2 and v2["current"]["status"] == "draft" and v2["reviewed_version"] == 1
    v1 = next(v for v in v2["versions"] if v["version"] == 1)
    assert v1["title_ru"] == "Черновик" and v1["content_sha256"] == frozen
    assert c.post(f"/api/v1/interventions/{iv['id']}/versions", json={}, headers=H).json()["error"]["code"] == "draft_exists"
    # unreferenced draft can be deleted; reviewed history stays
    d = c.delete(f"/api/v1/interventions/{iv['id']}/versions/2", headers=H).json()
    assert d["deleted_version"] == 2 and d["intervention"]["latest_version"] == 1
    # archive (no physical delete); archived → no new pilot, no edits
    a = c.post(f"/api/v1/interventions/{iv['id']}/archive", json={"reason": "заменена"}, headers=H).json()
    assert a["status"] == "archived" and a["versions"][0]["status"] == "reviewed"
    assert c.get(f"/api/v1/interventions/{iv['id']}", headers=H).status_code == 200
    assert c.post(f"/api/v1/interventions/{iv['id']}/versions", json={}, headers=H).json()["error"]["code"] == "intervention_archived"
    pilot = c.post("/api/v1/pilots", json={"dataset_id": ds["id"], "title": "Пилот на архиве", "intervention_id": iv["id"],
                                           "topic_id": topic(cur, "T3")}, headers=H)
    assert pilot.status_code == 409 and pilot.json()["error"]["code"] == "intervention_archived"


def test_review_requires_content_and_validation_errors(fresh_client):
    c = fresh_client
    H = login(c)
    cur = curriculum(c, H, dataset(c, H, "base")["id"])
    iv = c.post("/api/v1/interventions", json=intervention_body("T-EMPTY", cur, instructions_ru="", targets=[]), headers=H).json()
    r = c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={}, headers=H)
    assert r.status_code == 422 and set(r.json()["error"]["details"]["missing"]) == {"instructions_ru", "targets"}
    bad = intervention_body("T-BAD", cur, evidence_links=[{"title": "x", "url": "javascript:alert(1)"}])
    assert c.post("/api/v1/interventions", json=bad, headers=H).status_code == 422
    assert c.post("/api/v1/interventions", json=intervention_body("x y", cur), headers=H).status_code == 422  # code pattern
    assert c.post("/api/v1/interventions", json=intervention_body("T-LONG", cur, adaptation="x", title_ru="a" * 301), headers=H).status_code == 422


def test_suggestions_are_explainable_and_exclude_drafts_and_archived(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    r = c.get("/api/v1/interventions/suggest", params={"dataset_id": ds["id"], "topic_id": topic(cur, "T3"),
                                                        "misconception": "add_across", "grade": 6, "language": "ru"}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ranking_kind"] == "explainable_match_score" and d["scoring_rule"]["misconception_match"] == 3.0
    top = d["suggestions"][0]
    assert top["code"] == "INT-STRIPS"
    assert top["score"] == sum(x["points"] for x in top["components"])
    assert {x["code"] for x in top["components"]} >= {"misconception_match", "topic_match", "evidence_observational",
                                                        "synthetic_demo_signals"}
    assert next(x for x in top["components"] if x["code"] == "synthetic_demo_signals")["points"] == 0
    assert "accepted_positive_signals" not in {x["code"] for x in top["components"]}
    excluded = {e["code"]: e["reason"] for e in d["excluded"]}
    assert excluded["INT-OLDDRILL"] == "archived" and excluded["INT-ERRDIAG"] == "no_reviewed_version"
    assert excluded["INT-WORKED"] == "no_target_match"
    assert all(s["code"] not in ("INT-OLDDRILL", "INT-ERRDIAG") for s in d["suggestions"])
    assert d["limitations"]
    assert c.get("/api/v1/interventions/suggest", headers=H).status_code == 422


def test_intervention_permissions(fresh_client):
    c = fresh_client
    H = login(c)
    cur = curriculum(c, H, dataset(c, H, "base")["id"])
    V = login(c, "viewer")
    M = user_headers(["methodist"])
    A = user_headers(["analyst"])
    assert c.get("/api/v1/interventions", headers=V).status_code == 200
    assert c.get("/api/v1/interventions", headers=A).status_code == 200
    assert c.post("/api/v1/interventions", json=intervention_body("T-V", cur), headers=V).status_code == 403
    iv = c.post("/api/v1/interventions", json=intervention_body("T-M", cur), headers=M).json()
    assert c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={}, headers=M).status_code == 403  # approver only
    assert c.post(f"/api/v1/interventions/{iv['id']}/archive", json={"reason": "нет"}, headers=M).status_code == 403
    assert c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={}, headers=user_headers(["approver"])).status_code == 200
    assert c.post(f"/api/v1/interventions/{iv['id']}/archive", json={"reason": "admin"}, headers=user_headers(["admin"])).status_code == 200


def test_intervention_tenant_isolation(fresh_client):
    c = fresh_client
    H = login(c)
    O = login(c, "other_org")
    ds = dataset(c, H, "base")
    cur = curriculum(c, H, ds["id"])
    iv = c.post("/api/v1/interventions", json=intervention_body("T-ISO", cur), headers=H).json()
    assert c.get("/api/v1/interventions", headers=O).json() == []
    for r in (c.get(f"/api/v1/interventions/{iv['id']}", headers=O),
              c.patch(f"/api/v1/interventions/{iv['id']}", json={"title_ru": "x"}, headers=O),
              c.post(f"/api/v1/interventions/{iv['id']}/versions", json={}, headers=O),
              c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={}, headers=O),
              c.post(f"/api/v1/interventions/{iv['id']}/archive", json={"reason": "чужое"}, headers=O),
              c.get(f"/api/v1/interventions/{iv['id']}/evidence", headers=O),
              c.get("/api/v1/interventions", params={"dataset_id": ds["id"]}, headers=O)):
        assert r.status_code == 404, r.text
    # foreign topic id as a target, foreign dataset as scope
    assert c.post("/api/v1/interventions", json=intervention_body("O-1", cur), headers=O).status_code == 404
    assert c.post("/api/v1/interventions", json={**intervention_body("O-2", cur, targets=[]), "dataset_id": ds["id"]},
                  headers=O).status_code == 404
