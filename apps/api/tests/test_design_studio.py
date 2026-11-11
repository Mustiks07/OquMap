"""Round 2 / 14: Experiment Design Studio — monotonicity, false-precision guard, reproducibility, API."""

import math

import pytest
from conftest import login
from mhelpers import cohorts, curriculum, dataset

from oqumap.analytics import design_studio as eds

A = eds.Assumptions(m=25, icc=0.1, r=0.5, attrition=0.1)


def _a(**kw):
    return eds.Assumptions(**{**A.__dict__, **kw})


def test_hand_checked_standard_error():
    # m' = 22.5, DE = 1 + 21.5·0.1 = 3.15, (1 − .25)·3.15·(2/(6·22.5)) → SE = sqrt(0.035)
    assert eds.se_two_arm(6, 6, A) == pytest.approx(math.sqrt(0.75 * 3.15 * 2 / (6 * 22.5)))
    assert eds.se_single_group(6, A) == pytest.approx(math.sqrt(2 * 0.5 * 3.15 / (6 * 22.5)))


@pytest.mark.parametrize("j", [5, 6, 8, 10, 15, 20])
def test_more_clusters_never_reduce_power_and_shrink_mde(j):
    assert eds.two_arm_power(j + 1, j + 1, 0.25, A) >= eds.two_arm_power(j, j, 0.25, A)
    assert eds.two_arm_mde(j + 1, j + 1, A) <= eds.two_arm_mde(j, j, A)
    assert eds.single_group_mde(j + 1, A) <= eds.single_group_mde(j, A)


@pytest.mark.parametrize("icc", [0.0, 0.05, 0.1, 0.2, 0.3])
def test_larger_icc_never_improves_power(icc):
    assert eds.two_arm_power(8, 8, 0.25, _a(icc=icc + 0.05)) <= eds.two_arm_power(8, 8, 0.25, _a(icc=icc))
    assert eds.two_arm_mde(8, 8, _a(icc=icc + 0.05)) >= eds.two_arm_mde(8, 8, _a(icc=icc))


@pytest.mark.parametrize("att", [0.0, 0.1, 0.2, 0.4])
def test_larger_attrition_never_improves_power(att):
    assert eds.two_arm_power(8, 8, 0.25, _a(attrition=att + 0.1)) <= eds.two_arm_power(8, 8, 0.25, _a(attrition=att))


@pytest.mark.parametrize("r", [0.0, 0.3, 0.5, 0.7])
def test_more_baseline_information_reduces_mde(r):
    assert eds.two_arm_mde(8, 8, _a(r=r + 0.2)) <= eds.two_arm_mde(8, 8, _a(r=r))
    assert eds.two_arm_mde(8, 8, _a(m=40)) <= eds.two_arm_mde(8, 8, _a(m=20))


def test_power_rises_with_effect_and_mde_matches_power():
    assert eds.two_arm_power(8, 8, 0.4, A) > eds.two_arm_power(8, 8, 0.2, A)
    mde = eds.two_arm_mde(8, 8, A, power=0.8)
    assert eds.two_arm_power(8, 8, mde, A) == pytest.approx(0.8, abs=0.01)


def test_small_numbers_of_clusters_block_false_precision():
    assert eds.two_arm_power(4, 4, 0.3, A) is None and eds.two_arm_mde(4, 6, A) is None
    assert eds.single_group_mde(3, A) is None
    res = eds.evaluate(cluster_sizes=[25] * 6, icc_low=0.05, icc_high=0.2, baseline_r=0.5, attrition=0.1, effect_low=0.1,
                       effect_high=0.3, mde_target=0.3, comparison_available=True, n_pre_measurements=1, n_post_measurements=1,
                       calendar_weeks=12, intervention_weeks=6, contamination_risk="high")
    by = {d["design"]: d for d in res["designs"]}
    rct = by["cluster_randomized"]
    assert not rct["admissible"] and rct["mde_range"] is None and rct["precision_unavailable_reason"] == "too_few_clusters"
    assert "too_few_clusters_randomization" in rct["reasons"]
    assert by["interrupted_time_series"]["admissible"] is False and by["interrupted_time_series"]["power_range"] is None
    assert by["single_group"]["causal_ceiling"] == "descriptive_change" and by["single_group"]["mde_range"]["note"] == "change_detection_not_effect"
    assert res["auto_approval"] is False and "planning_approximation_no_guarantee" in res["warnings"]


def test_reproducible_and_calendar_blocks():
    kw = dict(cluster_sizes=[22, 25, 27, 24, 26, 23, 25, 28, 24, 26, 25, 27], icc_low=0.05, icc_high=0.2, baseline_r=0.6,
              attrition=0.1, effect_low=0.15, effect_high=0.35, mde_target=0.35, comparison_available=True, n_pre_measurements=3,
              n_post_measurements=2, calendar_weeks=12, intervention_weeks=6, contamination_risk="moderate")
    a, b = eds.evaluate(**kw), eds.evaluate(**kw)
    assert a == b
    rct = next(d for d in a["designs"] if d["design"] == "cluster_randomized")
    assert rct["admissible"] and rct["clusters"] == {"intervention": 6, "comparison": 6, "total": 12, "mean_size": 25.2}
    assert rct["mde_range"]["low"] <= rct["mde_range"]["high"] and len(rct["sensitivity"]) == 9
    pw = [row["power"] for row in rct["sensitivity"] if row["icc"] == 0.05]
    assert pw == sorted(pw)  # power grows with effect within one ICC
    late = eds.evaluate(**{**kw, "calendar_weeks": 4})
    assert not any(d["admissible"] for d in late["designs"])


@pytest.fixture(scope="module")
def env(client, H, datasets):
    ds = dataset(client, H, "measurement_loop")
    return client, H, ds, curriculum(client, H, ds["id"])


def test_api_uses_dataset_clusters_and_renders_reasons(env):
    c, H, ds, cur = env
    ids = cohorts(cur, "А") + cohorts(cur, "Б")
    r = c.post("/api/v1/design-studio/evaluate", json={"dataset_id": ds["id"], "cohort_ids": ids, "effect_low": 0.2, "effect_high": 0.4}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    rct = next(x for x in d["designs"] if x["design"] == "cluster_randomized")
    assert rct["clusters"]["total"] == 12 and rct["risks"]["contamination"] == "high"  # classes of the same schools
    assert all(msg["message_ru"] and msg["message_kz"] for x in d["designs"] for msg in x["messages"])
    school = c.post("/api/v1/design-studio/evaluate", json={"dataset_id": ds["id"], "cohort_ids": ids, "assignment_unit": "school"}, headers=H).json()
    sr = next(x for x in school["designs"] if x["design"] == "cluster_randomized")
    assert sr["clusters"]["total"] == 6 and sr["mde_range"] is None  # 3 schools per arm → no false precision
    O = login(c, "other_org")
    assert c.post("/api/v1/design-studio/evaluate", json={"dataset_id": ds["id"], "cohort_ids": ids}, headers=O).status_code == 404
    assert c.post("/api/v1/design-studio/evaluate", json={"cluster_sizes": [], "icc_low": 0.1}, headers=H).status_code == 422
    assert c.post("/api/v1/design-studio/evaluate", json={"cluster_sizes": [20] * 10, "icc_low": 0.3, "icc_high": 0.1}, headers=H).status_code == 422
