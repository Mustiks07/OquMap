import numpy as np
import pandas as pd
import pytest

from oqumap.analytics.comparison import compare_arms, cluster_unit_for, standardized_mean
from oqumap.analytics.fixtures import fixture_learners, load_fixture


def test_composition_fixture_reproduces_76_63_and_60_75():
    fx = load_fixture()
    learners = fixture_learners(fx)
    res = compare_arms(learners, "A", "B", strata_scheme="pre_two_level", weight_mode="equal")
    assert res["raw"]["a"]["mean"] == pytest.approx(0.76)
    assert res["raw"]["b"]["mean"] == pytest.approx(0.63)
    assert res["adjusted"]["a"] == pytest.approx(0.60)
    assert res["adjusted"]["b"] == pytest.approx(0.75)
    assert res["adjusted"]["difference"] == pytest.approx(0.15)
    # pooled weights coincide with 50/50 here (200 high + 200 low learners)
    pooled = compare_arms(learners, "A", "B", strata_scheme="pre_two_level", weight_mode="pooled")
    assert pooled["adjusted"]["weights"] == {"low": pytest.approx(0.5), "high": pytest.approx(0.5)}
    # illustration has a single school per arm: never a causal level, no interval
    assert res["inference_level"] != "causal_protocol"
    assert res["uncertainty"]["adjusted_difference_ci"] is None
    assert res["status"] == "limited"


def _synthetic(n_classes=16, n_per=25, effect=0.0, seed=1, empty_high_b=False):
    rng = np.random.default_rng(seed)
    rows = []
    for arm in ("A", "B"):
        for c in range(n_classes):
            cls_eff = rng.normal(0, 0.05)
            for i in range(n_per):
                base = rng.uniform(0, 1)
                if empty_high_b and arm == "B":
                    base = rng.uniform(0, 0.74)
                y = np.clip(0.3 + 0.4 * base + cls_eff + (effect if arm == "B" else 0) + rng.normal(0, 0.1), 0, 1)
                rows.append(
                    dict(learner_id=f"{arm}{c}-{i}", arm=arm, cohort_id=f"{arm}{c}", school_id=f"s{c % 8}",
                         teacher_id=f"t{arm}{c}", outcome=y, baseline=base)
                )
    return pd.DataFrame(rows)


def test_empty_stratum_blocks_adjusted_estimate_without_extrapolation():
    res = compare_arms(_synthetic(empty_high_b=True), "A", "B", replicates=200)
    assert res["adjusted"]["a"] is None and res["adjusted"]["b"] is None
    assert res["adjusted"]["unavailable_reason"] == "empty_stratum"
    assert any(r["code"] == "empty_stratum" for r in res["reasons"])
    assert res["inference_level"] == "descriptive"
    assert res["raw"]["a"]["mean"] is not None  # description of the available data is still shown


def test_few_clusters_suppress_interval_even_with_many_responses():
    res = compare_arms(_synthetic(n_classes=2, n_per=200), "A", "B", replicates=200)
    assert res["uncertainty"]["adjusted_difference_ci"] is None
    assert res["uncertainty"]["unavailable_reason"] == "too_few_clusters"
    assert res["status"] == "limited"


def test_teacher_confounding_is_not_comparable():
    df = _synthetic()
    df.loc[df["arm"] == "A", "teacher_id"] = "only-teacher"
    res = compare_arms(df, "A", "B", replicates=200)
    assert res["status"] == "not_comparable"
    assert res["ranking_allowed"] is False
    assert res["inference_level"] == "descriptive"


def test_cluster_unit_is_class_when_edition_varies_within_school_and_school_otherwise():
    df = _synthetic()
    assert cluster_unit_for(df) == "class"
    df2 = df.copy()
    df2["school_id"] = df2["arm"] + df2["cohort_id"].str[-1]
    assert cluster_unit_for(df2) == "school"


def test_bootstrap_resamples_clusters_not_learners():
    """With strong class effects, the cluster interval must be much wider than a naive learner-level one."""
    rng = np.random.default_rng(3)
    rows = []
    for arm in ("A", "B"):
        for c in range(8):
            eff = rng.normal(0, 0.15)
            for i in range(60):
                rows.append(dict(learner_id=f"{arm}{c}-{i}", arm=arm, cohort_id=f"{arm}{c}", school_id=f"s{c}",
                                 teacher_id=f"t{arm}{c}", outcome=float(np.clip(0.5 + eff + rng.normal(0, 0.05), 0, 1)),
                                 baseline=0.6))
    df = pd.DataFrame(rows)
    res = compare_arms(df, "A", "B", strata_scheme="pre_two_level", replicates=1000)
    ci = res["uncertainty"]["adjusted_difference_ci"]
    width = ci["high"] - ci["low"]
    a = df[df.arm == "A"].outcome
    b = df[df.arm == "B"].outcome
    naive = 2 * 1.96 * np.sqrt(a.var() / len(a) + b.var() / len(b))
    assert width > 2.5 * naive
    assert res["uncertainty"]["cluster_unit"] == "class"


def test_interval_coverage_simulation_known_difference():
    """Small simulation: the 95% cluster-bootstrap interval should cover the true difference most of the time."""
    true = 0.05
    covered = 0
    reps = 60
    for s in range(reps):
        res = compare_arms(_synthetic(effect=true, seed=100 + s), "A", "B", replicates=300, seed=s)
        ci = res["uncertainty"]["adjusted_difference_ci"]
        covered += ci["low"] <= true <= ci["high"]
    assert covered / reps >= 0.85


def test_standardized_mean_requires_every_weighted_stratum():
    assert standardized_mean({"a": 0.5, "b": None}, {"a": 0.5, "b": 0.5}) is None
    assert standardized_mean({"a": 0.5, "b": None}, {"a": 1.0, "b": 0.0}) == 0.5
