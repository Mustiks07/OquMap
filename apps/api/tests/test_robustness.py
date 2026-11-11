"""Round 2 / P2-9, P2-10, P2-13: database constraints and races → 409, small-cell suppression, stable pagination."""

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
from sqlalchemy.exc import IntegrityError

from oqumap import db
from oqumap import measurement_models as mm
from oqumap import models as m
from oqumap.services import privacy

# ---------------------------------------------------------------------------
# Suppression (pure)
# ---------------------------------------------------------------------------


def test_primary_and_complementary_suppression():
    out = privacy.suppress_cells({"a": 40, "b": 6, "c": 25})
    assert out["b"] == {"value": None, "suppressed": True, "reason": "small_cell"}
    assert out["c"]["reason"] == "complementary" and out["a"]["value"] == 40  # next smallest hidden: total − a ≠ b
    two = privacy.suppress_cells({"a": 40, "b": 6, "c": 3})
    assert two["b"]["reason"] == two["c"]["reason"] == "small_cell" and not two["a"]["suppressed"]
    assert not any(x["suppressed"] for x in privacy.suppress_cells({"a": 40, "b": 12}).values())
    assert privacy.suppress_cells({"a": 40, "b": 6}, total_visible=False)["a"]["suppressed"] is False


def test_outcome_filter_hides_small_arm_and_derived_estimate():
    res = {"arms": {"intervention": {"matched": 60, "assigned": 64, "change": {"mean": 0.12}, "baseline_mean": 0.4},
                    "comparison": {"matched": 7, "assigned": 8, "change": {"mean": 0.02}, "baseline_mean": 0.41}},
           "primary": {"estimate": 0.10, "ci_low": 0.02, "ci_high": 0.18}, "raw": {"estimate": 0.1}, "attrition": 0.06,
           "n_matched": 67, "cohorts": [{"code": "x"}]}
    f = privacy.filter_outcome_result(res)
    assert f["arms"]["comparison"]["suppressed"] and f["arms"]["comparison"]["change"]["mean"] is None
    # the intervention arm stays (60 ≥ 10) but the difference would reveal the comparison arm → hidden too
    assert f["primary"]["estimate"] is None and f["primary"]["suppression_reason"] == "complementary"
    assert f["raw"] is None and f["n_matched"] is None and f["cohorts"] is None
    assert f["suppression"]["suppressed_arms"] == {"comparison": "small_cell"}


@pytest.fixture(scope="module")
def env(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    return c, H, ds, curriculum(c, H, ds["id"])


def test_viewer_sees_suppressed_outcome_methodist_sees_values(env):
    c, H, ds, cur = env
    p1 = pilot_by_code(c, H, "PIL-M01")
    V = login(c, "viewer")
    ok = c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=V).json()[0]
    assert ok["result"]["suppression"]["applied"] is False and ok["result"]["primary"]["estimate"] is not None
    with db.session_factory()() as s:  # simulate a small comparison arm in the stored result
        o = s.query(mm.PilotOutcome).filter(mm.PilotOutcome.pilot_id == p1["id"]).first()
        r = dict(o.result)
        r["arms"] = {**r["arms"], "comparison": {**r["arms"]["comparison"], "matched": 6}}
        o.result = r
        s.commit()
    v = c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=V).json()[0]
    assert v["result"]["arms"]["comparison"]["suppressed"] and v["result"]["primary"]["estimate"] is None
    full = c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=H).json()[0]
    assert full["result"]["arms"]["comparison"]["matched"] == 6 and full["result"]["primary"]["estimate"] is not None


def test_portfolio_learner_cells_are_suppressed_for_viewers(env):
    from oqumap.services.portfolio import _learner_cells

    cells = {"positive_signal": 150, "invalid_due_to_fidelity": 7, "mixed": 30}
    v = _learner_cells(cells, detail=False)
    assert v["cells"]["invalid_due_to_fidelity"]["reason"] == "small_cell" and v["cells"]["mixed"]["reason"] == "complementary"
    assert v["total"] == 187 and v["suppression_applied"]
    assert _learner_cells(cells, detail=True)["cells"]["invalid_due_to_fidelity"]["value"] == 7
    c, H, ds, cur = env
    pv = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"]}, headers=login(c, "viewer")).json()
    assert pv["learners_by_outcome_status"]["min_cell"] == 10 and "cells" in pv["learners_by_outcome_status"]


# ---------------------------------------------------------------------------
# Constraints and races
# ---------------------------------------------------------------------------


def _expect_integrity(fn):
    with db.session_factory()() as s:
        fn(s)
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_database_constraints(env):
    c, H, ds, cur = env
    p1, p2 = pilot_by_code(c, H, "PIL-M01"), pilot_by_code(c, H, "PIL-M02")
    with db.session_factory()() as s:
        v = s.query(mm.InterventionVersion).first()
        o2 = s.query(mm.PilotOutcome).filter(mm.PilotOutcome.pilot_id == p2["id"]).first()
        other_iv = s.query(mm.Intervention).filter(mm.Intervention.id != v.intervention_id).first()
        vid, iid, o2id, org = v.id, v.intervention_id, o2.id, v.org_id
        log = s.query(mm.FidelityLog).filter(mm.FidelityLog.pilot_id == p1["id"]).first()
        log_id, cohort = log.id, log.cohort_id
    _expect_integrity(lambda s: s.add(mm.InterventionTarget(org_id=org, intervention_version_id=vid, target_type="topic",
                                                            topic_id=None, misconception_code="add_across")))
    _expect_integrity(lambda s: s.add(mm.FidelityLog(org_id=org, pilot_id=p1["id"], cohort_id=cohort, session_date=log.session_date,
                                                     planned_minutes=20, delivered_minutes=20, activities_planned=-1)))
    _expect_integrity(lambda s: s.get(mm.InterventionVersion, vid).__setattr__("duration_weeks", 0))
    # a conclusion of PIL-M01 pointing at PIL-M02's outcome
    _expect_integrity(lambda s: s.add(mm.PilotConclusion(org_id=org, pilot_id=p1["id"], outcome_id=o2id, decision="continue",
                                                         summary_ru="x" * 12)))
    # a pilot whose version belongs to another intervention
    _expect_integrity(lambda s: s.get(mm.Pilot, p1["id"]).__setattr__("intervention_id", other_iv.id))
    # two corrections of one log
    def two_corrections(s):
        for _ in range(2):
            s.add(mm.FidelityLog(org_id=org, pilot_id=p1["id"], cohort_id=cohort, session_date=log.session_date, planned_minutes=20,
                                 delivered_minutes=18, corrects_log_id=log_id))
    _expect_integrity(two_corrections)
    _ = iid


def test_races_become_conflicts_not_500(env, monkeypatch):
    c, H, ds, cur = env
    from oqumap.services import fidelity, interventions, learning_loop, pilots

    # 1. two users create version N+1 at the same time (the second saw a stale 'latest')
    iv = c.post("/api/v1/interventions", json=intervention_body("RACE-1", cur), headers=H).json()
    c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={}, headers=H)
    c.post(f"/api/v1/interventions/{iv['id']}/versions", json={"title_ru": "v2"}, headers=H)
    c.post(f"/api/v1/interventions/{iv['id']}/versions/2/review", json={}, headers=H)
    real_get = interventions.get_version
    monkeypatch.setattr(interventions, "get_version", lambda s, i, version=None, prefer_reviewed=False:
                        real_get(s, i, 1) if version is None else real_get(s, i, version, prefer_reviewed))
    r = c.post(f"/api/v1/interventions/{iv['id']}/versions", json={"title_ru": "v3"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "concurrent_modification"
    monkeypatch.setattr(interventions, "get_version", real_get)
    # 2. auto-generated pilot code taken concurrently → retried with the next free code
    real_next = pilots._next_code
    calls = {"n": 0}

    def stale_code(s, org, skip=None):
        calls["n"] += 1
        return "PIL-M01" if calls["n"] == 1 else real_next(s, org, skip)
    monkeypatch.setattr(pilots, "_next_code", stale_code)
    peer = next(x for x in items(c.get("/api/v1/interventions", params={"q": "INT-PEER"}, headers=H).json()) if x["code"] == "INT-PEER")
    body = {"dataset_id": ds["id"], "title": "Гонка кодов", "intervention_id": peer["id"], "topic_id": topic(cur, "T3")}
    r = c.post("/api/v1/pilots", json=body, headers=H)
    assert r.status_code == 200 and r.json()["code"] != "PIL-M01" and calls["n"] >= 2
    monkeypatch.setattr(pilots, "_next_code", real_next)
    # 3. two simultaneous corrections of one fidelity log (pre-check passed for both)
    p3 = pilot_by_code(c, H, "PIL-M03")
    log = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", headers=H).json()["logs"][-1]
    corr = {"cohort_id": log["cohort_id"], "session_date": log["session_date"], "planned_minutes": 25, "delivered_minutes": 20,
            "corrects_log_id": log["id"]}
    assert c.post(f"/api/v1/pilots/{p3['id']}/fidelity-logs", json=corr, headers=H).status_code == 200
    monkeypatch.setattr(fidelity, "correction_exists", lambda s, lid: False)
    r = c.post(f"/api/v1/pilots/{p3['id']}/fidelity-logs", json=corr, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_corrected"
    # 4. next decision version created concurrently (stale latest version)
    dec = c.post("/api/v1/decisions", json={"dataset_id": ds["id"], "topic_id": topic(cur, "T3"), "target_group": "6А",
                                            "problem": "p", "hypothesis": "h", "action": "a", "responsible": "r"}, headers=H).json()
    p2 = pilot_by_code(c, H, "PIL-M02")
    with db.session_factory()() as s:
        s.get(mm.Pilot, p2["id"]).decision_id = dec["id"]
        s.add(m.Decision(org_id=s.get(m.Decision, dec["id"]).org_id, decision_group_id=dec["decision_group_id"], version=2,
                         dataset_id=ds["id"], dataset_version=1, target_group="x", problem="x", hypothesis="x", action="x",
                         responsible="x", status="draft"))
        s.commit()
    monkeypatch.setattr(learning_loop, "latest_decision", lambda s, g, o: s.get(m.Decision, dec["id"]))  # stale: version 1
    o2 = c.get(f"/api/v1/pilots/{p2['id']}/outcomes", headers=H).json()[0]
    r = c.post(f"/api/v1/pilots/{p2['id']}/conclusions", json={"outcome_id": o2["id"], "decision": "extend_data_collection",
                                                                "summary_ru": "Продолжаем сбор данных."}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "concurrent_modification"
    assert c.get(f"/api/v1/pilots/{p2['id']}/conclusions", headers=H).json() == []  # nothing half-written


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,key", [("/api/v1/interventions", "items"), ("/api/v1/pilots", "items"),
                                      ("/api/v1/quality/assessments", "assessments")])
def test_pagination_is_stable_and_complete(env, path, key):
    c, H, ds, cur = env
    params = {"dataset_id": ds["id"]} if "quality" in path else {}
    full = c.get(path, params={**params, "limit": 200}, headers=H).json()
    total = full["total"]
    ids = [r["assessment"]["assessment_id"] if key == "assessments" else r["id"] for r in full[key]]
    assert len(ids) == total == len(set(ids))
    seen = []
    for off in range(0, total, 2):
        page = c.get(path, params={**params, "limit": 2, "offset": off}, headers=H).json()
        assert page["limit"] == 2 and page["offset"] == off and page["total"] == total
        seen += [r["assessment"]["assessment_id"] if key == "assessments" else r["id"] for r in page[key]]
    assert seen == ids  # same order, no duplicates, nothing skipped
    assert c.get(path, params={**params, "limit": 2, "offset": off}, headers=H).json()[key] == \
        c.get(path, params={**params, "limit": 2, "offset": off}, headers=H).json()[key]
    assert c.get(path, params={**params, "limit": 0}, headers=H).status_code == 422
    assert c.get(path, params={**params, "limit": 500}, headers=H).status_code == 422
    _ = (assessment, cohorts, user_headers)
