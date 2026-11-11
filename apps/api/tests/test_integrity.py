"""Round 2 / P1-4, P1-5, P1-6: snapshot integrity on activation, synthetic vs real evidence, item tenant scope."""

import json
from datetime import date, timedelta

import pytest
from conftest import login
from mhelpers import DEMO_ORG, OTHER_ORG, assessment, cohorts, curriculum, dataset, intervention_body, items, objective, topic

from oqumap import db
from oqumap import measurement_models as mm
from oqumap import models as m


@pytest.fixture(scope="module")
def env(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    return c, H, ds, curriculum(c, H, ds["id"])


def _ready_pilot(c, H, ds, cur, title="Пилот целостности"):
    iv = next(r for r in items(c.get("/api/v1/interventions", headers=H).json()) if r["code"] == "INT-PEER")
    body = {"dataset_id": ds["id"], "title": title, "intervention_id": iv["id"], "topic_id": topic(cur, "T3"),
            "primary_outcome_ru": "Доля баллов", "design": "single_group",
            "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "Г")[:2]],
            "baseline_assessment_id": assessment(cur, "DIAG-END"), "start_date": "2026-11-02", "end_date": "2026-12-04",
            "follow_up_due": "2026-12-11", "owner": "Методист", "sessions_per_week": 3, "duration_weeks": 5}
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "ready"}, headers=H).status_code == 200
    return p


def _activate(c, H, pid):
    return c.post(f"/api/v1/pilots/{pid}/transition", json={"to_status": "active"}, headers=H)


@pytest.mark.parametrize("tamper,expected", [
    ("snapshot_only", {"stored_snapshot_hash", "snapshot_canonical_content"}),
    ("snapshot_and_hash", {"snapshot_canonical_content"}),
    ("version_content", {"reviewed_version_modified"}),
    ("version_reference", {"snapshot_version_reference"}),
])
def test_tampered_snapshot_blocks_activation(env, tamper, expected):
    c, H, ds, cur = env
    p = _ready_pilot(c, H, ds, cur, f"Пилот {tamper}")
    from oqumap.services.pilots import _sha

    with db.session_factory()() as s:
        pl = s.get(mm.Pilot, p["id"])
        v = s.get(mm.InterventionVersion, pl.intervention_version_id)
        original = (dict(pl.intervention_snapshot), pl.snapshot_sha256, v.instructions_ru)
        if tamper.startswith("snapshot"):
            snap = dict(pl.intervention_snapshot)
            snap["instructions_ru"] = "ПОДМЕНЁННАЯ ИНСТРУКЦИЯ"
            pl.intervention_snapshot = snap
            if tamper == "snapshot_and_hash":
                pl.snapshot_sha256 = _sha(snap)
        elif tamper == "version_content":
            v.instructions_ru = "ПОДМЕНЁННАЯ ИНСТРУКЦИЯ"
        else:
            snap = dict(pl.intervention_snapshot)
            snap["version"] = 99
            pl.intervention_snapshot = snap
            pl.snapshot_sha256 = _sha(snap)
        s.commit()
    r = _activate(c, H, p["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "snapshot_mismatch", r.text
    assert expected <= set(r.json()["error"]["details"]["failed_checks"])
    assert c.get(f"/api/v1/pilots/{p['id']}", headers=H).json()["status"] == "ready"  # not activated
    with db.session_factory()() as s:
        rows = s.query(m.AuditLog).filter(m.AuditLog.action == "pilot.snapshot_mismatch", m.AuditLog.entity_id == p["id"]).all()
        assert rows and "ПОДМЕНЁННАЯ" not in json.dumps([x.details for x in rows], ensure_ascii=False)
        # restore so later tests see a clean library
        pl = s.get(mm.Pilot, p["id"])
        v = s.get(mm.InterventionVersion, pl.intervention_version_id)
        pl.intervention_snapshot, pl.snapshot_sha256, v.instructions_ru = original
        s.commit()
    assert _activate(c, H, p["id"]).status_code == 200  # intact snapshot activates


def _positive_pilot(c, H, ds, cur, iv_id, title):
    body = {"dataset_id": ds["id"], "title": title, "intervention_id": iv_id, "topic_id": topic(cur, "T3"),
            "objective_id": objective(cur, "DEMO-M6-3.1"), "primary_outcome_ru": "Доля баллов по цели 3.1",
            "design": "matched_comparison", "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "А")]
            + [{"cohort_id": x, "arm": "comparison"} for x in cohorts(cur, "Б")],
            "baseline_assessment_id": assessment(cur, "DIAG-BASE"), "start_date": "2026-09-21", "end_date": "2026-10-23",
            "follow_up_due": "2026-10-30", "owner": "Методист", "minutes_per_session": 20, "sessions_per_week": 3, "duration_weeks": 5}
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    for to in ("ready", "active"):
        p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H).json()
    days = [date(2026, 9, 21) + timedelta(days=i) for i in range(33) if (date(2026, 9, 21) + timedelta(days=i)).weekday() in (0, 2, 4)]
    for row in [x for x in p["cohorts"] if x["arm"] == "intervention"]:
        for d in days:
            c.post(f"/api/v1/pilots/{p['id']}/fidelity-logs", json={
                "cohort_id": row["cohort_id"], "session_date": d.isoformat(), "planned_minutes": 20, "delivered_minutes": 20,
                "activities_planned": 3, "activities_completed": 3, "learners_present": row["n_learners"] - 1,
                "learners_assigned": row["n_learners"]}, headers=H)
    c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "completed"}, headers=H)
    o = c.post(f"/api/v1/pilots/{p['id']}/follow-up", json={"outcome_assessment_id": assessment(cur, "DIAG-END")}, headers=H).json()
    assert o["status"] == "positive_signal", o["result"]["reasons"]
    con = c.post(f"/api/v1/pilots/{p['id']}/conclusions", json={
        "outcome_id": o["id"], "decision": "continue", "decision_basis": "evidence_supports",
        "summary_ru": "Положительный сигнал при высокой реализации.", "create_next_decision_version": False}, headers=H).json()
    r = c.post(f"/api/v1/intervention-evidence/{con['evidence_entry']['id']}/review", json={"accept": True, "note": "ok"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_synthetic_evidence_never_boosts_but_real_evidence_does(env):
    c, H, ds, cur = env
    # a real organisation that imported a synthetic dataset: still no boost from synthetic pilots
    with db.session_factory()() as s:
        s.get(m.Organization, DEMO_ORG).is_demo = False
        s.commit()
    sug = c.get("/api/v1/interventions/suggest", params={"misconception": "add_across", "topic_id": topic(cur, "T3")}, headers=H).json()
    strips = next(x for x in sug["suggestions"] if x["code"] == "INT-STRIPS")
    comps = {x["code"]: x["points"] for x in strips["components"]}
    assert comps.get("synthetic_demo_signals") == 0 and "accepted_positive_signals" not in comps
    syn_iv = c.post("/api/v1/interventions", json=intervention_body("SYN-1", cur, evidence_level="observational",
                                                                     targets=[{"target_type": "objective", "target_id": objective(cur, "DEMO-M6-3.1")}]),
                    headers=H).json()
    c.post(f"/api/v1/interventions/{syn_iv['id']}/versions/1/review", json={}, headers=H)
    for i in range(2):
        ev = _positive_pilot(c, H, ds, cur, syn_iv["id"], f"Синтетический пилот {i}")
    assert ev["accepted_entries"] == 0 and ev["accepted_synthetic_entries"] == 2
    assert not ev["repeated_positive_signal"] and ev["synthetic_comparable_positive_signals"] == 2
    pf = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"]}, headers=H).json()
    assert "SYN-1" not in {x["code"] for x in pf["interventions_with_repeated_signals"]}
    assert "SYN-1" in {x["code"] for x in pf["synthetic_evidence"]["repeated_signals_demo_only"]}
    assert pf["synthetic_evidence"]["counts_toward_recommendations"] is False
    # the same dataset treated as real observed data: accepted entries count and repeat
    with db.session_factory()() as s:
        s.get(m.Dataset, ds["id"]).is_synthetic = False
        s.commit()
    real_iv = c.post("/api/v1/interventions", json=intervention_body("REAL-1", cur, evidence_level="observational",
                                                                      targets=[{"target_type": "objective", "target_id": objective(cur, "DEMO-M6-3.1")}]),
                     headers=H).json()
    c.post(f"/api/v1/interventions/{real_iv['id']}/versions/1/review", json={}, headers=H)
    for i in range(2):
        ev = _positive_pilot(c, H, ds, cur, real_iv["id"], f"Реальный пилот {i}")
    assert ev["accepted_entries"] == 2 and ev["repeated_positive_signal"] and ev["accepted_synthetic_entries"] == 0
    sug = c.get("/api/v1/interventions/suggest", params={"objective_id": objective(cur, "DEMO-M6-3.1")}, headers=H).json()
    by_code = {x["code"]: {y["code"]: y["points"] for y in x["components"]} for x in sug["suggestions"]}
    assert by_code["REAL-1"]["accepted_positive_signals"] == 1.0
    assert "accepted_positive_signals" not in by_code["SYN-1"] and by_code["SYN-1"]["synthetic_demo_signals"] == 0
    pf = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"]}, headers=H).json()
    assert "REAL-1" in {x["code"] for x in pf["interventions_with_repeated_signals"]}
    with db.session_factory()() as s:  # restore flags
        s.get(m.Dataset, ds["id"]).is_synthetic = True
        s.get(m.Organization, DEMO_ORG).is_demo = True
        s.commit()


def test_item_from_shared_programme_is_visible_only_through_own_assessments(env):
    c, H, ds, cur = env
    with db.session_factory()() as s:
        pv = m.ProgramVersion(org_id=None, subject="math", grade=6, language="ru", version="shared-1", title="Общая программа", source="t")
        s.add(pv)
        s.flush()
        scale = m.Scale(code="S-SHARED", name="shared", linking_method="identical_form")
        item = m.Item(program_version_id=pv.id, code="SH1", item_type="single_choice", stem_ru="Секретное условие", stem_kz="x",
                      options=[{"key": "A", "text": "ответ", "correct": True, "misconception": None}], answer_key="A")
        s.add_all([scale, item])
        s.flush()
        form = m.AssessmentForm(program_version_id=pv.id, code="F-SHARED", name="shared", scale_id=scale.id, stage_hint="post")
        s.add(form)
        s.flush()
        s.add(m.FormItem(form_id=form.id, item_id=item.id, position=1))
        own = m.Dataset(org_id=DEMO_ORG, program_version_id=pv.id, code="shared_ds", name_ru="Общий набор", name_kz="x", is_synthetic=True)
        s.add(own)
        s.flush()
        s.add(m.Assessment(org_id=DEMO_ORG, dataset_id=own.id, form_id=form.id, code="SH-POST", stage="post"))
        s.commit()
        item_id, own_id = item.id, own.id
    r = c.get(f"/api/v1/quality/items/{item_id}", headers=H)
    assert r.status_code == 200 and r.json()["item"]["answer_key"] == "A"
    O = login(c, "other_org")
    for params in ({}, {"dataset_id": own_id}):
        rr = c.get(f"/api/v1/quality/items/{item_id}", params=params, headers=O)
        assert rr.status_code == 404 and "Секретное" not in rr.text and "answer_key" not in rr.text
    # dataset scope is strict even for the owner: the item is not in measurement_loop
    assert c.get(f"/api/v1/quality/items/{item_id}", params={"dataset_id": ds["id"]}, headers=H).status_code == 404
    _ = OTHER_ORG
