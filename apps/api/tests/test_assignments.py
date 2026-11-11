"""Round 2 / P1-3: explicit assessment → class assignments drive the 'assigned' denominator."""

from conftest import login
from mhelpers import curriculum, dataset, user_headers


def _quality(c, H, ds_id, code):
    lst = c.get("/api/v1/quality/assessments", params={"dataset_id": ds_id}, headers=H).json()["assessments"]
    aid = next(a for a in lst if a["assessment"]["code"] == code)["assessment"]["assessment_id"]
    return aid, c.get(f"/api/v1/quality/assessments/{aid}", headers=H).json()


def test_assigned_class_without_any_sitting_is_counted(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    aid, q = _quality(c, H, ds["id"], "DIAG-END")
    den = q["form"]["denominators"]
    assert den["assignment_scope"] == "explicit" and den["assigned_is_exact"]
    assignments = c.get(f"/api/v1/quality/assessments/{aid}/assignments", headers=H).json()
    silent = [r for r in assignments["cohorts"] if r["assigned"] and r["sitting_records"] == 0]
    assert [r["code"] for r in silent] == ["M06-6Д"]
    size = next(x for x in c.get(f"/api/v1/datasets/{ds['id']}/quality", headers=H).json()["assessments"] if x["code"] == "DIAG-BASE")
    assert size  # dataset exists; the class has sittings on other assessments
    assert den["no_sitting_record"] >= 20  # the whole class 6Д (22–28 learners) — not invisible
    assert den["present"] - den["present_outside_assignment"] + den["absent"] - den["absent_outside_assignment"] + den["no_sitting_record"] == den["assigned"]
    assert q["exclusions"]["assigned_cohorts_without_records"] == 1
    assert any(lim["code"] == "assigned_cohorts_without_records" for lim in q["limitations"])
    # removing the class from the assignment changes the denominator (new snapshot, not a stale one)
    keep = [r["cohort_id"] for r in assignments["cohorts"] if r["code"] != "M06-6Д"]
    assert c.put(f"/api/v1/quality/assessments/{aid}/assignments", json={"cohort_ids": keep}, headers=user_headers(["viewer"])).status_code == 403
    r = c.put(f"/api/v1/quality/assessments/{aid}/assignments", json={"cohort_ids": keep, "note": "6Д не писал"}, headers=H)
    assert r.status_code == 200 and sum(x["assigned"] for x in r.json()["cohorts"]) == len(keep)
    _, q2 = _quality(c, H, ds["id"], "DIAG-END")
    assert q2["form"]["denominators"]["no_sitting_record"] == 0  # 6Д removed from the assignment
    assert q2["provenance"]["analysis_id"] != q["provenance"]["analysis_id"]
    # cohorts of another dataset / org are rejected
    base_cur = curriculum(c, H, dataset(c, H, "base")["id"])
    assert c.put(f"/api/v1/quality/assessments/{aid}/assignments", json={"cohort_ids": [base_cur["cohorts"][0]["id"]]}, headers=H).status_code == 404
    O = login(c, "other_org")
    assert c.get(f"/api/v1/quality/assessments/{aid}/assignments", headers=O).status_code == 404
    assert c.put(f"/api/v1/quality/assessments/{aid}/assignments", json={"cohort_ids": []}, headers=O).status_code == 404
    _ = cur


def test_legacy_assessment_reports_inferred_scope(client, H, datasets):
    lst = client.get("/api/v1/quality/assessments", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()["assessments"]
    aid = next(a for a in lst if a["assessment"]["code"] == "POST-2026")["assessment"]["assessment_id"]
    q = client.get(f"/api/v1/quality/assessments/{aid}", headers=H).json()
    assert q["form"]["denominators"]["assignment_scope"] == "inferred_from_sittings"
    assert q["form"]["denominators"]["assigned_is_exact"] is False
    assert any(lim["code"] == "assignment_inferred" for lim in q["limitations"])
