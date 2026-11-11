"""Round 2 / P1-7: chronology and design invariants of the pilot protocol, protocol-only designs."""

from datetime import date

import pytest
from conftest import login
from mhelpers import assessment, cohorts, curriculum, dataset, items, topic

from oqumap.services import clock


@pytest.fixture(scope="module")
def ctx(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    iv = next(r for r in items(c.get("/api/v1/interventions", headers=H).json()) if r["code"] == "INT-PEER")
    return c, H, ds, cur, iv


def _body(ds, cur, iv, **kw):
    b = {"dataset_id": ds["id"], "title": "Протокол", "intervention_id": iv["id"], "topic_id": topic(cur, "T3"),
         "primary_outcome_ru": "Доля баллов", "design": "single_group",
         "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "Г")[:2]],
         "baseline_assessment_id": assessment(cur, "DIAG-END"), "start_date": "2027-01-11", "end_date": "2027-02-12",
         "follow_up_due": "2027-02-19", "owner": "Методист", "sessions_per_week": 3, "duration_weeks": 5}
    b.update(kw)
    return b


def _validation(c, H, body):
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    return p, {e["code"] for e in p["validation"]["errors"]}, {w["code"] for w in p["validation"]["warnings"]}


def test_chronology_invariants(ctx):
    c, H, ds, cur, iv = ctx
    _, err, _ = _validation(c, H, _body(ds, cur, iv, follow_up_due="2027-02-01"))
    assert "follow_up_before_end" in err
    _, err, _ = _validation(c, H, _body(ds, cur, iv, outcome_assessment_id=assessment(cur, "DIAG-BASE")))
    assert "outcome_before_start" in err
    p, err, warn = _validation(c, H, _body(ds, cur, iv, duration_weeks=12))
    assert not err and "duration_calendar_mismatch" in warn  # warning, not a block
    _, err, _ = _validation(c, H, _body(ds, cur, iv, analysis_plan={"primary_estimand": "difference_in_mean_changes"}))
    assert "estimand_design_mismatch" in err
    _, err, _ = _validation(c, H, _body(ds, cur, iv, design="matched_comparison",
                                        cohorts=[{"cohort_id": cohorts(cur, "Г")[0], "arm": "intervention"},
                                                 {"cohort_id": cohorts(cur, "Г")[1], "arm": "comparison"}],
                                        analysis_plan={"primary_estimand": "mean_paired_change"}))
    assert "estimand_design_mismatch" in err


def test_completing_before_planned_end_needs_override(ctx, monkeypatch):
    c, H, ds, cur, iv = ctx
    monkeypatch.setattr(clock, "today", lambda: date(2027, 1, 20))
    p = c.post("/api/v1/pilots", json=_body(ds, cur, iv), headers=H).json()
    for to in ("ready", "active"):
        assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H).status_code == 200
    r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "completed"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "end_date_in_future"
    r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "completed", "override_future_end": True}, headers=H)
    assert r.status_code == 409  # override without a reason is not enough
    r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "completed", "override_future_end": True,
                                                             "note": "Школы закрыли четверть раньше"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "completed"


@pytest.mark.parametrize("design", ["interrupted_time_series", "stepped_wedge"])
def test_protocol_only_designs_need_acknowledgement_and_never_compute(ctx, design):
    c, H, ds, cur, iv = ctx
    extra = {"pre_period_assessment_ids": [assessment(cur, a) for a in ("PRE-2026M", "DIAG-BASE", "DIAG-END")]} \
        if design == "interrupted_time_series" else {}
    p, err, warn = _validation(c, H, _body(ds, cur, iv, design=design, **extra))
    assert p["analysis_mode"] == "protocol_only_external_analysis"
    assert p["causal_ceiling"]["code"] == "external_analysis_required"
    assert "external_analysis_not_acknowledged" in err and "protocol_only_external_analysis" in warn
    p2, err2, _ = _validation(c, H, _body(ds, cur, iv, design=design, analysis_plan={"external_analysis_acknowledged": True}, **extra))
    assert "external_analysis_not_acknowledged" not in err2
    if design == "interrupted_time_series":
        assert not err2
        for to in ("ready", "active"):
            assert c.post(f"/api/v1/pilots/{p2['id']}/transition", json={"to_status": to}, headers=H).status_code == 200
        r = c.post(f"/api/v1/pilots/{p2['id']}/follow-up", json={}, headers=H)
        assert r.status_code == 409 and r.json()["error"]["code"] == "protocol_only_external_analysis"
