"""Implementation fidelity: hand-checkable aggregation, missing logs, classification rules, append-only corrections,
validation, role-restricted cohort detail and tenant isolation."""

from datetime import date

import pytest
from conftest import login
from mhelpers import pilot_by_code, user_headers

from oqumap.services import fidelity as F


def _log(cohort, day, planned=20, delivered=20, ap=4, ac=4, present=20, assigned=20, adherence=None, disruption="none"):
    return F.LogRow(cohort, day, planned, delivered, ap, ac, present, assigned,
                    adherence if adherence is not None else [{"done": True}, {"done": True}], disruption)


def test_expected_sessions_follow_elapsed_share():
    start, end = date(2026, 9, 1), date(2026, 9, 30)  # 30 days
    assert F.expected_sessions(12, start, end, date(2026, 8, 31)) == 0
    assert F.expected_sessions(12, start, end, date(2026, 9, 15)) == 6  # 15/30 of 12
    assert F.expected_sessions(12, start, end, date(2026, 10, 15)) == 12  # capped at the end
    assert F.expected_sessions(12, None, end, date(2026, 9, 15)) == 0


def test_aggregation_hand_computed():
    d = date(2026, 9, 2)
    logs = [_log("c1", d, delivered=20), _log("c1", d, delivered=10, ac=2, adherence=[{"done": True}, {"done": False}]),
            _log("c1", d, delivered=0, ac=0, present=None, adherence=[], disruption="cancelled")]
    mtr = F.aggregate_logs(logs, expected=4, minutes_per_session=20)
    assert mtr["logged_sessions"] == 3 and mtr["delivered_sessions"] == 2 and mtr["cancelled_sessions"] == 1
    assert mtr["missing_logs"] == 1 and mtr["log_coverage"] == 0.75
    assert mtr["dosage_completion"] == pytest.approx(30 / 80)
    assert mtr["session_completion"] == 0.5
    assert mtr["reach"] == 1.0
    assert mtr["adherence"] == pytest.approx((2 + 4 + 1 + 2) / (2 + 4 + 2 + 4))
    assert mtr["classification"]["code"] == "low" and "dosage_completion_below_50pct" in mtr["reasons"]


def test_classification_rules():
    base = {"expected_sessions": 10, "log_coverage": 1.0, "dosage_completion": 0.9, "session_completion": 0.9,
            "adherence": 0.9, "reach": 0.9}
    assert F.classify(base)[0] == "high"
    assert F.classify({**base, "reach": 0.7})[0] == "moderate"
    assert F.classify({**base, "adherence": 0.4})[0] == "low"
    assert F.classify({**base, "log_coverage": 0.3, "dosage_completion": 0.1})[0] == "unknown"  # missing logs ≠ low
    assert F.classify({**base, "expected_sessions": 0})[0] == "unknown"
    assert F.classify({**base, "adherence": None, "reach": None})[0] == "high"


def test_missing_logs_and_overall_downgrade():
    start, end = date(2026, 9, 1), date(2026, 9, 10)
    logs = [_log(c, date(2026, 9, i)) for c in ("a", "b", "c") for i in range(1, 11)]
    res = F.compute(["a", "b", "c", "d"], logs, 10, 20, start, end, date(2026, 9, 10))
    assert res["per_cohort"]["d"]["missing_logs"] == 10 and res["per_cohort"]["d"]["classification"]["code"] == "unknown"
    assert res["distribution"] == {"high": 3, "moderate": 0, "low": 0, "unknown": 1}
    assert res["overall"]["missing_logs"] == 10 and res["overall"]["log_coverage"] == 0.75
    res2 = F.compute(["a", "b", "c"], logs + [_log("x", date(2026, 9, 3))], 10, 20, start, end, date(2026, 9, 10))
    assert res2["overall"]["classification"]["code"] == "high" and res2["overall"]["logged_sessions"] == 30  # foreign cohort ignored
    # logs after as_of are not counted
    res3 = F.compute(["a"], logs, 10, 20, start, end, date(2026, 9, 5))
    assert res3["per_cohort"]["a"]["logged_sessions"] == 5 and res3["expected_per_cohort"] == 5


def test_seeded_fidelity_high_and_low(client, H):
    p1 = pilot_by_code(client, H, "PIL-M01")
    p2 = pilot_by_code(client, H, "PIL-M02")
    f1 = client.get(f"/api/v1/pilots/{p1['id']}/fidelity", headers=H).json()
    f2 = client.get(f"/api/v1/pilots/{p2['id']}/fidelity", headers=H).json()
    assert f1["overall"]["classification"]["code"] == "high" and f1["overall"]["missing_logs"] == 0
    assert f1["as_of"] == p1["end_date"] and f1["method_version"] == "fidelity-v1"
    assert f2["overall"]["classification"]["code"] == "low"
    assert f2["overall"]["missing_logs"] == 36 and f2["overall"]["cancelled_sessions"] == 24
    assert f1["cohort_detail_visible"] and len(f1["cohorts"]) == 6 and f1["logs"]


@pytest.fixture(scope="module")
def active(fresh_client):
    c = fresh_client
    H = login(c)
    return c, H, pilot_by_code(c, H, "PIL-M03")


def test_log_validation_and_append_only_corrections(active):
    c, H, p3 = active
    cid = next(x["cohort_id"] for x in p3["cohorts"] if x["arm"] == "intervention")
    url = f"/api/v1/pilots/{p3['id']}/fidelity-logs"
    body = {"cohort_id": cid, "session_date": "2026-11-10", "planned_minutes": 25, "delivered_minutes": 20, "activities_planned": 3,
            "activities_completed": 2, "learners_present": 20, "learners_assigned": 24,
            "adherence": [{"key": "model", "label": "Модель", "done": True}], "adaptation_note": "  Сократили\x00 разминку  "}
    r = c.post(url, json=body, headers=H)
    assert r.status_code == 200, r.text
    log = r.json()
    assert log["adaptation_note"] == "Сократили разминку" and log["recorder"]
    for bad, code in (({"session_date": "2027-03-01"}, "date_outside_pilot"),
                      ({"learners_present": 30}, "validation_error"),
                      ({"disruption": "cancelled"}, "validation_error"),
                      ({"cohort_id": "00000000-0000-0000-0000-000000000000"}, "cohort_not_in_pilot")):
        rr = c.post(url, json={**body, **bad}, headers=H)
        assert rr.status_code == 422 and rr.json()["error"]["code"] == code, rr.text
    assert c.post(url, json={**body, "adaptation_note": "x" * 2001}, headers=H).status_code == 422
    future = c.post(url, json={**body, "session_date": "2026-12-20"}, headers=H)  # inside the period, but not yet happened
    assert future.status_code == 422 and future.json()["error"]["code"] == "date_in_future"
    before = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", params={"as_of": "2026-11-11"}, headers=H).json()
    fixed = c.post(url, json={**body, "delivered_minutes": 25, "corrects_log_id": log["id"]}, headers=H).json()
    assert c.post(url, json={**body, "corrects_log_id": log["id"]}, headers=H).status_code == 409  # correct the latest only
    after = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", params={"as_of": "2026-11-11"}, headers=H).json()
    assert after["overall"]["logged_sessions"] == before["overall"]["logged_sessions"]  # replaced, not added
    rows = {x["id"]: x for x in after["logs"]}
    assert rows[log["id"]]["superseded_by"] == fixed["id"] and rows[log["id"]]["delivered_minutes"] == 20  # history kept
    # draft pilots do not accept logs
    p4 = pilot_by_code(c, H, "PIL-M04")
    rr = c.post(f"/api/v1/pilots/{p4['id']}/fidelity-logs", json=body, headers=H)
    assert rr.status_code == 409 and rr.json()["error"]["code"] == "pilot_not_running"


def test_fidelity_roles_and_isolation(active):
    c, H, p3 = active
    V = login(c, "viewer")
    v = c.get(f"/api/v1/pilots/{p3['id']}/fidelity", headers=V).json()
    assert v["cohorts"] is None and v["logs"] is None and not v["cohort_detail_visible"]
    assert v["overall"]["classification"]["code"] in ("high", "moderate", "low", "unknown")
    T = user_headers(["teacher"])
    assert c.get(f"/api/v1/pilots/{p3['id']}/fidelity", headers=T).json()["cohort_detail_visible"]
    cid = next(x["cohort_id"] for x in p3["cohorts"] if x["arm"] == "intervention")
    body = {"cohort_id": cid, "session_date": "2026-11-09", "planned_minutes": 25, "delivered_minutes": 25}
    assert c.post(f"/api/v1/pilots/{p3['id']}/fidelity-logs", json=body, headers=V).status_code == 403
    assert c.post(f"/api/v1/pilots/{p3['id']}/fidelity-logs", json=body, headers=T).status_code == 200
    O = login(c, "other_org")
    assert c.get(f"/api/v1/pilots/{p3['id']}/fidelity", headers=O).status_code == 404
    assert c.post(f"/api/v1/pilots/{p3['id']}/fidelity-logs", json=body, headers=O).status_code == 404
