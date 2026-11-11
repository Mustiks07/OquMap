"""Round 2 / P1-1, P1-2: one effective as-of date drives fingerprints, fidelity, follow-up and the portfolio."""

from datetime import date

import pytest
from conftest import login
from mhelpers import assessment, cohorts, curriculum, dataset, items, pilot_by_code, topic

from oqumap.services import clock


@pytest.fixture(scope="module")
def env(fresh_client):
    c = fresh_client
    H = login(c)
    ds = dataset(c, H, "measurement_loop")
    cur = curriculum(c, H, ds["id"])
    iv = next(r for r in items(c.get("/api/v1/interventions", headers=H).json()) if r["code"] == "INT-PEER")
    body = {"dataset_id": ds["id"], "title": "Пилот для as_of", "intervention_id": iv["id"], "topic_id": topic(cur, "T3"),
            "primary_outcome_ru": "Доля баллов", "design": "single_group",
            "cohorts": [{"cohort_id": x, "arm": "intervention"} for x in cohorts(cur, "Г")],
            "baseline_assessment_id": assessment(cur, "DIAG-BASE"), "start_date": "2026-09-21", "end_date": "2026-12-18",
            "follow_up_due": "2026-12-21", "owner": "Методист", "sessions_per_week": 2, "duration_weeks": 13}
    p = c.post("/api/v1/pilots", json=body, headers=H).json()
    for to in ("ready", "active"):
        r = c.post(f"/api/v1/pilots/{p['id']}/transition", json={"to_status": to}, headers=H)
        assert r.status_code == 200, r.text
    return c, H, ds, cur, p


def _run(c, H, pid, **body):
    return c.post(f"/api/v1/pilots/{pid}/follow-up", json=body, headers=H)


def test_default_as_of_is_part_of_the_fingerprint(env, monkeypatch):
    c, H, ds, cur, p = env
    end = assessment(cur, "DIAG-END")
    monkeypatch.setattr(clock, "today", lambda: date(2026, 11, 1))
    o1 = _run(c, H, p["id"], outcome_assessment_id=end).json()
    assert o1["as_of"] == "2026-11-01" and o1["result"]["fidelity"]["as_of"] == "2026-11-01"
    assert _run(c, H, p["id"]).json()["id"] == o1["id"]  # same effective date, no new logs → reuse
    monkeypatch.setattr(clock, "today", lambda: date(2026, 11, 8))
    o2 = _run(c, H, p["id"]).json()
    assert o2["id"] != o1["id"] and o2["as_of"] == "2026-11-08"  # a later default date is not silently the old snapshot
    assert o2["result"]["fidelity"]["metrics"]["expected_sessions"] > o1["result"]["fidelity"]["metrics"]["expected_sessions"]


def test_explicit_as_of_reuses_and_future_as_of_is_rejected(env, monkeypatch):
    c, H, ds, cur, p = env
    monkeypatch.setattr(clock, "today", lambda: date(2026, 11, 10))
    a = _run(c, H, p["id"], as_of="2026-11-05").json()
    b = _run(c, H, p["id"], as_of="2026-11-05").json()
    assert a["id"] == b["id"] and a["as_of"] == "2026-11-05"
    r = _run(c, H, p["id"], as_of="2026-11-20")
    assert r.status_code == 422 and r.json()["error"]["code"] == "as_of_in_future"
    r = _run(c, H, p["id"], as_of="2026-10-01")  # DIAG-END (30.10) had not happened yet on that date
    assert r.status_code == 422 and r.json()["error"]["code"] == "outcome_after_as_of"
    assert c.get(f"/api/v1/pilots/{p['id']}/fidelity", params={"as_of": "2026-12-01"}, headers=H).json()["error"]["code"] == "as_of_in_future"
    assert c.get("/api/v1/portfolio/interventions", params={"as_of": "2026-12-01"}, headers=H).status_code == 422


def test_portfolio_uses_one_date_everywhere(env, monkeypatch):
    c, H, ds, cur, p = env
    monkeypatch.setattr(clock, "today", lambda: date(2027, 1, 5))
    p3 = pilot_by_code(c, H, "PIL-M03")
    now = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"]}, headers=H).json()
    past = c.get("/api/v1/portfolio/interventions", params={"dataset_id": ds["id"], "as_of": "2026-11-20"}, headers=H).json()
    assert now["as_of"] == "2027-01-05" and past["as_of"] == "2026-11-20"
    assert "PIL-M03" in {x["code"] for x in now["follow_ups"]["overdue"]}
    assert "PIL-M03" not in {x["code"] for x in past["follow_ups"]["overdue"]}
    for snap, day in ((now, "2027-01-05"), (past, "2026-11-20")):
        f = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", params={"as_of": day}, headers=H).json()["overall"]["classification"]["code"]
        row = next(x for x in snap["pilots"] if x["code"] == "PIL-M03")
        assert row["fidelity"] == f  # list, distribution and the fidelity endpoint agree on the same date
    exp_now = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", params={"as_of": "2027-01-05"}, headers=H).json()["overall"]["expected_sessions"]
    exp_past = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", params={"as_of": "2026-11-20"}, headers=H).json()["overall"]["expected_sessions"]
    assert exp_now > exp_past
