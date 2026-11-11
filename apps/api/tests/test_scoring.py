import numpy as np
import pandas as pd
import pytest

from oqumap.analytics import scoring


def frame(rows):
    cols = ["learner_id", "cohort_id", "school_id", "teacher_id", "item_id", "attempt", "status", "score", "max_points", "response_value"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows])


def test_first_and_last_attempt_rules_keep_one_row_per_learner_item():
    df = frame([
        ("L1", "C1", "S1", "T1", "I1", 1, "answered", 0.0, 1.0, "B"),
        ("L1", "C1", "S1", "T1", "I1", 2, "answered", 1.0, 1.0, "A"),
        ("L2", "C1", "S1", "T1", "I1", 1, "answered", 1.0, 1.0, "A"),
    ])
    first = scoring.select_attempts(df, "first")
    last = scoring.select_attempts(df, "last")
    assert len(first) == len(last) == 2
    assert first.set_index("learner_id").loc["L1", "score"] == 0.0
    assert last.set_index("learner_id").loc["L1", "score"] == 1.0


def test_item_linked_to_two_objectives_is_not_double_counted_in_topic():
    links = pd.DataFrame([
        {"item_id": "I1", "objective_id": "O1", "weight": 0.5},
        {"item_id": "I1", "objective_id": "O2", "weight": 0.5},
        {"item_id": "I2", "objective_id": "O1", "weight": 1.0},
    ])
    topic_of = {"O1": "T", "O2": "T"}
    w = scoring.item_unit_weights(links, topic_of, "T").set_index("item_id")["w"]
    assert w["I1"] == pytest.approx(1.0) and w["I2"] == pytest.approx(1.0)
    df = frame([("L1", "C1", "S1", "T1", "I1", 1, "answered", 1.0, 1.0, "A"),
                ("L1", "C1", "S1", "T1", "I2", 1, "answered", 0.0, 1.0, "B")])
    s = scoring.learner_unit_scores(df, w.reset_index(), "as_incorrect")
    assert s["score"].iloc[0] == pytest.approx(0.5)
    # split across topics: half of the item counts for each topic
    topic_split = {"O1": "T", "O2": "U"}
    w2 = scoring.item_unit_weights(links, topic_split, "U").set_index("item_id")["w"]
    assert w2.to_dict() == {"I1": pytest.approx(0.5)}


def test_absent_learner_has_no_score_and_omissions_follow_policy():
    df = frame([
        ("L1", "C1", "S1", "T1", "I1", 1, "answered", 1.0, 1.0, "A"),
        ("L1", "C1", "S1", "T1", "I2", 1, "omitted", np.nan, 1.0, None),
        ("L2", "C1", "S1", "T1", "I1", 1, "answered", 0.0, 1.0, "B"),  # measured zero
    ])
    w = pd.DataFrame({"item_id": ["I1", "I2"], "w": [1.0, 1.0]})
    inc = scoring.learner_unit_scores(df, w, "as_incorrect").set_index("learner_id")["score"]
    exc = scoring.learner_unit_scores(df, w, "exclude").set_index("learner_id")["score"]
    assert inc["L1"] == 0.5 and exc["L1"] == 1.0
    assert inc["L2"] == 0.0  # a real zero
    assert "L3" not in inc.index  # absent learner: no row, no zero


def test_cluster_robust_interval_uses_class_count_and_is_withheld_for_few_classes():
    rng = np.random.default_rng(0)
    rows = []
    for c in range(3):
        for i in range(200):
            rows.append({"learner_id": f"{c}-{i}", "cohort_id": f"C{c}", "school_id": "S", "teacher_id": "T",
                         "score": float(rng.uniform())})
    s = scoring.summarize_scores(pd.DataFrame(rows))
    assert s.n_learners == 600 and s.n_classes == 3
    assert s.ci_low is None and s.ci_unavailable_reason == "too_few_clusters"


def test_empty_inputs_produce_null_not_zero():
    s = scoring.summarize_scores(pd.DataFrame(columns=["learner_id", "cohort_id", "school_id", "score"]))
    assert s.mean is None and s.ci_unavailable_reason == "no_data"


def test_paired_change_uses_same_learners_and_cluster_bootstrap():
    import numpy as np
    import pandas as pd

    from oqumap.analytics.paired import paired_change

    rng = np.random.default_rng(1)
    rows_b, rows_a = [], []
    for c in range(6):
        for i in range(10):
            lid = f"L{c}-{i}"
            b = float(rng.uniform(0.2, 0.6))
            rows_b.append({"learner_id": lid, "cohort_id": f"C{c}", "score": b})
            rows_a.append({"learner_id": lid, "cohort_id": f"C{c}", "score": b + 0.1})
    before, after = pd.DataFrame(rows_b), pd.DataFrame(rows_a)
    r = paired_change(before, after)
    assert r["available"] and r["n_pairs"] == 60 and abs(r["mean_change"] - 0.1) < 1e-9
    assert r["ci"]["low"] - 1e-9 <= 0.1 <= r["ci"]["high"] + 1e-9
    other = after.assign(learner_id=after["learner_id"] + "-new")
    assert paired_change(before, other)["reason"] == "no_shared_learner_ids"
    assert paired_change(before.head(10), after.head(10))["reason"] == "too_few_pairs"
