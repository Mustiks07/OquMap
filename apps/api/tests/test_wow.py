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
