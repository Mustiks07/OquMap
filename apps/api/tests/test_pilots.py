"""Pilot protocol: server-side validation, causal ceiling, status machine (valid and forbidden transitions),
randomisation, snapshot lock, permissions and tenant isolation."""

import pytest
from conftest import login
from mhelpers import (
    assessment,
    cohorts,
    curriculum,
    dataset,
    intervention_body,
    items,
    pilot_by_code,
    topic,
    user_headers,
)

from oqumap.services.pilots import TRANSITIONS, causal_ceiling


def test_causal_ceiling_is_derived_from_design():
    assert causal_ceiling("single_group", {}) == "descriptive_change"
    assert causal_ceiling("matched_comparison", {"adjustment": "none"}) == "descriptive_comparison"
    assert causal_ceiling("matched_comparison", {"adjustment": "baseline_strata"}) == "adjusted_association"
    assert causal_ceiling("cluster_randomized", {}) == "causal_estimate"
    assert causal_ceiling("interrupted_time_series", {}) == "external_analysis_required"  # protocol only
    assert causal_ceiling("stepped_wedge", {}) == "external_analysis_required"


def test_transition_table_has_no_exit_from_terminal_states():
    assert not [k for k in TRANSITIONS if k[0] in ("completed", "stopped")]
    assert ("draft", "active") not in TRANSITIONS and ("draft", "completed") not in TRANSITIONS


@pytest.fixture(scope="module")
def ctx(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    ivs = {r["code"]: r for r in items(c.get("/api/v1/interventions", headers=H).json())}
    return {"c": c, "H": H, "ds": ds, "cur": cur, "ivs": ivs}


def _base(ctx, **kw):
    cur = ctx["cur"]
    body = {"dataset_id": ctx["ds"]["id"], "title": "Тестовый пилот", "intervention_id": ctx["ivs"]["INT-PEER"]["id"],
            "topic_id": topic(cur, "T3"), "primary_outcome_ru": "Доля баллов T3", "design": "single_group",
            "cohorts": [{"cohort_id": cid, "arm": "intervention"} for cid in cohorts(cur, "Г")[:2]],
            "baseline_assessment_id": assessment(cur, "DIAG-END"), "start_date": "2027-01-11", "end_date": "2027-02-19",
            "follow_up_due": "2027-02-26", "owner": "Тест"}
    body.update(kw)
    return body


def test_full_state_machine_and_forbidden_transitions(ctx):
    c, H = ctx["c"], ctx["H"]
    p = c.post("/api/v1/pilots", json=_base(ctx), headers=H).json()
    assert p["status"] == "draft" and p["causal_ceiling"]["code"] == "descriptive_change"
    assert p["validation"]["ok"] and any(w["code"] == "cohort_in_active_pilot" for w in p["validation"]["warnings"])
    # dosage defaults come from the intervention version (INT-PEER: 3 × 20 min for 5 weeks)
    assert p["planned"] == {"minutes_per_session": 20, "sessions_per_week": 3, "duration_weeks": 5, "total_sessions": 15,
                            "total_minutes": 300}
    for bad in ("active", "completed"):
        r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": bad}, headers=H)
        assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "ready"}, headers=H).json()
    assert p["status"] == "ready" and p["snapshot_locked"]
    # protocol and snapshot are locked outside draft
    r = c.patch(f"/api/v1/pilots/{p['id']}", json={"intervention_version": 1}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "protocol_locked"
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "draft"}, headers=H).json()
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "ready"}, headers=H).json()
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "active"}, headers=H).json()
    assert p["status"] == "active" and [e["to_status"] for e in p["events"]] == ["draft", "ready", "draft", "ready", "active"]
    r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "stopped", "note": ""}, headers=H)
    assert r.status_code == 422  # stop requires a reason
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "stopped", "note": "Школа на карантине"}, headers=H).json()
    assert p["status"] == "stopped" and p["stop_reason"] == "Школа на карантине" and p["allowed_transitions"] == []
    for to in ("active", "completed", "draft", "ready"):
        assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H).status_code == 409


def test_server_side_protocol_validation(ctx):
    c, H, cur = ctx["c"], ctx["H"], ctx["cur"]

    def errors(body):
        p = c.post("/api/v1/pilots", json=body, headers=H).json()
        r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "ready"}, headers=H)
        assert r.status_code == 422 and r.json()["error"]["code"] == "protocol_invalid"
        return {e["code"] for e in r.json()["error"]["details"]["errors"]}

    assert {"missing_field"} <= errors(_base(ctx, owner="", start_date=None))
    assert "dates_invalid" in errors(_base(ctx, start_date="2027-03-01", end_date="2027-02-01"))
    assert "baseline_after_start" in errors(_base(ctx, start_date="2026-09-01", end_date="2026-10-01"))
    assert "comparison_not_allowed" in errors(_base(ctx, cohorts=[{"cohort_id": cohorts(cur, "Г")[0], "arm": "intervention"},
                                                                   {"cohort_id": cohorts(cur, "Г")[1], "arm": "comparison"}]))
    assert "no_comparison_cohorts" in errors(_base(ctx, design="matched_comparison"))
    assert "no_intervention_cohorts" in errors(_base(ctx, cohorts=[]))
    assert "its_needs_pre_points" in errors(_base(ctx, design="interrupted_time_series", pre_period_assessment_ids=[assessment(cur, "DIAG-BASE")]))
    assert "intervention_not_reviewed" in errors(_base(ctx, intervention_id=ctx["ivs"]["INT-ERRDIAG"]["id"]))
    # cluster randomisation without server randomisation / with too few clusters
    rct = _base(ctx, design="cluster_randomized", cohorts=[{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "Г")[:3]]
                + [{"cohort_id": x, "arm": "comparison"} for x in cohorts(cur, "Г")[3:]])
    assert {"randomization_not_recorded", "too_few_clusters_for_randomization"} <= errors(rct)
    # school-level assignment with classes of one school in different arms
    mixed = _base(ctx, design="matched_comparison", assignment_unit="school",
                  cohorts=[{"cohort_id": cohorts(cur, "А")[0], "arm": "intervention"}, {"cohort_id": cohorts(cur, "Б")[0], "arm": "comparison"}])
    assert "assignment_unit_mixed" in errors(mixed)


def test_randomization_is_server_side_seeded_and_enough_clusters_allows_ready(ctx):
    c, H, cur = ctx["c"], ctx["H"], ctx["cur"]
    pool = cohorts(cur, "А") + cohorts(cur, "Б")[:4]  # 10 classes → 5 + 5 clusters (unit = class)
    body = _base(ctx, design="cluster_randomized", cohorts=[])
    p1 = c.post("/api/v1/pilots", json=body, headers=H).json()
    r1 = c.post(f"/api/v1/pilots/{p1['id']}/randomize", json={"seed": 42, "cohort_ids": pool}, headers=H).json()
    p2 = c.post("/api/v1/pilots", json=body, headers=H).json()
    r2 = c.post(f"/api/v1/pilots/{p2['id']}/randomize", json={"seed": 42, "cohort_ids": pool}, headers=H).json()
    arms1 = {x["cohort_id"]: x["arm"] for x in r1["cohorts"]}
    assert arms1 == {x["cohort_id"]: x["arm"] for x in r2["cohorts"]}  # same seed → same assignment
    assert sorted(arms1.values()).count("intervention") == 5 and r1["randomization"]["seed"] == 42
    assert r1["validation"]["ok"], r1["validation"]["errors"]
    assert r1["causal_ceiling"]["code"] == "causal_estimate"
    # a manual edit of the assignment invalidates the recorded randomisation
    edited = [{"cohort_id": cid, "arm": "intervention" if arm == "comparison" else "comparison"} for cid, arm in arms1.items()]
    r = c.patch(f"/api/v1/pilots/{p1['id']}", json={"cohorts": edited}, headers=H).json()
    assert r["randomization"] is None and any(e["code"] == "randomization_not_recorded" for e in r["validation"]["errors"])
    single = c.post("/api/v1/pilots", json=_base(ctx), headers=H).json()
    assert c.post(f"/api/v1/pilots/{single['id']}/randomize", json={"seed": 1, "cohort_ids": pool}, headers=H).status_code == 422


def test_seeded_cluster_pilot_cannot_become_ready(ctx):
    c, H = ctx["c"], ctx["H"]
    p4 = pilot_by_code(c, H, "PIL-M04")
    assert p4["status"] == "draft" and p4["randomization"]["unit"] == "school"
    codes = {e["code"] for e in p4["validation"]["errors"]}
    assert codes == {"too_few_clusters_for_randomization"}
    assert c.post(f"/api/v1/pilots/{p4['id']}/transition", json={"to_status": "ready"}, headers=H).status_code == 422


def test_snapshot_is_frozen_against_later_versions(ctx):
    c, H = ctx["c"], ctx["H"]
    p1 = pilot_by_code(c, H, "PIL-M01")
    assert p1["intervention_version"] == 1 and p1["snapshot_locked"]
    assert p1["intervention_snapshot"]["minutes_per_session"] == 20  # v2 changed it to 25
    strips = c.get(f"/api/v1/interventions/{p1['intervention_id']}", headers=H).json()
    v1 = next(v for v in strips["versions"] if v["version"] == 1)
    assert v1["content_sha256"] == p1["intervention_snapshot"]["content_sha256"] and v1["used_by_pilots"] >= 1


def test_pilot_permissions(ctx):
    c = ctx["c"]
    V = login(c, "viewer")
    M = user_headers(["methodist"])
    assert c.get("/api/v1/pilots", headers=V).status_code == 200
    assert c.post("/api/v1/pilots", json=_base(ctx), headers=V).status_code == 403
    p = c.post("/api/v1/pilots", json=_base(ctx), headers=M).json()
    assert p["allowed_transitions"] == ["ready"]
    assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "ready"}, headers=M).status_code == 200
    r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "active"}, headers=M)
    assert r.status_code == 403  # activation is for approvers
    assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "stopped", "note": "нет"}, headers=M).status_code == 403
    assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "active"}, headers=user_headers(["approver"])).status_code == 200


def test_pilot_tenant_isolation(ctx):
    c, H, cur = ctx["c"], ctx["H"], ctx["cur"]
    O = login(c, "other_org")
    p1 = pilot_by_code(c, H, "PIL-M01")
    assert items(c.get("/api/v1/pilots", headers=O).json()) == []
    for r in (c.get(f"/api/v1/pilots/{p1['id']}", headers=O),
              c.patch(f"/api/v1/pilots/{p1['id']}", json={"title": "чужой"}, headers=O),
              c.post(f"/api/v1/pilots/{p1['id']}/transition", json={"to_status": "stopped", "note": "чужой"}, headers=O),
              c.post(f"/api/v1/pilots/{p1['id']}/randomize", json={"seed": 1, "cohort_ids": ["a", "b"]}, headers=O),
              c.get("/api/v1/pilots", params={"dataset_id": ctx["ds"]["id"]}, headers=O)):
        assert r.status_code == 404, r.text
    # references across tenants/datasets are rejected
    other_iv = c.post("/api/v1/interventions", json=intervention_body("O-PIL", cur, targets=[]), headers=O)
    assert other_iv.status_code == 200
    r = c.post("/api/v1/pilots", json=_base(ctx, intervention_id=other_iv.json()["id"]), headers=H)
    assert r.status_code == 404
    base_cur = curriculum(c, H, dataset(c, H, "base")["id"])
    r = c.post("/api/v1/pilots", json=_base(ctx, cohorts=[{"cohort_id": base_cur["cohorts"][0]["id"], "arm": "intervention"}]), headers=H)
    assert r.status_code == 404 and r.json()["error"]["details"]["entity"] == "cohort"
