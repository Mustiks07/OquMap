"""Language DIF screening (method ``dif-mh-v1``) — Mantel–Haenszel on dichotomous items of ONE form.

For an item and two language groups (reference R, focal F), learners are stratified by the *rest score* (number of
other dichotomous items answered correctly — the analysed item is excluded from the matching variable). In each
stratum k with both groups present: A = R correct, B = R incorrect, C = F correct, D = F incorrect, N = total.

    α_MH = Σ(A·D/N) / Σ(B·C/N)          common odds ratio (α > 1: the item is relatively easier for R)
    MH D-DIF = −2.35 · ln α_MH           ETS delta scale (negative: the item disadvantages F)
    Var(ln α_MH): Robins–Breslow–Greenland;  SE(D) = 2.35 · sqrt(Var)
    χ²_MH = (|ΣA − ΣE(A)| − 0.5)² / ΣVar(A)  (continuity corrected, 1 df)

ETS-style screening categories: A — |D| < 1 or χ² not significant (p ≥ .05); C — |D| ≥ 1.5 and |D| − 1.96·SE > 1;
B — otherwise. The result is a *DIF screening signal* for expert review (translation, context, curriculum), not
evidence of bias and not a psychometric examination; no IRT is used.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

METHOD_VERSION_DIF = "dif-mh-v1"
MIN_GROUP_N = 100
MIN_ITEM_VARIATION = 5  # minimum correct and incorrect answers overall


def mantel_haenszel(item: np.ndarray, focal: np.ndarray, matching: np.ndarray) -> dict:
    """item: 0/1 scores; focal: boolean (True = focal group); matching: integer rest scores."""
    item = np.asarray(item, dtype=int)
    focal = np.asarray(focal, dtype=bool)
    matching = np.asarray(matching, dtype=int)
    n_ref, n_foc = int((~focal).sum()), int(focal.sum())
    base = {"n_reference": n_ref, "n_focal": n_foc, "alpha_mh": None, "mh_d_dif": None, "se": None, "ci_low": None, "ci_high": None,
            "chi2": None, "p_value": None, "category": None, "n_strata": 0, "unavailable_reason": None}
    if min(n_ref, n_foc) < MIN_GROUP_N:
        return {**base, "unavailable_reason": "insufficient_sample"}
    if item.sum() < MIN_ITEM_VARIATION or (len(item) - item.sum()) < MIN_ITEM_VARIATION:
        return {**base, "unavailable_reason": "near_constant_item"}
    sum_r = sum_s = 0.0
    p_r = ps_qr = q_s = 0.0
    a_sum = e_sum = v_sum = 0.0
    strata = 0
    for k in np.unique(matching):
        sel = matching == k
        ref, foc = sel & ~focal, sel & focal
        if not ref.any() or not foc.any():
            continue  # stratum without both groups carries no information
        A, B = int(item[ref].sum()), int((1 - item[ref]).sum())
        C, D = int(item[foc].sum()), int((1 - item[foc]).sum())
        N = A + B + C + D
        strata += 1
        R, S = A * D / N, B * C / N
        P, Q = (A + D) / N, (B + C) / N
        sum_r += R
        sum_s += S
        p_r += P * R
        ps_qr += P * S + Q * R
        q_s += Q * S
        m1, m0, nr, nf = A + C, B + D, A + B, C + D
        a_sum += A
        e_sum += nr * m1 / N
        if N > 1:
            v_sum += nr * nf * m1 * m0 / (N * N * (N - 1))
    if strata == 0:
        return {**base, "unavailable_reason": "no_informative_strata"}
    if sum_r == 0 or sum_s == 0:
        return {**base, "n_strata": strata, "unavailable_reason": "degenerate_odds_ratio"}
    alpha = sum_r / sum_s
    var_ln = p_r / (2 * sum_r ** 2) + ps_qr / (2 * sum_r * sum_s) + q_s / (2 * sum_s ** 2)
    d = -2.35 * math.log(alpha)
    se = 2.35 * math.sqrt(var_ln)
    chi2 = (max(0.0, abs(a_sum - e_sum) - 0.5) ** 2 / v_sum) if v_sum > 0 else 0.0
    p = float(1 - stats.chi2.cdf(chi2, 1))
    if abs(d) < 1 or p >= 0.05:
        cat = "A"
    elif abs(d) >= 1.5 and abs(d) - 1.96 * se > 1:
        cat = "C"
    else:
        cat = "B"
    return {**base, "alpha_mh": alpha, "mh_d_dif": d, "se": se, "ci_low": d - 1.96 * se, "ci_high": d + 1.96 * se, "chi2": chi2,
            "p_value": p, "category": cat, "n_strata": strata,
            "direction": "disadvantages_focal" if d < 0 else "disadvantages_reference"}
