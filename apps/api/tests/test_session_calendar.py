"""Round 2 / 15: planned session calendar — draft generation, edits before activation, history after activation,
reschedule ≠ missed session, fidelity against sessions planned up to as_of."""

from datetime import date

import pytest
from conftest import login
from mhelpers import assessment, cohorts, curriculum, dataset, items, pilot_by_code, topic, user_headers

from oqumap.services import clock
from oqumap.services import fidelity as F
from oqumap.services.sessions import draft_schedule


def test_draft_schedule_respects_weekdays_and_blackouts():
    d = draft_schedule(date(2026, 11, 2), date(2026, 11, 15), [0, 2, 4], {date(2026, 11, 4)})
    assert d == [date(2026, 11, 2), date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 11), date(2026, 11, 13)]


def test_fidelity_counts_planned_sessions_and_not_rescheduled_ones():
    cal = {"c1": [(date(2026, 11, 2), 20, "completed"), (date(2026, 11, 4), 20, "rescheduled"), (date(2026, 11, 6), 30, "planned"),
                  (date(2026, 11, 20), 20, "planned")]}
    logs = [F.LogRow("c1", date(2026, 11, 2), 20, 20, 0, 0, None, None, [], "none")]
    res = F.compute(["c1"], logs, 99, 20, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 10), cal)
    m = res["per_cohort"]["c1"]
    assert res["expected_source"] == "calendar"
    assert m["expected_sessions"] == 2  # 02.11 and 06.11; the rescheduled 04.11 and future 20.11 are not expected
    assert m["missing_logs"] == 1 and m["dosage_completion"] == pytest.approx(20 / 50)
    uni = F.compute(["c1"], logs, 10, 20, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 10))
    assert uni["expected_source"] == "uniform"


@pytest.fixture(scope="module")
def env(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    iv = next(r for r in items(c.get("/api/v1/interventions", headers=H).json()) if r["code"] == "INT-PEER")
    return c, H, ds, cur, iv


def test_calendar_lifecycle(env, monkeypatch):
    c, H, ds, cur, iv = env
    monkeypatch.setattr(clock, "today", lambda: date(2026, 11, 20))
    body = {"dataset_id": ds["id"], "title": "Календарь", "intervention_id": iv["id"], "topic_id": topic(cur, "T3"),
            "primary_outcome_ru": "Доля", "design": "single_group", "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "Г")[:2]],
            "baseline_assessment_id": assessment(cur, "DIAG-END"), "start_date": "2026-11-02", "end_date": "2026-12-04",
            "follow_up_due": "2026-12-11", "owner": "М", "sessions_per_week": 2, "duration_weeks": 5}
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    url = f"/api/v1/pilots/{p['id']}/sessions"
    g = c.post(f"{url}/generate", json={"blackout_ranges": [{"from": "2026-11-16", "to": "2026-11-20"}]}, headers=H).json()
    assert g["default_weekdays"] == [1, 3] and g["editable"]
    per = [s for s in g["sessions"] if s["cohort_id"] == cohorts(cur, "Г")[0]]
    assert [s["planned_date"] for s in per][:3] == ["2026-11-03", "2026-11-05", "2026-11-10"]
    assert not any("2026-11-17" <= s["planned_date"] <= "2026-11-19" for s in per)  # holiday excluded
    # before activation: free edits and deletes, all logged
    s0 = per[0]
    e = c.patch(f"{url}/{s0['id']}", json={"planned_date": "2026-11-04", "duration_minutes": 25}, headers=H).json()
    assert next(x for x in e["sessions"] if x["id"] == s0["id"])["planned_date"] == "2026-11-04"
    d = c.delete(f"{url}/{per[-1]['id']}", headers=H).json()
    assert per[-1]["id"] not in {x["id"] for x in d["sessions"]} and any(ev["action"] == "deleted" for ev in d["events"])
    assert c.post(url, json={"cohort_id": s0["cohort_id"], "planned_date": "2026-11-04"}, headers=H).json()["error"]["code"] == "session_exists"
    # activation freezes history
    for to in ("ready", "active"):
        assert c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H).status_code == 200
    assert c.delete(f"{url}/{s0['id']}", headers=H).json()["error"]["code"] == "calendar_locked"
    assert c.patch(f"{url}/{s0['id']}", json={"duration_minutes": 40}, headers=H).json()["error"]["code"] == "calendar_locked"
    assert c.post(f"{url}/generate", json={}, headers=H).json()["error"]["code"] == "calendar_locked"
    # a fidelity log completes the matching session
    c.post(f"/api/v1/pilots/{p['id']}/fidelity-logs", json={"cohort_id": s0["cohort_id"], "session_date": "2026-11-04",
                                                           "planned_minutes": 25, "delivered_minutes": 25}, headers=H)
    cal = c.get(url, headers=H).json()
    assert next(x for x in cal["sessions"] if x["id"] == s0["id"])["status"] == "completed"
    assert any(ev["source"] == "fidelity_log" for ev in cal["events"])
    # reschedule: original keeps its date with status 'rescheduled', a new planned session appears
    target = next(x for x in cal["sessions"] if x["cohort_id"] == s0["cohort_id"] and x["planned_date"] == "2026-11-10")
    r = c.patch(f"{url}/{target['id']}", json={"planned_date": "2026-11-13", "note": "экскурсия"}, headers=H).json()
    orig = next(x for x in r["sessions"] if x["id"] == target["id"])
    assert orig["status"] == "rescheduled" and orig["rescheduled_to_id"]
    assert next(x for x in r["sessions"] if x["id"] == orig["rescheduled_to_id"])["planned_date"] == "2026-11-13"
    # fidelity on 11.11: expected = 04.11, 05.11 (10.11 rescheduled, 12.11 and 13.11 not yet) → one missing log, none for 10.11
    f = c.get(f"/api/v1/pilots/{p['id']}/fidelity", params={"as_of": "2026-11-11"}, headers=H).json()
    row = next(x for x in f["cohorts"] if x["cohort_id"] == s0["cohort_id"])
    assert f["expected_source"] == "calendar" and row["metrics"]["expected_sessions"] == 2 and row["metrics"]["missing_logs"] == 1
    # roles and tenancy
    assert c.get(url, headers=login(c, "viewer")).status_code == 403
    assert c.patch(f"{url}/{s0['id']}", json={"status": "cancelled"}, headers=user_headers(["teacher"])).status_code == 200
    assert c.get(url, headers=login(c, "other_org")).status_code == 404


def test_seeded_calendars(env):
    c, H, ds, cur, iv = env
    p3 = pilot_by_code(c, H, "PIL-M03")
    cal = c.get(f"/api/v1/pilots/{p3['id']}/sessions", headers=H).json()
    assert cal["counts"].get("rescheduled") == 1
    assert not any("2026-12-21" <= s["planned_date"] <= "2026-12-25" for s in cal["sessions"])  # winter break
    p1 = pilot_by_code(c, H, "PIL-M01")
    cal1 = c.get(f"/api/v1/pilots/{p1['id']}/sessions", headers=H).json()
    assert cal1["counts"] == {"completed": 90}  # every planned session matched by a fidelity log
    f1 = c.get(f"/api/v1/pilots/{p1['id']}/fidelity", headers=H).json()
    assert f1["expected_source"] == "calendar" and f1["overall"]["expected_sessions"] == 90
