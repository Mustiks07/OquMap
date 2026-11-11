"""Round 2 / 16: language DIF screening (Mantel–Haenszel) — null, known DIF, insufficient sample, API on demo data."""

import numpy as np
import pytest
from conftest import login
from mhelpers import dataset

from oqumap.analytics import dif


def _simulate(n_ref=400, n_foc=300, shift=0.0, seed=1, n_other=10):
    rng = np.random.default_rng(seed)
    theta = rng.normal(0, 1, n_ref + n_foc)
    focal = np.r_[np.zeros(n_ref, bool), np.ones(n_foc, bool)]
    b = np.linspace(-1, 1, n_other)
    other = (rng.random((len(theta), n_other)) < 1 / (1 + np.exp(-(theta[:, None] - b)))).astype(int)
    p_item = 1 / (1 + np.exp(-(theta - (0.2 + shift * focal))))
    item = (rng.random(len(theta)) < p_item).astype(int)
    return item, focal, other.sum(axis=1)


def test_no_dif_gives_category_a():
    r = dif.mantel_haenszel(*_simulate(shift=0.0, seed=3))
    assert r["category"] == "A" and abs(r["mh_d_dif"]) < 1 and r["ci_low"] < 0 < r["ci_high"]


def test_known_dif_against_focal_group_is_flagged():
    r = dif.mantel_haenszel(*_simulate(shift=1.5, seed=4))
    assert r["category"] == "C" and r["mh_d_dif"] < -1.5 and r["direction"] == "disadvantages_focal" and r["p_value"] < 0.001
    assert r["alpha_mh"] > 1  # easier for the reference group at equal rest score


def test_insufficient_sample_and_degenerate_cases():
    item, focal, match = _simulate(n_ref=300, n_foc=40)
    r = dif.mantel_haenszel(item, focal, match)
    assert r["unavailable_reason"] == "insufficient_sample" and r["mh_d_dif"] is None
    ones = np.ones(400, int)
    assert dif.mantel_haenszel(ones, np.r_[np.zeros(200, bool), np.ones(200, bool)], np.arange(400) % 5)["unavailable_reason"] == "near_constant_item"


def test_hand_checked_single_stratum():
    # one stratum: A=30 B=20 C=20 D=30 → α = (30·30/100)/(20·20/100) = 2.25, D = −2.35·ln 2.25
    item = np.r_[np.ones(30), np.zeros(20), np.ones(20), np.zeros(30)].astype(int)
    focal = np.r_[np.zeros(50, bool), np.ones(50, bool)]
    old = dif.MIN_GROUP_N
    dif.MIN_GROUP_N = 10
    try:
        r = dif.mantel_haenszel(item, focal, np.zeros(100, int))
    finally:
        dif.MIN_GROUP_N = old
    assert r["alpha_mh"] == pytest.approx(2.25) and r["mh_d_dif"] == pytest.approx(-2.35 * np.log(2.25))


def test_api_on_demo_form(client, H, datasets):
    ds = dataset(client, H, "measurement_loop")
    lst = client.get("/api/v1/quality/assessments", params={"dataset_id": ds["id"]}, headers=H).json()["assessments"]
    aid = next(a for a in lst if a["assessment"]["code"] == "DIAG-BASE")["assessment"]["assessment_id"]
    r = client.get(f"/api/v1/quality/assessments/{aid}/dif", headers=H).json()
    assert r["available"] and r["label"] == "dif_screening_signal" and r["group_sizes"]["kz"] >= 100
    by = {x["code"]: x for x in r["items"]}
    assert by["Q10"]["category"] in ("B", "C") and by["Q10"]["mh_d_dif"] < 0  # deliberately harder for Kazakh-medium classes
    assert by["Q08"]["category"] == "A"  # comparable word problem without a shift
    assert any(lim["code"] == "dif_screening_only" for lim in r["limitations"])
    base = next(a for a in client.get("/api/v1/quality/assessments", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()["assessments"])
    rb = client.get(f"/api/v1/quality/assessments/{base['assessment']['assessment_id']}/dif", headers=H).json()
    assert rb["available"] is False and rb["unavailable_reason"] == "single_language_group" and rb["items"] == []
    assert client.get(f"/api/v1/quality/assessments/{aid}/dif", headers=login(client, "other_org")).status_code == 404
    assert client.get(f"/api/v1/quality/assessments/{aid}/dif", params={"focal": "ru"}, headers=H).status_code == 422
