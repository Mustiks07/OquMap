"""End-to-end API path on the seeded demo: data quality → topic → comparison → plan → decision → report →
follow-up import → dynamics, plus staleness and contract checks."""

import io
import json
from pathlib import Path

from conftest import login
from openpyxl import load_workbook
from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[3]


def topic_id(curriculum, code):
    return next(t["id"] for t in curriculum["topics"] if t["code"] == code)


def edition_id(curriculum, code):
    return next(e["id"] for e in curriculum["editions"] if e["code"] == code)


def test_health_and_datasets_are_synthetic(fresh_client):
    c = fresh_client
    assert c.get("/health").json()["status"] == "ok"
    H = login(c)
    ds = c.get("/api/v1/datasets", headers=H).json()
    assert {d["code"] for d in ds} >= {"base", "no_difference", "few_clusters", "unlinked_forms", "confounded", "illustration"}
    assert all(d["is_synthetic"] for d in ds)


def test_full_methodist_path(fresh_client):
    c = fresh_client
    H = login(c)
    ds = {d["code"]: d for d in c.get("/api/v1/datasets", headers=H).json()}["base"]
    cur = c.get("/api/v1/curriculum", params={"dataset_id": ds["id"]}, headers=H).json()
    t3 = topic_id(cur, "T3")
    A, B = edition_id(cur, "EDA"), edition_id(cur, "EDB")

    q = c.get(f"/api/v1/datasets/{ds['id']}/quality", headers=H).json()
    assert q["data_level"] == "pre_post_with_exposure"
    assert any(a["absent"] > 0 for a in q["assessments"])

    filters = {"attempt_rule": "first"}
    ov = c.post(f"/api/v1/datasets/{ds['id']}/overview", json=filters, headers=H).json()
    statuses = {t["code"]: t["status"] for t in ov["result"]["topics"]}
    assert statuses["T8"] == "not_measured" and statuses["T6"] == "unverified_mapping"
    assert next(t for t in ov["result"]["topics"] if t["code"] == "T8")["score"] is None  # not a zero
    assert ov["result"]["priorities"][0]["code"] == "T3"

    ev = c.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": ds["id"], "filters": json.dumps(filters)}, headers=H).json()
    assert ev["context"]["is_stale"] is False
    assert ev["result"]["misconceptions"] and ev["result"]["sources"]
    # same filters → same snapshot id (screen / assistant / report quote one analysis)
    ev2 = c.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": ds["id"], "filters": json.dumps(filters)}, headers=H).json()
    assert ev2["context"]["analysis_id"] == ev["context"]["analysis_id"]

    comp = c.post("/api/v1/comparisons", json={"dataset_id": ds["id"], "topic_id": t3, "edition_a_id": A, "edition_b_id": B,
                                               "filters": filters}, headers=H).json()
    r = comp["result"]
    assert r["raw"]["difference"] < 0 < r["adjusted"]["difference"], "composition effect must flip the ranking"
    assert r["inference_level"] == "adjusted_association"
    assert r["uncertainty"]["cluster_unit"] == "class"

    expl = c.post("/api/v1/ai/explain-comparison", json={"analysis_id": comp["context"]["analysis_id"]}, headers=H).json()
    assert expl["mode"] == "template" and expl["fallback_reason"] == "model_not_configured"
    assert expl["verification"]["numbers"]["status"] == "passed"

    ctx = c.get("/api/v1/plans/context", params={"dataset_id": ds["id"], "filters": json.dumps(filters)}, headers=H).json()
    topics = [{"topic_id": t["topic_id"], "code": t["code"], "title": t["title_ru"], "current_hours": t["current_hours"],
               "priority": t["priority"], "min_hours": t["min_hours"], "max_hours": t["max_hours"],
               "elapsed_hours": t["elapsed_hours"]} for t in ctx["topics"]]
    plan = c.post("/api/v1/plans/solve", json={"dataset_id": ds["id"], "filters": filters, "topics": topics,
                                                 "budget": ctx["budget"], "presets": ["balanced", "minimal_changes"]},
                  headers=H).json()
    scen = plan["result"]["scenarios"][0]
    assert scen["status"] in ("optimal", "feasible") and scen["validation"]["valid"]
    assert sum(scen["hours"].values()) == ctx["budget"]
    t3_change = next(ch for ch in scen["changes"] if ch["code"] == "T3")
    assert t3_change["delta"] > 0

    rec = c.post("/api/v1/ai/recommend", json={"topic_analysis_id": ev["context"]["analysis_id"],
                                                "comparison_analysis_id": comp["context"]["analysis_id"]}, headers=H).json()
    assert rec["verification"]["citations"]["status"] == "passed" and rec["citations"]

    dec = c.post("/api/v1/decisions", json={
        "dataset_id": ds["id"], "topic_id": t3, "filters": {**filters, "edition_ids": [A]},
        "target_group": "Классы, работающие по пособию А", "problem": rec["output"]["problem"],
        "hypothesis": rec["output"]["hypothesis"], "action": rec["output"]["action"], "responsible": "Методист МО",
        "follow_up_date": "2027-02-10", "follow_up_criterion": "Рост доли баллов по общим заданиям T3",
        "analysis_ids": [ev["context"]["analysis_id"], comp["context"]["analysis_id"]],
        "plan_analysis_id": plan["context"]["analysis_id"], "plan_preset": "balanced",
        "source_ids": rec["citations"], "generation_id": rec["generation_id"]}, headers=H)
    assert dec.status_code == 200, dec.text
    dec = dec.json()
    assert dec["status"] == "draft" and dec["version"] == 1
    snap = dec["snapshot"]
    assert snap["comparison"]["adjusted"]["difference"] == r["adjusted"]["difference"]
    assert snap["topic"]["summary"]["mean"] == ev["result"]["summary"]["mean"]

    # viewer cannot approve; methodist-approver can; approval creates a version, history kept
    V = login(c, "viewer")
    assert c.post(f"/api/v1/decisions/{dec['id']}/approve", json={}, headers=V).status_code == 403
    ap = c.post(f"/api/v1/decisions/{dec['id']}/approve", json={"note": "Согласовано на МО"}, headers=H).json()
    assert ap["status"] == "approved" and ap["version"] == 2
    assert [h["status"] for h in ap["history"]] == ["superseded", "approved"]

    # exports match the snapshot
    pdf = c.get(f"/api/v1/decisions/{ap['id']}/report", params={"format": "pdf"}, headers=H)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "СИНТЕТИЧЕСКИЕ ДАННЫЕ" in text and "T3" in text
    pct = f"{100 * r['adjusted']['difference']:+.1f}".replace(".", ",")
    assert pct in text
    x = c.get(f"/api/v1/decisions/{ap['id']}/report", params={"format": "xlsx"}, headers=H)
    wb = load_workbook(io.BytesIO(x.content))
    rows = list(wb["results"].iter_rows(values_only=True))
    diff_row = next(rw for rw in rows if rw[1] == "adjusted_difference_b_minus_a")
    assert abs(float(diff_row[3]) - r["adjusted"]["difference"]) < 1e-12
    csvb = c.get(f"/api/v1/decisions/{ap['id']}/report", params={"format": "csv"}, headers=H)
    assert "adjusted_difference_b_minus_a" in csvb.content.decode("utf-8-sig")

    # follow-up import → dataset version increases → old analyses are stale
    data = (REPO / "data/demo/imports/followup_2026_2027.csv").read_bytes()
    v = c.post("/api/v1/imports/validate", files={"file": ("followup.csv", data, "text/csv")},
               data={"dataset_id": ds["id"], "kind": "responses"}, headers=H).json()
    assert v["rows_rejected"] == 0, v["report"]["errors_by_code"]
    job = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=H).json()
    assert job["status"] == "succeeded", job
    old = c.get(f"/api/v1/analyses/{ev['context']['analysis_id']}", headers=H).json()
    assert old["context"]["is_stale"] is True
    dstale = c.get(f"/api/v1/decisions/{ap['id']}", headers=H).json()
    assert dstale["is_stale"] is True
    # creating a decision from a stale analysis is refused
    bad = c.post("/api/v1/decisions", json={"dataset_id": ds["id"], "topic_id": t3, "target_group": "x", "problem": "x",
                                            "hypothesis": "x", "action": "x", "responsible": "x",
                                            "analysis_ids": [ev["context"]["analysis_id"]]}, headers=H)
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "stale_analysis"

    fu = c.post(f"/api/v1/decisions/{ap['id']}/follow-up", json={}, headers=H)
    assert fu.status_code == 200, fu.text
    fu = fu.json()
    res = fu["result"]
    assert res["interpretation_level"] == "observed_dynamics"
    assert res["target"]["adjusted_change"] > 0
    assert res["status"] in ("positive_signal", "not_confirmed")
    assert res["comparison_group"] is not None
    assert fu["decision"]["follow_ups"]
    pdf2 = c.get(f"/api/v1/decisions/{ap['id']}/report", params={"format": "pdf"}, headers=H)
    assert "Повторная проверка" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf2.content)).pages)


def test_comparison_scenarios(client, H, datasets, curriculum):
    t3 = topic_id(curriculum, "T3")
    A, B = edition_id(curriculum, "EDA"), edition_id(curriculum, "EDB")

    def run(code, **kw):
        body = {"dataset_id": datasets[code]["id"], "topic_id": t3, "edition_a_id": A, "edition_b_id": B, **kw}
        r = client.post("/api/v1/comparisons", json=body, headers=H)
        assert r.status_code == 200, r.text
        return r.json()["result"]

    nd = run("no_difference")
    assert nd["signal"] == "no_clear_difference"
    fc = run("few_clusters")
    assert fc["uncertainty"]["adjusted_difference_ci"] is None and fc["status"] == "limited"
    uf = run("unlinked_forms")
    assert uf["status"] == "not_comparable" and uf["adjusted"]["difference"] is None
    assert any(x["code"] == "forms_not_linked" for x in uf["reasons"])
    cf = run("confounded")
    assert cf["status"] == "not_comparable" and not cf["ranking_allowed"]
    il = run("illustration", strata_scheme="pre_two_level", weight_mode="equal")
    assert round(il["raw"]["a"]["mean"], 4) == 0.76 and round(il["raw"]["b"]["mean"], 4) == 0.63
    assert round(il["adjusted"]["a"], 4) == 0.60 and round(il["adjusted"]["b"], 4) == 0.75


def test_composition_fixture_endpoint_computes_numbers(client, H):
    r = client.get("/api/v1/fixtures/composition", headers=H).json()
    assert round(r["raw"]["a"]["mean"], 2) == 0.76 and round(r["adjusted"]["b"], 2) == 0.75


def test_attempt_rule_changes_scores_but_not_learner_counts(client, H, datasets, curriculum):
    t3 = topic_id(curriculum, "T3")
    first = client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": datasets["base"]["id"],
                       "filters": json.dumps({"attempt_rule": "first"})}, headers=H).json()["result"]
    last = client.get(f"/api/v1/topics/{t3}/evidence", params={"dataset_id": datasets["base"]["id"],
                      "filters": json.dumps({"attempt_rule": "last"})}, headers=H).json()["result"]
    assert first["summary"]["n_learners"] == last["summary"]["n_learners"]
    assert last["summary"]["mean"] != first["summary"]["mean"]
    assert first["exclusions"]["learners_with_repeat_attempts"] > 0


def test_plan_conflict_is_explained_with_verified_core(client, H, datasets):
    topics = [
        {"code": "R", "current_hours": 4, "min_hours": 3, "fixed": True, "priority": 0.2},
        {"code": "TARGET", "current_hours": 8, "min_hours": 10, "max_hours": 10, "priority": 1},
        {"code": "CONS", "current_hours": 4, "min_hours": 3, "fixed": True, "priority": 0.2},
        {"code": "CHECK", "current_hours": 4, "min_hours": 4, "fixed": True, "priority": 0.5},
    ]
    r = client.post("/api/v1/plans/solve", json={"dataset_id": datasets["base"]["id"], "topics": topics, "budget": 20},
                    headers=H).json()
    sc = r["result"]["scenarios"][0]
    assert sc["status"] == "infeasible" and sc["hours"] is None
    assert sc["conflict"]["verified"] is True
    assert all("message_ru" in x for x in sc["conflict"]["constraints"])


def test_error_contract_and_validation(client, H):
    r = client.get("/api/v1/datasets/does-not-exist", headers=H)
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error", "request_id"} and body["error"]["code"] == "not_found"
    assert client.get("/api/v1/datasets").status_code == 401
    r = client.post("/api/v1/comparisons", json={"dataset_id": "x"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_responses_have_no_nan(client, H, datasets, curriculum):
    t8 = topic_id(curriculum, "T8")
    raw = client.get(f"/api/v1/topics/{t8}/evidence", params={"dataset_id": datasets["base"]["id"]}, headers=H).text
    assert "NaN" not in raw and "Infinity" not in raw
    ev = json.loads(raw)["result"]
    assert ev["status"] == "not_measured" and ev["summary"] is None
