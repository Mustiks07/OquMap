"""Weekly calendar: sequence/prerequisites, weekly load, holidays, fixed windows, explanations, verified conflicts."""

from oqumap.analytics import calendar as cal


def _p(**kw):
    topics = kw.pop("topics", [cal.CalTopic("A", 6), cal.CalTopic("B", 4), cal.CalTopic("C", 5)])
    return cal.CalProblem(topics=topics, capacity=kw.pop("capacity", [3] * 8), **kw)


def test_sequential_fill_skips_holidays_and_shares_weeks():
    cur = cal.sequential_fill([cal.CalTopic("A", 4), cal.CalTopic("B", 3)], [3, 3, 3, 3], {1})
    assert cur == {"A": {0: 3, 2: 1}, "B": {2: 2, 3: 1}}


def test_solution_respects_load_holidays_prerequisites_and_is_validated():
    p = _p(unavailable={2}, prerequisites=[("A", "C")], keep_order=False)
    r = cal.solve(p)
    assert r["status"] in ("optimal", "feasible") and r["validation"]["valid"]
    s = r["schedule"]
    assert all(2 not in s[t] for t in s)
    for w in range(8):
        assert sum(s[t].get(w, 0) for t in s) <= 3
    assert max(s["A"]) <= min(s["C"])
    assert {t: sum(v.values()) for t, v in s.items()} == {"A": 6, "B": 4, "C": 5}


def test_validator_catches_violations_independently():
    p = _p(unavailable={1}, prerequisites=[("A", "B")])
    bad = {"A": {0: 3, 1: 3}, "B": {0: 4}, "C": {3: 5}}
    codes = {v["constraint"] for v in cal.validate(p, bad)}
    assert {"holidays", "weekly_load", "prerequisite"} <= codes


def test_infeasible_fixed_window_gives_verified_minimal_conflict_with_arithmetic():
    p = _p(topics=[cal.CalTopic("A", 6), cal.CalTopic("B", 9, fixed_from=0, fixed_to=1)], keep_order=False)
    r = cal.solve(p)
    assert r["status"] == "infeasible"
    c = r["conflict"]
    assert c["verified"] and {x["key"] for x in c["constraints"]} == {"hours:B", "fixed:B"}
    assert c["arithmetic"]["hours_needed"] == 9 and c["arithmetic"]["hours_available"] == 6


def test_prerequisite_cycle_with_order_is_a_conflict():
    p = _p(topics=[cal.CalTopic("A", 2), cal.CalTopic("B", 2)], prerequisites=[("B", "A")], keep_order=True)
    r = cal.solve(p)
    assert r["status"] == "infeasible"
    keys = {x["key"] for x in r["conflict"]["constraints"]}
    assert "prereq:B>A" in keys and "order:A>B" in keys


def test_calendar_api_compare_explain_replay(client, H, datasets):
    ds = datasets["base"]["id"]
    ctx = client.get("/api/v1/calendar/context", params={"dataset_id": ds}, headers=H).json()
    assert ctx["defaults"]["n_weeks"] == 34 and {"before": "T2", "topic": "T3"} in ctx["prerequisites"]
    body = {"dataset_id": ds, "topic_hours": {"T3": 18, "T7": 8}, "unavailable_weeks": [8, 12, 17, 18, 29]}
    r = client.post("/api/v1/calendar/solve", json=body, headers=H).json()
    res = r["result"]
    assert res["status"] in ("optimal", "feasible") and res["validation"]["valid"] and res["is_forecast"] is False
    mv = {m["topic"]: m for m in res["moves"]}
    t3 = {x["code"] for x in mv["T3"]["reasons"]}
    assert "hours_changed" in t3 and "new_unavailable_weeks" in t3
    assert "earlier_topics_hours" in {x["code"] for x in mv["T4"]["reasons"]}
    assert mv["T1"]["reasons"][0]["code"] == "unchanged"
    load = res["load"]
    assert all(w["proposed"] <= w["capacity"] for w in load) and all(w["proposed"] == 0 for w in load if w["unavailable"])
    assert client.post("/api/v1/calendar/solve", json=body, headers=H).json()["context"]["analysis_id"] == r["context"]["analysis_id"]
    bad = client.post("/api/v1/calendar/solve", json={"dataset_id": ds, "fixed": [{"topic": "T3", "from_week": 2, "to_week": 4}]}, headers=H).json()
    c = bad["result"]["conflict"]
    assert bad["result"]["status"] == "infeasible" and c["verified"] and c["arithmetic"]["message_ru"].startswith("Нужно")
    assert all(x["message_ru"] for x in c["constraints"])
    unk = client.post("/api/v1/calendar/solve", json={"dataset_id": ds, "topic_hours": {"T42": 3}}, headers=H)
    assert unk.status_code == 422 and unk.json()["error"]["code"] == "unknown_topic"


def test_calendar_takes_hours_from_a_sandbox_scenario(client, H, datasets):
    ds = datasets["base"]["id"]
    sb = client.post("/api/v1/sandbox/run", json={"dataset_id": ds, "scenarios": [
        {"name": "A", "ops": [{"op": "add", "topic": "T3", "value": 2}, {"op": "remove", "topic": "T7", "value": 2}]}]}, headers=H).json()
    plan_id = sb["result"]["scenarios"][0]["plan_analysis_id"]
    r = client.post("/api/v1/calendar/solve", json={"dataset_id": ds, "plan_analysis_id": plan_id}, headers=H).json()["result"]
    assert r["hours"]["proposed"]["T3"] == r["hours"]["current"]["T3"] + 2
    assert r["status"] in ("optimal", "feasible")
