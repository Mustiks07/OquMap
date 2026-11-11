"""A new organisation starts from nothing: templates → staged import → full analysis → decision → export."""

import io
from pathlib import Path

from conftest import login
from openpyxl import load_workbook
from pypdf import PdfReader

from oqumap import db
from oqumap.services.admin import create_organization

REPO = Path(__file__).resolve().parents[3]
EX = REPO / "data/templates/example_project"


def _login(c, username, password):
    r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _validate(c, H, ds, kind, data, name="f.csv"):
    r = c.post("/api/v1/imports/validate", files={"file": (name, data, "text/csv")}, data={"dataset_id": ds, "kind": kind},
               headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _commit(c, H, batch_id):
    return c.post("/api/v1/imports/commit", json={"batch_id": batch_id, "wait": True}, headers=H).json()


def test_templates_are_downloadable_with_instructions(fresh_client):
    c = fresh_client
    t = c.get("/api/v1/imports/templates").json()
    assert t["order"] == ["program", "editions", "item_bank", "roster", "responses", "assignments"]
    for k in t["order"]:
        x = c.get(f"/api/v1/imports/templates/{k}", params={"format": "xlsx"})
        wb = load_workbook(io.BytesIO(x.content))
        assert wb.sheetnames == ["data", "instructions"]
        csvt = c.get(f"/api/v1/imports/templates/{k}", params={"format": "csv"}).content.decode("utf-8-sig")
        assert csvt.splitlines()[0].split(",")[0]
        assert c.get(f"/api/v1/imports/examples/{k}").status_code == 200


def test_empty_org_imports_a_real_project_and_runs_the_whole_path(fresh_client):
    c = fresh_client
    with db.session_factory()() as s:
        org, _ = create_organization(s, "Сеть школ (тест)", "alice.admin", "Correct-Horse-42")
    H = _login(c, "alice.admin", "Correct-Horse-42")
    assert c.get("/api/v1/datasets", headers=H).json() == []
    ds = c.post("/api/v1/datasets", json={"name_ru": "Математика 5, 2025–2026", "is_synthetic": True}, headers=H).json()
    did = ds["id"]
    assert ds["data_level"] == "setup" and ds["program_version_id"] is None
    assert c.get(f"/api/v1/datasets/{did}/quality", headers=H).json()["data_level"] == "setup"
    # analysis before setup → clear 409, not 500
    r = c.post(f"/api/v1/datasets/{did}/overview", json={}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "project_incomplete"

    # wrong order: item bank before programme is blocked with a plain-language dependency
    v = _validate(c, H, did, "item_bank", (EX / "3_item_bank.csv").read_bytes())
    assert v["report"]["commit_allowed"] is False
    assert v["report"]["blocking"][0]["dependency"] == "program"
    r = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=H).json()
    assert r["status"] == "failed" and r["error"]["code"] == "blocking_errors"

    # a broken programme (unknown prerequisite) is strict: nothing is committed
    bad = (EX / "1_program.csv").read_text(encoding="utf-8").replace("EX-3.1;EX-1.1", "EX-9.9")
    v = _validate(c, H, did, "program", bad.encode())
    assert v["report"]["commit_allowed"] is False and "unknown_prerequisite" in v["report"]["errors_by_code"]

    for kind, fname in (("program", "1_program.csv"), ("editions", "2_editions.csv"), ("item_bank", "3_item_bank.csv"),
                        ("roster", "4_roster.csv"), ("responses", "5_responses.csv")):
        v = _validate(c, H, did, kind, (EX / fname).read_bytes(), fname)
        assert v["rows_rejected"] == 0, (kind, v["report"].get("errors_by_code"))
        j = _commit(c, H, v["id"])
        assert j["status"] == "succeeded", (kind, j)
        again = _commit(c, H, v["id"])  # idempotent
        assert again["id"] == j["id"]
    q = c.get(f"/api/v1/datasets/{did}/quality", headers=H).json()
    assert q["data_level"] == "pre_post_with_exposure" and q["counts"]["learners"] == 240
    assert all(st["done"] or st["optional"] for st in q["project"]["stages"])

    # assessment scope: without explicit assignments it is only inferred from sittings (and labelled so)
    def scopes():
        lst = c.get("/api/v1/quality/assessments", params={"dataset_id": did}, headers=H).json()["assessments"]
        return {a["assessment"]["code"]: (a["denominators"]["assignment_scope"], a["denominators"]["assigned_is_exact"]) for a in lst}

    assert set(scopes().values()) == {("inferred_from_sittings", False)}
    text = (EX / "6_assignments.csv").read_text(encoding="utf-8")
    bad = text + "EX-POST-2026,NO-SUCH-CLASS,x\n"
    v = _validate(c, H, did, "assignments", bad.encode())
    assert v["report"]["strict"] and v["report"]["commit_allowed"] is False and "unknown_class" in v["report"]["errors_by_code"]
    v = _validate(c, H, did, "assignments", text.encode(), "6_assignments.csv")
    assert v["rows_rejected"] == 0 and _commit(c, H, v["id"])["status"] == "succeeded"
    assert set(scopes().values()) == {("explicit", True)}
    again = _validate(c, H, did, "assignments", (text.replace("(пример)", "(повтор)")).encode(), "again.csv")
    assert again["report"]["commit_allowed"] is False and "already_assigned" in again["report"]["errors_by_code"]
    # re-importing the same programme file is refused
    v = _validate(c, H, did, "program", (EX / "1_program.csv").read_bytes())
    assert v["report"]["duplicate_of_batch"] or v["report"]["commit_allowed"] is False

    cur = c.get("/api/v1/curriculum", params={"dataset_id": did}, headers=H).json()
    assert [t["code"] for t in cur["topics"]] == ["EX-T1", "EX-T2", "EX-T3"]
    assert {e["code"] for e in cur["editions"]} == {"EX-BOOK1", "EX-BOOK2"}
    assert not any(o["code"].startswith("DEMO-") for o in cur["objectives"])
    ov = c.post(f"/api/v1/datasets/{did}/overview", json={}, headers=H).json()["result"]
    assert all(t["status"] in ("difficult", "attention", "stable") for t in ov["topics"])
    t2 = next(t["id"] for t in cur["topics"] if t["code"] == "EX-T2")
    ev = c.get(f"/api/v1/topics/{t2}/evidence", params={"dataset_id": did}, headers=H).json()
    assert ev["result"]["summary"]["n_learners"] > 200 and ev["result"]["summary"]["n_classes"] == 12
    eds = {e["code"]: e["id"] for e in cur["editions"]}
    comp = c.post("/api/v1/comparisons", json={"dataset_id": did, "topic_id": t2, "edition_a_id": eds["EX-BOOK1"],
                                               "edition_b_id": eds["EX-BOOK2"]}, headers=H).json()
    assert comp["result"]["adjusted"]["difference"] is not None and comp["result"]["uncertainty"]["cluster_unit"] == "class"
    pc = c.get("/api/v1/plans/context", params={"dataset_id": did}, headers=H).json()
    assert pc["budget"] == 32 and len(pc["topics"]) == 3
    topics = [{"topic_id": t["topic_id"], "code": t["code"], "current_hours": t["current_hours"], "priority": t["priority"],
               "min_hours": t["min_hours"], "max_hours": t["max_hours"], "elapsed_hours": t["elapsed_hours"]} for t in pc["topics"]]
    plan = c.post("/api/v1/plans/solve", json={"dataset_id": did, "topics": topics, "budget": pc["budget"]}, headers=H).json()
    sc = plan["result"]["scenarios"][0]
    assert sc["status"] == "optimal" and sc["validation"]["valid"]
    dec = c.post("/api/v1/decisions", json={
        "dataset_id": did, "topic_id": t2, "target_group": "Все классы", "problem": "p", "hypothesis": "h", "action": "a",
        "responsible": "Методист", "analysis_ids": [ev["context"]["analysis_id"], comp["context"]["analysis_id"]],
        "plan_analysis_id": plan["context"]["analysis_id"], "plan_preset": "balanced"}, headers=H)
    assert dec.status_code == 200, dec.text
    ap = c.post(f"/api/v1/decisions/{dec.json()['id']}/approve", json={}, headers=H).json()
    pdf = c.get(f"/api/v1/decisions/{ap['id']}/report", params={"format": "pdf"}, headers=H)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "EX-T2" in text and "СИНТЕТИЧЕСКИЕ ДАННЫЕ" in text

    # isolation both ways
    D = login(c)
    assert c.get(f"/api/v1/datasets/{did}", headers=D).status_code == 404
    assert c.get(f"/api/v1/decisions/{ap['id']}", headers=D).status_code == 404
    demo_ds = c.get("/api/v1/datasets", headers=D).json()[0]["id"]
    assert c.get(f"/api/v1/datasets/{demo_ds}", headers=H).status_code == 404
    assert {d["id"] for d in c.get("/api/v1/datasets", headers=H).json()} == {did}


def test_formula_and_invalid_structure_rejected(fresh_client):
    c = fresh_client
    with db.session_factory()() as s:
        create_organization(s, "Org F", "bob.admin", "Another-Strong-7")
    H = _login(c, "bob.admin", "Another-Strong-7")
    did = c.post("/api/v1/datasets", json={"name_ru": "F"}, headers=H).json()["id"]
    v = _validate(c, H, did, "program", (EX / "1_program.csv").read_bytes())
    _commit(c, H, v["id"])
    bank = (EX / "3_item_bank.csv").read_text(encoding="utf-8")
    bank = bank.replace("Вычислите 248 + 175", '=HYPERLINK(""http://x"")').replace("EX-1.2,confirmed", "EX-1.2:0.7,confirmed")
    v = _validate(c, H, did, "item_bank", bank.encode())
    codes = v["report"]["errors_by_code"]
    assert "formula_not_allowed" in codes and "weights_not_normalized" in codes and v["report"]["commit_allowed"] is False


def test_user_management_and_password_rules(fresh_client):
    c = fresh_client
    with db.session_factory()() as s:
        create_organization(s, "Org U", "carol.admin", "Admin-Pass-123")
    H = _login(c, "carol.admin", "Admin-Pass-123")
    r = c.post("/api/v1/admin/users", json={"username": "dan.viewer", "password": "short", "roles": ["viewer"]}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    u = c.post("/api/v1/admin/users", json={"username": "dan.viewer", "password": "Viewer-Pass-99", "roles": ["viewer"]},
               headers=H).json()
    V = _login(c, "dan.viewer", "Viewer-Pass-99")
    assert c.post("/api/v1/datasets", json={"name_ru": "x"}, headers=V).status_code == 403
    assert c.get("/api/v1/admin/users", headers=V).status_code == 403
    c.post(f"/api/v1/admin/users/{u['id']}", json={"is_active": False}, headers=H)
    assert c.get("/api/v1/auth/me", headers=V).status_code == 401
    D = login(c)  # demo methodist (no admin role) cannot manage users
    assert c.get("/api/v1/admin/users", headers=D).status_code == 403
