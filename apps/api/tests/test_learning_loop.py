"""Follow-up and learning loop: hand-checkable statistics, ordered status rules (low fidelity is never
"ineffective"), comparability/attrition/causal ceiling, the full API flow from a quality signal to the next decision
version, portfolio aggregates without league tables, deterministic seed, permissions and tenant isolation."""

import hashlib
import json
import math

import numpy as np
import pytest
from conftest import login
from mhelpers import (
    assessment,
    cohorts,
    curriculum,
    dataset,
    intervention_body,
    items,
    objective,
    pilot_by_code,
    topic,
    user_headers,
)

from oqumap.demo import measurement_seed
from oqumap.services import learning_loop as L

# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_cluster_mean_hand_computed():
    # mean 3.5; cluster residual sums −4, 0, 4 → SE = sqrt(3/2 · 32) / 6; t(2) = 4.3027
    r = L.cluster_mean(np.array([1, 2, 3, 4, 5, 6.0]), np.array(list("aabbcc")), min_clusters=2)
    assert r["mean"] == 3.5 and r["se"] == pytest.approx(math.sqrt(48) / 6) and r["df"] == 2
    assert r["ci_low"] == pytest.approx(3.5 - 4.302653 * math.sqrt(48) / 6, rel=1e-5)
    few = L.cluster_mean(np.array([1, 2, 3.0]), np.array(list("aab")))
    assert few["ci_low"] is None and few["ci_unavailable_reason"] == "too_few_clusters" and few["mean"] == 2
    assert L.cluster_mean(np.array([]), np.array([]))["ci_unavailable_reason"] == "no_data"


def test_difference_of_means_uses_conservative_df():
    a = {"mean": 0.3, "se": 0.03, "n_clusters": 6, "ci_unavailable_reason": None}
    b = {"mean": 0.1, "se": 0.04, "n_clusters": 8, "ci_unavailable_reason": None}
    d = L.difference_of_means(a, b)
    assert d["estimate"] == pytest.approx(0.2) and d["se"] == pytest.approx(0.05) and d["df"] == 5
    assert L.difference_of_means({**a, "se": None, "ci_unavailable_reason": "too_few_clusters"}, b)["ci_low"] is None


BASE = dict(comparability_ok=True, has_outcome=True, analysis_supported=True, n_matched=200, min_matched=30, fidelity="high",
            attrition=0.05, ci=(0.02, 0.1), heterogeneous=False)


@pytest.mark.parametrize("change,expected", [
    ({}, "positive_signal"),
    ({"fidelity": "low"}, "invalid_due_to_fidelity"),
    ({"fidelity": "unknown"}, "invalid_due_to_fidelity"),
    ({"fidelity": "low", "ci": (-0.2, -0.1)}, "invalid_due_to_fidelity"),  # low fidelity + negative change ≠ "ineffective"
    ({"fidelity": "moderate"}, "mixed"),
    ({"heterogeneous": True}, "mixed"),
    ({"ci": (-0.02, 0.1)}, "not_confirmed"),
    ({"ci": (-0.2, -0.05)}, "not_confirmed"),
    ({"ci": (None, None)}, "needs_more_data"),
    ({"n_matched": 10}, "needs_more_data"),
    ({"attrition": 0.5}, "needs_more_data"),
    ({"has_outcome": False}, "needs_more_data"),
    ({"analysis_supported": False}, "needs_more_data"),
    ({"comparability_ok": False, "fidelity": "low"}, "invalid_due_to_comparability"),
])
def test_status_rules_are_ordered(change, expected):
    status, fired = L.decide_status(**{**BASE, **change})
    assert status == expected and fired


def test_no_status_means_ineffective():
    from oqumap.services.measurement_messages import STATUS_LABELS

    assert set(STATUS_LABELS) == {"positive_signal", "mixed", "not_confirmed", "needs_more_data", "invalid_due_to_fidelity",
                                  "invalid_due_to_comparability"}


def test_causal_level_comes_from_design_not_confidence():
    kw = dict(adjusted_used=False, baseline_imbalance=False, fidelity="high", attrition=0.05, differential=False, randomization_ok=True)
    assert L.achieved_causal_level("positive_signal", "single_group", "descriptive_change", **kw) == "descriptive_change"
    assert L.achieved_causal_level("positive_signal", "matched_comparison", "adjusted_association", **{**kw, "adjusted_used": True}) == "adjusted_association"
    assert L.achieved_causal_level("positive_signal", "matched_comparison", "adjusted_association", **kw) == "descriptive_comparison"
    assert L.achieved_causal_level("positive_signal", "cluster_randomized", "causal_estimate", **kw) == "causal_estimate"
    assert L.achieved_causal_level("positive_signal", "cluster_randomized", "causal_estimate", **{**kw, "attrition": 0.3}) == "descriptive_comparison"
    assert L.achieved_causal_level("positive_signal", "cluster_randomized", "causal_estimate", **{**kw, "fidelity": "moderate"}) != "causal_estimate"
    assert L.achieved_causal_level("invalid_due_to_fidelity", "cluster_randomized", "causal_estimate", **kw) == "none"


def test_demo_generator_is_deterministic():
    a = measurement_seed.generate_rows()
    b = measurement_seed.generate_rows()
    assert a == b
    digest = hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()
    assert digest == hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()
    assert measurement_seed.generate_rows(seed=1) != a
    assert {r["assessment_code"] for r in a} == {"PRE-2026M", "DIAG-BASE", "DIAG-END"}


# ---------------------------------------------------------------------------
# Seeded outcomes (shared, read-only)
# ---------------------------------------------------------------------------


def test_seeded_outcomes_have_known_behaviour(client, H):
    p1 = pilot_by_code(client, H, "PIL-M01")
    p2 = pilot_by_code(client, H, "PIL-M02")
    o1 = client.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=H).json()[0]
    o2 = client.get(f"/api/v1/pilots/{p2['id']}/outcomes", headers=H).json()[0]
    assert o1["status"] == "positive_signal" and o1["causal_level"]["code"] == "adjusted_association"
    assert o1["result"]["primary"]["source"] == "adjusted" and o1["result"]["primary"]["ci_low"] > 0
    assert o1["result"]["comparability"]["code"] == "identical_form"
    assert o1["result"]["arms"]["intervention"]["matched"] <= o1["result"]["arms"]["intervention"]["assigned"]
    # low fidelity: a positive change is shown, but the status says "not interpretable", never "ineffective"
    assert o2["status"] == "invalid_due_to_fidelity" and o2["causal_level"]["code"] == "none"
    assert o2["result"]["primary"]["estimate"] > 0 and o2["fidelity"]["code"] == "low"
    assert "ни её эффективности, ни неэффективности" in o2["result"]["interpretation_ru"]
    assert o2["status_label"]["label_ru"].startswith("Не интерпретируется")
    assert "NaN" not in json.dumps(o1) and "Infinity" not in json.dumps(o2)


# ---------------------------------------------------------------------------
# Full flow on a separate database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flow(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    return c, H, ds, curriculum(c, H, ds["id"])


def _pilot_body(ds, cur, iv_id, **kw):
    body = {"dataset_id": ds["id"], "title": "Пилот сквозного сценария", "intervention_id": iv_id, "topic_id": topic(cur, "T3"),
            "objective_id": objective(cur, "DEMO-M6-3.1"), "primary_outcome_ru": "Доля баллов по цели 3.1",
            "design": "matched_comparison", "assignment_unit": "cohort",
            "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "А")]
            + [{"cohort_id": x, "arm": "comparison"} for x in cohorts(cur, "Б")],
            "baseline_assessment_id": assessment(cur, "DIAG-BASE"), "start_date": "2026-09-21", "end_date": "2026-10-23",
            "follow_up_due": "2026-10-30", "owner": "Методист", "minutes_per_session": 20, "sessions_per_week": 3, "duration_weeks": 5,
            "analysis_plan": {"adjustment": "none"}}
    body.update(kw)
    return body


def test_end_to_end_from_quality_signal_to_next_decision_version(flow):
    c, H, ds, cur = flow
    # 1. the methodist sees an assessment-quality problem
    qa = c.get("/api/v1/quality/assessments", params={"dataset_id": ds["id"]}, headers=H).json()["assessments"]
    diag = next(a for a in qa if a["assessment"]["code"] == "DIAG-BASE")
    assert diag["n_flagged_items"] >= 3
    items = c.get(f"/api/v1/quality/assessments/{diag['assessment']['assessment_id']}/items",
                  params={"flag": "negative_discrimination"}, headers=H).json()["items"]
    assert [i["code"] for i in items] == ["Q05"]
    # 2. a decision exists for the topic; 3. an intervention is created and reviewed
    dec = c.post("/api/v1/decisions", json={"dataset_id": ds["id"], "topic_id": topic(cur, "T3"), "target_group": "6А классы",
                                            "problem": "Ошибки сложения дробей", "hypothesis": "Модель поможет",
                                            "action": "Пилот модели", "responsible": "Методист"}, headers=H).json()
    iv = c.post("/api/v1/interventions", json=intervention_body("FLOW-1", cur, minutes_per_session=20, sessions_per_week=3,
                                                                duration_weeks=5, evidence_level="observational",
                                                                targets=[{"target_type": "objective", "target_id": objective(cur, "DEMO-M6-3.1")},
                                                                         {"target_type": "misconception", "misconception_code": "add_across"}]),
                headers=H).json()
    c.post(f"/api/v1/interventions/{iv['id']}/versions/1/review", json={"note": "ok"}, headers=H)
    sha_v1 = c.get(f"/api/v1/interventions/{iv['id']}", headers=H).json()["current"]["content_sha256"]
    # 4. a valid pilot is launched
    p = c.post("/api/v1/pilots", json=_pilot_body(ds, cur, iv["id"], decision_id=dec["id"]), headers=H).json()
    assert p["causal_ceiling"]["code"] == "descriptive_comparison"
    assert c.post(f"/api/v1/pilots/{p['id']}/follow-up", json={}, headers=H).status_code == 409  # not running yet
    for to in ("ready", "active"):
        p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H).json()
    # 5. fidelity is recorded (all sessions)
    from datetime import date, timedelta

    days = [date(2026, 9, 21) + timedelta(days=i) for i in range(33) if (date(2026, 9, 21) + timedelta(days=i)).weekday() in (0, 2, 4)]
    for row in [x for x in p["cohorts"] if x["arm"] == "intervention"]:
        for d in days:
            r = c.post(f"/api/v1/pilots/{p['id']}/fidelity-logs", json={
                "cohort_id": row["cohort_id"], "session_date": d.isoformat(), "planned_minutes": 20, "delivered_minutes": 20,
                "activities_planned": 3, "activities_completed": 3, "learners_present": row["n_learners"] - 1,
                "learners_assigned": row["n_learners"], "adherence": [{"key": "model", "label": "Модель", "done": True}]}, headers=H)
            assert r.status_code == 200, r.text
    assert c.get(f"/api/v1/pilots/{p['id']}/fidelity", headers=H).json()["overall"]["classification"]["code"] == "high"
    p = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": "completed"}, headers=H).json()
    # 6. a follow-up assessment is added → honest result
    o = c.post(f"/api/v1/pilots/{p['id']}/follow-up", json={"outcome_assessment_id": assessment(cur, "DIAG-END")}, headers=H).json()
    assert o["status"] == "positive_signal", o["result"]["reasons"]
    assert o["causal_level"]["code"] == "descriptive_comparison"  # no pre-registered adjustment → no "adjusted" claim
    assert o["result"]["adjusted"]["unavailable_reason"] == "not_preregistered" and o["result"]["primary"]["source"] == "raw"
    assert any(r["code"] == "observational_comparison" for r in o["result"]["reasons"])
    again = c.post(f"/api/v1/pilots/{p['id']}/follow-up", json={}, headers=H).json()
    assert again["id"] == o["id"]  # same inputs → same immutable outcome
    # 7. a conclusion is saved with evidence → next decision version + proposed evidence entry
    log_id = c.get(f"/api/v1/pilots/{p['id']}/fidelity", headers=H).json()["logs"][0]["id"]
    assert c.post(f"/api/v1/pilots/{p['id']}/conclusions", json={"outcome_id": o["id"], "decision": "modify", "summary_ru": "Короткий вывод для теста",
                                                                  "evidence_ids": ["not-an-id"]}, headers=H).status_code == 404
    con = c.post(f"/api/v1/pilots/{p['id']}/conclusions", json={
        "outcome_id": o["id"], "decision": "modify", "summary_ru": "Сигнал положительный; модель стоит доработать для смешанных чисел.",
        "lessons_ru": "Формат 3×20 минут выполним.", "open_questions": ["Сохранится ли эффект через месяц?"],
        "evidence_ids": [log_id], "next_action_ru": "Добавить этап со смешанными числами (версия 2)."}, headers=H).json()
    assert con["next_decision_id"] and con["evidence_entry"]["review_status"] == "proposed"
    assert set(con["evidence_ids"]) == {o["id"], log_id}
    nd = c.get(f"/api/v1/decisions/{con['next_decision_id']}", headers=H).json()
    assert nd["decision_group_id"] == dec["decision_group_id"] and nd["version"] == dec["version"] + 1 and nd["status"] == "draft"
    assert nd["snapshot"]["learning_loop"]["outcome_status"] == "positive_signal" and "смешанными" in nd["action"]
    assert [h["status"] for h in nd["history"]] == ["superseded", "draft"]
    # 8. evidence enters the library only after human approval, without touching the version
    before = c.get(f"/api/v1/interventions/{iv['id']}/evidence", headers=H).json()
    assert before["accepted_entries"] == 0 and before["proposed_synthetic_entries"] == 1  # synthetic dataset
    sug0 = c.get("/api/v1/interventions/suggest", params={"objective_id": objective(cur, "DEMO-M6-3.1")}, headers=H).json()
    assert not any(x["code"] == "accepted_positive_signals" for s in sug0["suggestions"] if s["code"] == "FLOW-1" for x in s["components"])
    assert c.post(f"/api/v1/intervention-evidence/{con['evidence_entry']['id']}/review", json={"accept": True},
                  headers=user_headers(["methodist"])).status_code == 403
    after = c.post(f"/api/v1/intervention-evidence/{con['evidence_entry']['id']}/review", json={"accept": True, "note": "ok"}, headers=H).json()
    assert after["accepted_synthetic_entries"] == 1 and after["by_status_synthetic"] == {"positive_signal": 1}
    assert after["accepted_entries"] == 0 and after["by_status"] == {} and not after["repeated_positive_signal"]
    assert c.post(f"/api/v1/intervention-evidence/{con['evidence_entry']['id']}/review", json={"accept": True}, headers=H).status_code == 409
    assert c.get(f"/api/v1/interventions/{iv['id']}", headers=H).json()["current"]["content_sha256"] == sha_v1
    sug = c.get("/api/v1/interventions/suggest", params={"objective_id": objective(cur, "DEMO-M6-3.1")}, headers=H).json()
    flow_s = next(s for s in sug["suggestions"] if s["code"] == "FLOW-1")
    # synthetic evidence is shown (0 points) and never boosts the score; real evidence: tests/test_integrity.py
    assert {x["code"]: x["points"] for x in flow_s["components"]}.get("synthetic_demo_signals") == 0
    assert not any(x["code"] == "accepted_positive_signals" for x in flow_s["components"])
    # 9. the organisation sees what it learned
    summ = c.get("/api/v1/learning/summary", params={"dataset_id": ds["id"]}, headers=H).json()
    assert any(q["question"] == "Сохранится ли эффект через месяц?" for q in summ["open_questions"])
    assert any(lsn["lessons_ru"] == "Формат 3×20 минут выполним." for lsn in summ["lessons"])


def test_comparability_and_small_samples_are_honest(flow):
    c, H, ds, cur = flow
    iv = next(r for r in items(c.get("/api/v1/interventions", headers=H).json()) if r["code"] == "INT-PEER")
    # baseline on F-PRE (scale S-PRE) vs outcome on F-T3-DIAG: unlinked scales → no change computed
    body = _pilot_body(ds, cur, iv["id"], design="single_group", objective_id=None, baseline_assessment_id=assessment(cur, "PRE-2026M"),
                       cohorts=[{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "В")], start_date="2026-09-08")
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    for to in ("ready", "active"):
        c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H)
    o = c.post(f"/api/v1/pilots/{p['id']}/follow-up", json={"outcome_assessment_id": assessment(cur, "DIAG-END")}, headers=H).json()
    assert o["status"] == "invalid_due_to_comparability" and o["result"]["primary"]["estimate"] is None
    assert o["result"]["comparability"]["code"] == "forms_not_comparable" and o["interim"]
    # one class: too few learners / clusters → needs more data (the point estimate stays descriptive)
    small = _pilot_body(ds, cur, iv["id"], design="single_group", cohorts=[{"cohort_id": cohorts(cur, "В")[0], "arm": "intervention"}],
                        analysis_plan={"min_matched_learners": 30})
    p2 = c.post("/api/v1/pilots", json=small, headers=H).json()
    for to in ("ready", "active"):
        c.post(f"/api/v1/pilots/{p2['id']}/transition", json={"to_status": to}, headers=H)
    o2 = c.post(f"/api/v1/pilots/{p2['id']}/follow-up", json={"outcome_assessment_id": assessment(cur, "DIAG-END")}, headers=H).json()
    assert o2["status"] == "needs_more_data" and o2["result"]["status_rules_fired"] == ["too_few_matched"]
    assert o2["result"]["n_matched"] < 30 and o2["result"]["primary"]["ci_low"] is None  # 1 class → no interval
    assert o2["result"]["primary"]["estimate"] is not None  # descriptive value stays visible
    # outcome measured before the pilot started is rejected
    r = c.post(f"/api/v1/pilots/{p2['id']}/follow-up", json={"outcome_assessment_id": assessment(cur, "DIAG-BASE")}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "outcome_before_start"


def test_stop_after_low_fidelity_requires_structured_operational_basis(flow):
    c, H, ds, cur = flow
    p2 = pilot_by_code(c, H, "PIL-M02")
    o2 = c.get(f"/api/v1/pilots/{p2['id']}/outcomes", headers=H).json()[0]
    url = f"/api/v1/pilots/{p2['id']}/conclusions"
    base = {"outcome_id": o2["id"], "create_next_decision_version": False}

    def post(**kw):
        return c.post(url, json={**base, **kw}, headers=H)

    # the text is irrelevant: mentioning "реализация" no longer passes, and the structure decides
    r = post(decision="stop", summary_ru="Реализация низкая, останавливаем.", stop_reason_code="resource_constraints")
    assert r.status_code == 422 and r.json()["error"]["code"] == "stop_requires_operational_basis"
    assert post(decision="stop", summary_ru="Останавливаем пилот.", decision_basis="operational",
                acknowledged_limitation_codes=["no_effectiveness_conclusion", "requires_new_pilot_or_implementation"]
                ).json()["error"]["code"] == "stop_reason_required"
    assert post(decision="continue", summary_ru="Интервенция работает, продолжаем.", decision_basis="evidence_supports"
                ).json()["error"]["code"] == "basis_inconsistent_with_outcome"
    assert post(decision="continue", summary_ru="Продолжаем наблюдение.", acknowledged_limitation_codes=["made_up"]
                ).json()["error"]["code"] == "unknown_limitation_code"
    ok_stop = post(decision="stop", summary_ru="Интервенция не работает, прекращаем.", decision_basis="operational",
                   stop_reason_code="implementation_not_feasible",
                   acknowledged_limitation_codes=["no_effectiveness_conclusion", "requires_new_pilot_or_implementation", "fidelity_low"])
    assert ok_stop.status_code == 200, ok_stop.text  # allowed: structurally an operational stop, not a verdict
    body = ok_stop.json()
    assert body["decision_basis"] == "operational" and body["stop_reason_code"] == "implementation_not_feasible"
    assert "no_effectiveness_conclusion" in body["acknowledged_limitation_codes"]
    ok = post(decision="extend_data_collection", summary_ru="Реализация низкая: проверить эффективность не удалось.").json()
    assert ok["next_decision_id"] is None and ok["evidence_entry"]["outcome_status"] == "invalid_due_to_fidelity"
    # accepting an uninterpretable result requires a note
    rv = c.post(f"/api/v1/intervention-evidence/{ok['evidence_entry']['id']}/review", json={"accept": True}, headers=H)
    assert rv.status_code == 422


def test_portfolio_aggregates_without_league_tables(flow, monkeypatch):
    from datetime import date

    from oqumap.services import clock

    monkeypatch.setattr(clock, "today", lambda: date(2027, 1, 5))  # a date after PIL-M03's follow-up deadline
    c, H, ds, cur = flow
    r = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"], "as_of": "2027-01-05"}, headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["best_intervention"] is None and d["best_intervention_reason"] == "not_shown_without_comparability_and_repetition"
    assert d["counts_by_status"]["completed"] >= 2 and d["counts_by_status"]["draft"] >= 1
    assert d["fidelity_distribution"]["high"] >= 1 and d["fidelity_distribution"]["low"] >= 1
    assert d["outcome_distribution"]["positive_signal"] >= 1 and d["outcome_distribution"]["invalid_due_to_fidelity"] >= 1
    assert "PIL-M03" in {x["code"] for x in d["follow_ups"]["overdue"]}
    actions = {(a["code"], a["action"]) for a in d["action_queue"]}
    assert ("PIL-M03", "run_follow_up_overdue") in actions and ("PIL-M04", "complete_protocol") in actions
    assert any(m["code"] == "PIL-M02" and "adequate_implementation" in m["missing"] for m in d["missing_for_conclusions"])
    t3 = next(t for t in d["coverage"]["topics"] if t["code"] == "T3")
    assert t3["pilots"] >= 4 and t3["has_interventions"] and d["coverage"]["topics_total"] == 8
    text = json.dumps(d, ensure_ascii=False)
    assert "school_code" not in text and "teacher" not in text and "rank" not in text  # no league tables
    assert all(lim["message_ru"] for lim in d["limitations"])


def test_outcome_detail_roles_and_isolation(flow):
    c, H, ds, cur = flow
    p1 = pilot_by_code(c, H, "PIL-M01")
    V = login(c, "viewer")
    ov = c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=V).json()[0]
    assert ov["result"]["cohorts"] is None and not ov["result"]["cohort_detail_visible"]
    oh = c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=H).json()[0]
    assert oh["result"]["cohorts"] and all(r["n_matched"] is None or r["n_matched"] >= 10 for r in oh["result"]["cohorts"])
    assert c.post(f"/api/v1/pilots/{p1['id']}/follow-up", json={}, headers=V).status_code == 403
    assert c.post(f"/api/v1/pilots/{p1['id']}/conclusions", json={"outcome_id": oh["id"], "decision": "continue",
                                                                   "summary_ru": "Попытка наблюдателя"}, headers=V).status_code == 403
    O = login(c, "other_org")
    entry = c.get(f"/api/v1/interventions/{p1['intervention_id']}/evidence", headers=H).json()["entries"][0]["id"]
    for r in (c.get(f"/api/v1/pilots/{p1['id']}/outcomes", headers=O),
              c.post(f"/api/v1/pilots/{p1['id']}/follow-up", json={}, headers=O),
              c.get(f"/api/v1/pilots/{p1['id']}/conclusions", headers=O),
              c.post(f"/api/v1/pilots/{p1['id']}/conclusions", json={"outcome_id": oh["id"], "decision": "continue",
                                                                      "summary_ru": "Чужая организация"}, headers=O),
              c.post(f"/api/v1/intervention-evidence/{entry}/review", json={"accept": False}, headers=O),
              c.get("/api/v1/learning/summary", params={"dataset_id": ds["id"]}, headers=O),
              c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"]}, headers=O)):
        assert r.status_code == 404, r.text
    other = c.get("/api/v1/portfolio/interventions", headers=O).json()
    assert other["pilots"] == [] and sum(other["counts_by_status"].values()) == 0
    assert c.get("/api/v1/learning/summary", headers=O).json()["lessons"] == []


def test_audit_trail_has_no_free_text_notes(flow):
    from oqumap import db
    from oqumap import models as m

    with db.session_factory()() as s:
        rows = s.query(m.AuditLog).filter(m.AuditLog.action.in_(["fidelity.log", "pilot.conclusion", "pilot.follow_up"])).all()
        assert rows
        blob = json.dumps([r.details for r in rows], ensure_ascii=False)
    assert "Сократили" not in blob and "Сигнал положительный" not in blob and "token" not in blob.lower()
