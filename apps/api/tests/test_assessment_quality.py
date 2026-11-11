"""Assessment Quality Lab: hand-checkable statistics, edge cases and the API contract."""

import json
import math

import numpy as np
import pandas as pd
import pytest
from conftest import login

from oqumap.analytics import assessment_quality as aq


def _items(spec):
    return {k: aq.ItemMeta(k, k.upper(), mp, key, opts) for k, (mp, key, opts) in spec.items()}


def _resp(rows):
    return pd.DataFrame(rows, columns=["learner_id", "item_id", "status", "score", "max_points", "response_value"])


# ---------------------------------------------------------------------------
# Elementary statistics on hand-checkable arrays
# ---------------------------------------------------------------------------


def test_cronbach_alpha_hand_computed():
    # item variances (ddof=1): .25, .3333, .25 → Σ=.8333; totals 3,2,1,0 → var 1.6667; α = 1.5·(1−.5) = .75
    mat = np.array([[1, 1, 1], [1, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=float)
    a = aq.cronbach_alpha(mat, min_learners=1)
    assert a.value == pytest.approx(0.75)


def test_alpha_zero_variance_tiny_n_and_few_items_are_explicit():
    assert aq.cronbach_alpha(np.ones((40, 5)), min_learners=1).reason == "zero_total_variance"
    assert aq.cronbach_alpha(np.random.default_rng(1).integers(0, 2, (10, 5)).astype(float)).reason == "too_few_learners"
    assert aq.cronbach_alpha(np.ones((40, 2)), min_learners=1).reason == "too_few_items"
    d = aq.Stat(None, "too_few_learners").as_dict()
    assert d == {"value": None, "unavailable_reason": "too_few_learners"}


def test_pearson_and_zero_variance():
    assert aq.pearson(np.array([1, 2, 3, 4]), np.array([2, 4, 6, 8])).value == pytest.approx(1.0)
    assert aq.pearson(np.array([1, 2, 3, 4]), np.array([8, 6, 4, 2])).value == pytest.approx(-1.0)
    assert aq.pearson(np.array([1, 1, 1, 1]), np.array([1, 2, 3, 4])).reason == "zero_variance"
    assert aq.pearson(np.array([1, 2]), np.array([1, 2])).reason == "too_few_pairs"


def test_upper_lower_rule_uses_27_percent_of_corrected_total_and_is_deterministic():
    item = [0, 0, 0, 1, 0, 1, 1, 1, 1, 1]
    rest = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    ids = [f"L{i}" for i in range(10)]
    r = aq.upper_lower_discrimination(item, rest, ids, share=0.3, min_learners=10)
    assert r["group_size"] == 3 and r["p_lower"] == 0 and r["p_upper"] == 1 and r["value"] == 1
    assert aq.upper_lower_discrimination(item, rest, ids)["unavailable_reason"] == "too_few_learners"


def test_distribution_floor_ceiling_and_empty():
    d = aq.distribution(np.array([0, 0, 0.5, 1.0]))
    assert d["floor_share"] == 0.5 and d["ceiling_share"] == 0.25 and d["median"] == 0.25
    assert sum(b["count"] for b in d["histogram"]) == 4
    assert aq.distribution(np.array([]))["unavailable_reason"] == "no_present_learners"


def test_partial_credit_normalised_by_max_points():
    items = _items({"a": (1.0, "A", []), "b": (2.0, "B", [])})
    resp = _resp([("L1", "a", "answered", 1.0, 1.0, "A"), ("L1", "b", "answered", 1.0, 2.0, "B")])
    share, status = aq.item_matrix(resp, ["L1"], ["a", "b"], items)
    assert share.loc["L1", "b"] == 0.5
    assert aq.learner_totals(share, items)["L1"] == pytest.approx(2 / 3)  # (1 + 1) / (1 + 2), not mean of shares


def test_omitted_wrong_missing_and_absent_are_kept_apart():
    items = _items({"a": (1.0, "A", []), "b": (1.0, "B", [])})
    resp = _resp([("L1", "a", "answered", 0.0, 1.0, "C"), ("L1", "b", "omitted", None, 1.0, None),
                  ("L2", "a", "answered", 1.0, 1.0, "A")])  # L2 has no row for b → missing
    share, status = aq.item_matrix(resp, ["L1", "L2"], ["a", "b"], items)  # L3 absent: not in present
    assert list(share.index) == ["L1", "L2"]
    assert status.loc["L1", "a"] == "answered" and share.loc["L1", "a"] == 0.0  # wrong = measured zero
    assert status.loc["L1", "b"] == "omitted" and share.loc["L1", "b"] == 0.0  # as_incorrect
    assert status.loc["L2", "b"] == "missing" and math.isnan(share.loc["L2", "b"])
    share_x, _ = aq.item_matrix(resp, ["L1", "L2"], ["a", "b"], items, "exclude")
    assert math.isnan(share_x.loc["L1", "b"])
    fq = aq.form_quality(share, status, items, {"assigned": 3, "present": 2, "absent": 1, "no_record": 0})
    assert fq["denominators"]["expected_item_responses"] == 4
    assert fq["item_responses"] == {"answered": 2, "omitted": 1, "missing": 1}
    assert fq["omission_rate"] == 0.25 and fq["completion_rate"] == 0.5 and fq["participation_rate"] == pytest.approx(2 / 3)
    assert fq["reliability"]["cronbach_alpha"]["value"] is None


def test_all_omitted_item():
    opts = [{"key": "A", "text": "1", "correct": True, "misconception": None}, {"key": "B", "text": "2", "correct": False, "misconception": "x"}]
    items = _items({"a": (1.0, "A", opts), "b": (1.0, "A", opts)})
    rows = []
    for i in range(40):
        rows.append((f"L{i:02d}", "a", "omitted", None, 1.0, None))
        rows.append((f"L{i:02d}", "b", "answered", float(i % 2), 1.0, "A" if i % 2 else "B"))
    resp = _resp(rows)
    present = [f"L{i:02d}" for i in range(40)]
    share, status = aq.item_matrix(resp, present, ["a", "b"], items)
    row = aq.item_quality("a", share, status, resp, items, aq.learner_totals(share, items))
    assert row["denominators"]["answered"] == 0 and row["omission_rate"] == 1.0
    assert row["p_value"] == 0.0 and row["p_value_among_answered"] is None
    assert row["item_rest_correlation"]["unavailable_reason"] == "zero_variance"
    codes = {f["code"] for f in row["flags"]}
    assert "high_omission" in codes and "too_hard" in codes
    share_x, status_x = aq.item_matrix(resp, present, ["a", "b"], items, "exclude")
    row_x = aq.item_quality("a", share_x, status_x, resp, items, aq.learner_totals(share_x, items))
    assert row_x["p_value"] is None  # nothing usable under 'exclude' — not 0


def _miskeyed_fixture(n=60, seed=7):
    """Item 'k' is keyed 'B' but strong learners choose 'A': negative discrimination + suspicious distractor.
    Option 'D' is never chosen: non-functional distractor."""
    rng = np.random.default_rng(seed)
    opts = [{"key": c, "text": c, "correct": c == "B", "misconception": None if c == "B" else f"m{c}"} for c in "ABCD"]
    good_opts = [{"key": c, "text": c, "correct": c == "A", "misconception": None if c == "A" else f"m{c}"} for c in "ABC"]
    items = {"k": aq.ItemMeta("k", "K", 1.0, "B", opts)}
    rows = []
    theta = np.sort(rng.normal(0, 1, n))
    for j in range(6):
        items[f"g{j}"] = aq.ItemMeta(f"g{j}", f"G{j}", 1.0, "A", good_opts)
    for i, t in enumerate(theta):
        lid = f"L{i:03d}"
        for j in range(6):
            ok = rng.random() < 1 / (1 + math.exp(-(1.5 * t)))
            rows.append((lid, f"g{j}", "answered", 1.0 if ok else 0.0, 1.0, "A" if ok else "B"))
        choice = "A" if t > 0 else ("B" if rng.random() < 0.7 else "C")
        rows.append((lid, "k", "answered", 1.0 if choice == "B" else 0.0, 1.0, choice))
    return items, _resp(rows), [f"L{i:03d}" for i in range(n)]


def test_distractor_analysis_flags_miskeyed_item():
    items, resp, present = _miskeyed_fixture()
    ids = list(items)
    share, status = aq.item_matrix(resp, present, ids, items)
    totals = aq.learner_totals(share, items)
    row = aq.item_quality("k", share, status, resp, items, totals)
    assert row["item_rest_correlation"]["value"] < 0 and row["upper_lower"]["value"] < 0
    opt = {o["key"]: o for o in row["options"]}
    assert opt["D"]["count"] == 0 and opt["D"]["share_of_answered"] == 0
    assert opt["A"]["point_biserial_rest"]["value"] > 0  # strong learners choose a 'wrong' option
    assert opt["A"]["mean_rest_score"] > opt["B"]["mean_rest_score"]
    codes = {f["code"]: f for f in row["flags"]}
    assert {"negative_discrimination", "suspicious_distractor", "non_functional_distractors"} <= set(codes)
    assert "A" in codes["suspicious_distractor"]["params"]["options"]
    assert codes["non_functional_distractors"]["params"]["options"] == ["D"]
    good = aq.item_quality("g0", share, status, resp, items, totals)
    assert good["item_rest_correlation"]["value"] > 0.2
    assert not {"negative_discrimination", "suspicious_distractor"} & {f["code"] for f in good["flags"]}


def test_small_slices_are_suppressed_with_complementary_suppression():
    out = aq.suppress_slices([{"value": "ru", "n": 50, "mean": .6, "median": .6, "sd": .1},
                              {"value": "kz", "n": 8, "mean": .5, "median": .5, "sd": .1},
                              {"value": "en", "n": 40, "mean": .7, "median": .7, "sd": .1}])
    by = {s["value"]: s for s in out}
    assert by["kz"]["suppressed"] and by["kz"]["mean"] is None and by["kz"]["n"] is None
    assert by["en"]["suppressed"] and by["en"]["suppression"] == "complementary"
    assert not by["ru"]["suppressed"] and by["ru"]["mean"] == .6


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _assessment(client, H, datasets, code, ds="base"):
    lst = client.get("/api/v1/quality/assessments", params={"dataset_id": datasets[ds]["id"]}, headers=H)
    assert lst.status_code == 200, lst.text
    return next(a for a in lst.json()["assessments"] if a["assessment"]["code"] == code)


def test_quality_api_contract_provenance_and_denominators(client, H, datasets):
    summ = _assessment(client, H, datasets, "POST-2026")
    aid = summ["assessment"]["assessment_id"]
    r = client.get(f"/api/v1/quality/assessments/{aid}", headers=H)
    assert r.status_code == 200
    assert "NaN" not in r.text and "Infinity" not in r.text
    d = r.json()
    assert d["method_version"] == "aq-v1" and d["provenance"]["kind"] == "assessment_quality"
    assert d["dataset_version"] == datasets["base"]["version"] and d["generated_at"]
    den = d["form"]["denominators"]
    assert den["present"] + den["absent"] + den["no_sitting_record"] == den["assigned"]
    assert den["absent"] == d["exclusions"]["absent_learners"] > 0
    assert d["form"]["reliability"]["cronbach_alpha"]["value"] > 0.8
    assert d["exclusions"]["rows_excluded_by_attempt_rule"] > 0 and d["exclusions"]["learners_with_repeat_attempts"] > 0
    assert d["limitations"] and all(x["message_ru"] and x["message_kz"] for x in d["limitations"])
    # unconfirmed (T6) items are flagged as a review signal, not dropped
    t6 = [it for it in d["items"] if any(o["topic_code"] == "T6" for o in it["objectives"])]
    assert t6 and all(any(f["code"] == "mapping_unconfirmed" for f in it["flags"]) for it in t6)
    # same request → same snapshot
    assert client.get(f"/api/v1/quality/assessments/{aid}", headers=H).json()["provenance"]["analysis_id"] == d["provenance"]["analysis_id"]


def test_attempt_rule_changes_only_retaken_items(client, H, datasets):
    aid = _assessment(client, H, datasets, "POST-2026")["assessment"]["assessment_id"]
    first = client.get(f"/api/v1/quality/assessments/{aid}/items", headers=H).json()
    last = client.get(f"/api/v1/quality/assessments/{aid}/items", params={"attempt_rule": "last"}, headers=H).json()
    assert first["provenance"]["analysis_id"] != last["provenance"]["analysis_id"]
    pf = {i["code"]: i for i in first["items"]}
    pl = {i["code"]: i for i in last["items"]}
    assert pf["I02"]["p_value"] == pl["I02"]["p_value"]  # T1 item: no retakes
    assert pf["I14"]["denominators"]["present"] == pl["I14"]["denominators"]["present"]  # retakes never add learners
    assert pl["I14"]["p_value"] >= pf["I14"]["p_value"]
    bad = client.get(f"/api/v1/quality/assessments/{aid}", params={"attempt_rule": "best"}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_parameter"


def test_item_endpoint_lists_administrations_without_pooling(client, H, datasets, curriculum):
    aid = _assessment(client, H, datasets, "POST-2026")["assessment"]["assessment_id"]
    items = client.get(f"/api/v1/quality/assessments/{aid}/items", headers=H).json()["items"]
    i14 = next(i for i in items if i["code"] == "I14")
    d = client.get(f"/api/v1/quality/items/{i14['item_id']}", headers=H).json()
    assert d["pooled"] is None and d["pooled_unavailable_reason"] == "administrations_not_pooled"
    assert len({a["assessment"]["assessment_id"] for a in d["administrations"]}) == len(d["administrations"]) >= 2
    one = client.get(f"/api/v1/quality/items/{i14['item_id']}", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()
    assert {a["assessment"]["dataset_id"] for a in one["administrations"]} == {datasets["base"]["id"]}


def test_quality_tenant_isolation(client, H, datasets):
    aid = _assessment(client, H, datasets, "POST-2026")["assessment"]["assessment_id"]
    items = client.get(f"/api/v1/quality/assessments/{aid}/items", headers=H).json()["items"]
    O = login(client, "other_org")
    assert client.get("/api/v1/quality/assessments", headers=O).json()["assessments"] == []
    for r in (client.get(f"/api/v1/quality/assessments/{aid}", headers=O),
              client.get(f"/api/v1/quality/assessments/{aid}/items", headers=O),
              client.get(f"/api/v1/quality/items/{items[0]['item_id']}", headers=O),
              client.get("/api/v1/quality/assessments", params={"dataset_id": datasets["base"]["id"]}, headers=O)):
        assert r.status_code == 404, r.text
    # wrong dataset scope for an existing assessment → 404, not data from another dataset
    assert client.get(f"/api/v1/quality/assessments/{aid}", params={"dataset_id": datasets["few_clusters"]["id"]},
                      headers=H).status_code == 404
    assert client.get("/api/v1/quality/assessments").status_code == 401


def test_viewer_can_read_quality(client, datasets):
    V = login(client, "viewer")
    r = client.get("/api/v1/quality/assessments", params={"dataset_id": datasets["few_clusters"]["id"]}, headers=V)
    assert r.status_code == 200 and json.dumps(r.json()).count("learner_id") == 0  # aggregates only
