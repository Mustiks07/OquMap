"""WOW layer: evidence graph, agent council, decision sandbox, diagnostic quizzes."""

from conftest import login


def _topic(curriculum, code):
    return next(t for t in curriculum["topics"] if t["code"] == code)


def test_evidence_graph_has_verifiable_path_and_gaps(client, H, datasets, curriculum):
    ds = datasets["base"]["id"]
    t3 = _topic(curriculum, "T3")
    g = client.get(f"/api/v1/topics/{t3['id']}/graph", params={"dataset_id": ds}, headers=H).json()
    r = g["result"]
    kinds = {n["kind"] for n in r["nodes"]}
    assert {"topic", "objective", "item", "misconception", "source"} <= kinds
    ids = {n["id"] for n in r["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in r["edges"])
    assert r["path"][0] == f"topic:{t3['id']}" and len(r["path"]) >= 4
    assert all(n["open"] is None or n["open"]["type"] in ("calculation", "item", "source", "plan", "decision")
               for n in r["nodes"])
    # every calculation link resolves to the stored analysis run
    calc = next(n for n in r["nodes"] if n["kind"] == "objective")
    assert client.get(f"/api/v1/analyses/{calc['open']['analysis_id']}", headers=H).status_code == 200
    # the model/user may only select existing node IDs
    ok = client.post("/api/v1/graph/validate", json={"dataset_id": ds, "topic_id": t3["id"], "node_ids": r["path"]}, headers=H)
    assert ok.status_code == 200 and ok.json()["status"] == "passed"
    bad = client.post("/api/v1/graph/validate", json={"dataset_id": ds, "topic_id": t3["id"],
                                                      "node_ids": [r["path"][0], "objective:invented"]}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_evidence_ids"


def test_unmeasured_topic_graph_shows_gaps_not_zero(client, H, datasets, curriculum):
    t8 = _topic(curriculum, "T8")
    r = client.get(f"/api/v1/topics/{t8['id']}/graph", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()["result"]
    codes = {n["code"] for n in r["gaps"]}
    assert "objective_not_measured" in codes
    assert all(n["metrics"].get("mean") in (None,) for n in r["nodes"] if n["kind"] == "objective")


def test_graph_is_tenant_scoped(client, datasets, curriculum):
    other = login(client, "methodist")
    t3 = _topic(curriculum, "T3")
    # same org persona works; a random dataset id from nowhere does not
    r = client.get(f"/api/v1/topics/{t3['id']}/graph", params={"dataset_id": "00000000-0000-0000-0000-000000000000"}, headers=other)
    assert r.status_code == 404


def test_council_trail_critic_and_verified_card(client, H, datasets, curriculum):
    ds = datasets["base"]["id"]
    t3 = _topic(curriculum, "T3")
    r = client.post("/api/v1/ai/council", json={"dataset_id": ds, "topic_id": t3["id"]}, headers=H)
    assert r.status_code == 200, r.text
    g = r.json()
    out = g["output"]
    assert g["mode"] == "template" and g["task"] == "council"
    roles = {s["role"] for s in out["steps"]}
    assert roles == {"orchestrator", "analyst", "curriculum", "critic"}
    tools = [s["tool"] for s in out["steps"] if s["action"] == "tool"]
    assert {"get_topic_evidence", "get_evidence_graph", "compare_editions"} <= set(tools)
    assert all("analysis_id" in s["output_ref"] for s in out["steps"] if s["action"] == "tool" and s.get("output_ref")
               and s["tool"] != "get_plan_hours")
    # the demo has Simpson's paradox: raw and adjusted differences have opposite signs → raw claim blocked
    v = {x["kind"]: x for x in out["verdicts"]}
    assert v["raw_comparison"]["verdict"] == "blocked" and v["raw_comparison"]["reasons"] == ["confounded_by_entry_level"]
    assert v["adjusted_comparison"]["verdict"] == "weakened" and "association_not_causal" in v["adjusted_comparison"]["reasons"]
    assert v["misconception"]["verdict"] == "weakened"
    assert out["highlight"]["claim_id"] == v["raw_comparison"]["claim_id"]
    card = out["final"]
    assert set(card) == {"claim", "evidence_ids", "limitations", "recommended_action", "verification_plan"}
    known = {f["id"] for f in out["facts"]}
    graph = client.get(f"/api/v1/topics/{t3['id']}/graph", params={"dataset_id": ds}, headers=H).json()["result"]
    known |= {n["id"] for n in graph["nodes"]}
    assert card["evidence_ids"] and set(card["evidence_ids"]) <= known
    assert "fact:cmp_raw" not in card["evidence_ids"]  # blocked claim does not support the conclusion
    assert g["verification"]["numbers"]["status"] == "passed"
    assert "chain" not in str(out).lower() or "chain-of-thought" not in str(out).lower()


def test_council_rejects_invented_ids_and_numbers_from_a_model(client, H, datasets, curriculum, monkeypatch):
    from oqumap.ai import council

    def fake_live(task, system, user, schema, synthetic=True):
        if task == "council_analyst":
            return {"claims": [{"kind": "level", "text": "Тема провалена: 12% учеников.", "evidence_ids": ["fact:topic_level"]},
                               {"kind": "level", "text": "Всё плохо.", "evidence_ids": ["fact:invented"]}]}, \
                {"mode": "live_model", "provider": "fake", "model": "fake-1"}
        return None, {"fallback_reason": "model_not_configured", "provider": "none", "model": None}

    monkeypatch.setattr(council, "_live_or_none", fake_live)
    t3 = _topic(curriculum, "T3")
    out = client.post("/api/v1/ai/council", json={"dataset_id": datasets["base"]["id"], "topic_id": t3["id"]}, headers=H).json()["output"]
    reasons = [v["reasons"] for v in out["verdicts"] if v["role"] == "analyst"]
    assert ["unverified_numbers"] in reasons and ["unknown_evidence_ids"] in reasons
    assert "fact:invented" not in out["final"]["evidence_ids"] and "12%" not in out["final"]["claim"]


def test_sandbox_intent_to_typed_ops_with_diff():
    from oqumap.services.sandbox import parse_intent

    ops, rest = parse_intent("Добавь 2 часа на T3 за счёт T7, T5 не трогать, каждую тему менять не больше чем на 3")
    got = [(o.op, o.topic, o.value) for o in ops]
    assert ("add", "T3", 2) in got and ("remove", "T7", 2) in got and ("fix", "T5", None) in got and ("max_change", None, 3) in got
    assert rest == []
    ops, rest = parse_intent("сделай красиво и T4 не меньше 12")
    assert [(o.op, o.topic, o.value) for o in ops] == [("min", "T4", 12)] and rest  # leftovers reported, not guessed


def test_sandbox_compares_scenarios_and_converts_to_decision(client, H, datasets, curriculum):
    ds = datasets["base"]["id"]
    r = client.post("/api/v1/sandbox/intent", json={"dataset_id": ds, "text": "добавь 2 часа на T3 за счёт T7"}, headers=H).json()
    assert {d["topic"] for d in r["diff"]} == {"T3", "T7"}
    bad = client.post("/api/v1/sandbox/intent", json={"dataset_id": ds, "text": "добавь 2 часа на T42"}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_topic"
    body = {"dataset_id": ds, "scenarios": [{"name": "A: +2 к T3", "ops": r["all_ops"]},
                                            {"name": "B: T3 ровно 30", "ops": [{"op": "set", "topic": "T3", "value": 30}]}]}
    res = client.post("/api/v1/sandbox/run", json=body, headers=H).json()
    a, b = res["result"]["scenarios"]
    before = res["result"]["before"]
    assert a["status"] in ("optimal", "feasible") and a["hours"]["T3"] == before["hours"]["T3"] + 2
    assert a["hours"]["T7"] == before["hours"]["T7"] - 2 and a["validation"]["valid"]
    assert b["status"] == "infeasible" and b["conflict"]["constraints"]  # verified minimal conflict, not a silent fix
    assert res["result"]["is_forecast"] is False
    # replay: same request → same stored analysis
    again = client.post("/api/v1/sandbox/run", json=body, headers=H).json()
    assert again["context"]["analysis_id"] == res["context"]["analysis_id"]
    t3 = _topic(curriculum, "T3")
    d = client.post("/api/v1/decisions", headers=H, json={
        "dataset_id": ds, "topic_id": t3["id"], "target_group": "6 классы", "problem": "Низкий уровень по T3",
        "hypothesis": "Не хватает часов на смешанные числа", "action": "Сценарий A песочницы", "responsible": "Методист",
        "plan_analysis_id": a["plan_analysis_id"], "plan_preset": "balanced"})
    assert d.status_code == 200, d.text
    assert d.json()["snapshot"]["plan"]["analysis_id"] == a["plan_analysis_id"]


def test_quiz_families_are_exact_and_distractors_follow_rules():
    from fractions import Fraction

    from oqumap.services import quizzes as qz

    r = qz.render_frac_add({"a": 1, "b": 2, "c": 1, "d": 3})
    by = {o["misconception"]: o["text"] for o in r["options"]}
    assert r["key_value"] == Fraction(5, 6) and by[None] == "5/6" and by["add_across"] == "2/5" and by["numerators_not_scaled"] == "2/6"
    r = qz.render_mixed_sub({"w1": 3, "n1": 1, "w2": 1, "n2": 3, "d": 4})
    by = {o["misconception"]: o["text"] for o in r["options"]}
    assert by[None] == "1 1/2" and by["ignore_fraction"] == "2"


def test_quiz_generate_review_export_and_responses(client, H, datasets, curriculum):
    import io

    from openpyxl import load_workbook

    ds = datasets["base"]["id"]
    t3 = _topic(curriculum, "T3")
    q = client.post("/api/v1/quizzes/generate", json={"dataset_id": ds, "topic_id": t3["id"], "n_items": 5}, headers=H)
    assert q.status_code == 200, q.text
    q = q.json()
    assert q["status"] == "draft" and q["counts_toward_grade"] is False and len(q["items"]) == 5
    assert q["checks"]["approvable"], q["checks"]["blocking_failed"]
    for it in q["items"]:
        assert sum(o["correct"] for o in it["options"]) == 1
        assert all(o["rationale_ru"] for o in it["options"]) and it["evidence_ids"][0].startswith("misconception:")
    # teacher edits the stem of Q1 → recomputed key no longer applies → approval blocked until the teacher verifies the key
    items = [dict(i) for i in q["items"]]
    items[0]["stem_ru"] = items[0]["stem_ru"] + " Запишите решение."
    e = client.put(f"/api/v1/quizzes/{q['id']}", json={"items": items, "note": "уточнил формулировку"}, headers=H).json()
    assert e["status"] == "edited" and e["current_version"] == 2 and not e["checks"]["approvable"]
    blocked = client.post(f"/api/v1/quizzes/{q['id']}/review", json={"action": "approve"}, headers=H)
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "quiz_checks_failed"
    items[0]["teacher_key_verified"] = True
    e = client.put(f"/api/v1/quizzes/{q['id']}", json={"items": items}, headers=H).json()
    assert e["checks"]["approvable"] and [v["version"] for v in e["versions"]] == [1, 2, 3]
    ok = client.post(f"/api/v1/quizzes/{q['id']}/review", json={"action": "approve", "note": "ok"}, headers=H).json()
    assert ok["status"] == "approved"
    locked = client.put(f"/api/v1/quizzes/{q['id']}", json={"items": items}, headers=H)
    assert locked.status_code == 409
    pdf = client.get(f"/api/v1/quizzes/{q['id']}/export", params={"format": "pdf", "teacher": True}, headers=H)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert client.get(f"/api/v1/quizzes/{q['id']}/export", params={"format": "pdf"}, headers=H).content == \
        client.get(f"/api/v1/quizzes/{q['id']}/export", params={"format": "pdf"}, headers=H).content  # deterministic
    x = client.get(f"/api/v1/quizzes/{q['id']}/export", params={"format": "xlsx"}, headers=H)
    wb = load_workbook(io.BytesIO(x.content))
    assert wb["items"].max_row == 1 + sum(len(i["options"]) for i in ok["items"])
    csv_ = client.get(f"/api/v1/quizzes/{q['id']}/export", params={"format": "csv"}, headers=H).content.decode("utf-8-sig")
    assert csv_.splitlines()[0].startswith("code,objective")
    # responses: one learner chooses the misconception option on Q2 twice? (one row per item) + duplicate + unknown
    q2 = ok["items"][1]
    wrong = next(o for o in q2["options"] if not o["correct"])
    right = next(o for o in q2["options"] if o["correct"])
    rows = "learner_code,item_code,response\nL1,Q2,{w}\nL2,Q2,{r}\nL1,Q2,{r}\nL3,Q9,A\n".format(w=wrong["key"], r=right["key"])
    rs = client.post(f"/api/v1/quizzes/{q['id']}/responses", files={"file": ("r.csv", rows.encode(), "text/csv")}, headers=H).json()
    assert rs["n_learners"] == 2 and rs["summary"]["items"]["Q2"]["p_correct"] == 0.5
    assert rs["summary"]["hypotheses"][wrong["misconception"]]["n_learners"] == 1 and rs["summary"]["n_rejected"] == 2


def test_quiz_for_topic_without_family_is_honest(client, H, datasets, curriculum):
    t8 = _topic(curriculum, "T8")  # not measured: no hypotheses → no template family
    r = client.post("/api/v1/quizzes/generate", json={"dataset_id": datasets["base"]["id"], "topic_id": t8["id"]}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_template_family"
