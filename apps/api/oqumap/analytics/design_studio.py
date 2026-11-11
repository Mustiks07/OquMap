"""Experiment Design Studio (method ``eds-v1``) — deterministic, analytic, no LLM, no automatic approval.

Outcome in standard-deviation units (standardised effect δ). For a two-arm cluster design with J_T and J_C clusters
of mean size m, attrition a (m' = m·(1 − a)), intraclass correlation ρ and a baseline (pre-test) correlation r:

    DE      = 1 + (m' − 1)·ρ                          (design effect)
    Var(Δ)  = (1 − r²) · DE · (1/(J_T·m') + 1/(J_C·m'))   (baseline adjustment assumed to explain r² at both levels)
    df      = J_T + J_C − 2                           (cluster-level degrees of freedom)
    MDE     = (t_{1−α/2, df} + t_{power, df}) · SE
    power   ≈ 1 − F_t,df(t_{1−α/2, df} − δ/SE)         (shifted central t; the opposite tail is ignored)

Single group (pre/post, no comparison): Var(change) = 2·(1 − r)·DE/(J·m'), df = J − 1 — this detects *change*,
which includes ordinary growth; it is not an effect estimate.

Small numbers of clusters block false precision: with fewer than ``MIN_CLUSTERS_PER_ARM`` clusters per arm (or per
group for single-group designs) MDE and power are not reported. Interrupted time series and stepped wedge are only
checked for admissibility (OquMap stores their protocol; analysis is external), no power is computed.
These are planning approximations; they do not guarantee a result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

METHOD_VERSION_DESIGN = "eds-v1"
MIN_CLUSTERS_PER_ARM = 5
MIN_ITS_PRE = 3
MIN_SW_CLUSTERS = 4


@dataclass
class Assumptions:
    m: float  # mean cluster size before attrition
    icc: float
    r: float
    attrition: float
    alpha: float = 0.05


def _m_eff(a: Assumptions) -> float:
    return max(1.0, a.m * (1 - a.attrition))


def se_two_arm(j_t: int, j_c: int, a: Assumptions) -> float:
    m = _m_eff(a)
    de = 1 + (m - 1) * a.icc
    return math.sqrt((1 - a.r ** 2) * de * (1 / (j_t * m) + 1 / (j_c * m)))


def se_single_group(j: int, a: Assumptions) -> float:
    m = _m_eff(a)
    de = 1 + (m - 1) * a.icc
    return math.sqrt(2 * (1 - a.r) * de / (j * m))


def power_from_se(effect: float, se: float, df: int, alpha: float = 0.05) -> float:
    tcrit = stats.t.ppf(1 - alpha / 2, df)
    return float(1 - stats.t.cdf(tcrit - effect / se, df))


def mde_from_se(se: float, df: int, power: float = 0.8, alpha: float = 0.05) -> float:
    return float((stats.t.ppf(1 - alpha / 2, df) + stats.t.ppf(power, df)) * se)


def two_arm_power(j_t: int, j_c: int, effect: float, a: Assumptions) -> float | None:
    if min(j_t, j_c) < MIN_CLUSTERS_PER_ARM:
        return None
    return power_from_se(effect, se_two_arm(j_t, j_c, a), j_t + j_c - 2, a.alpha)


def two_arm_mde(j_t: int, j_c: int, a: Assumptions, power: float = 0.8) -> float | None:
    if min(j_t, j_c) < MIN_CLUSTERS_PER_ARM:
        return None
    return mde_from_se(se_two_arm(j_t, j_c, a), j_t + j_c - 2, power, a.alpha)


def single_group_power(j: int, effect: float, a: Assumptions) -> float | None:
    if j < MIN_CLUSTERS_PER_ARM:
        return None
    return power_from_se(effect, se_single_group(j, a), j - 1, a.alpha)


def single_group_mde(j: int, a: Assumptions, power: float = 0.8) -> float | None:
    if j < MIN_CLUSTERS_PER_ARM:
        return None
    return mde_from_se(se_single_group(j, a), j - 1, power, a.alpha)


def _r(x: float | None, d: int = 3) -> float | None:
    return None if x is None else round(x, d)


def evaluate(*, cluster_sizes: list[int], icc_low: float, icc_high: float, baseline_r: float, attrition: float,
             effect_low: float, effect_high: float, mde_target: float | None, comparison_available: bool,
             n_pre_measurements: int, n_post_measurements: int, calendar_weeks: int, intervention_weeks: int,
             contamination_risk: str, alpha: float = 0.05, target_power: float = 0.8) -> dict:
    j = len(cluster_sizes)
    m = (sum(cluster_sizes) / j) if j else 0.0
    j_t, j_c = (j + 1) // 2, j // 2
    icc_mid = (icc_low + icc_high) / 2
    eff_mid = (effect_low + effect_high) / 2

    def A(icc: float) -> Assumptions:
        return Assumptions(m=m, icc=icc, r=baseline_r, attrition=attrition, alpha=alpha)

    calendar_ok = intervention_weeks <= calendar_weeks
    common_reasons = [] if calendar_ok else ["calendar_insufficient"]
    designs = []

    def two_arm_block(code: str, ceiling: str, extra_reasons: list[str], risks: dict) -> dict:
        reasons = list(common_reasons) + extra_reasons
        if not comparison_available:
            reasons.append("no_comparison_group")
        small = min(j_t, j_c) < MIN_CLUSTERS_PER_ARM
        if small:
            reasons.append("too_few_clusters_for_precision")
        blocking = {"calendar_insufficient", "no_comparison_group", "too_few_clusters_randomization"}
        admissible = not (set(reasons) & blocking)
        mdes = [two_arm_mde(j_t, j_c, A(i), target_power) for i in (icc_low, icc_high)]
        powers = [two_arm_power(j_t, j_c, e, A(i)) for i in (icc_low, icc_high) for e in (effect_low, effect_high)]
        sens = [{"icc": _r(i), "effect": _r(e), "power": _r(two_arm_power(j_t, j_c, e, A(i)))}
                for i in (icc_low, icc_mid, icc_high) for e in (effect_low, eff_mid, effect_high)]
        mde_mid = two_arm_mde(j_t, j_c, A(icc_mid), target_power)
        return {
            "design": code, "admissible": admissible, "analysis_mode": "built_in", "causal_ceiling": ceiling,
            "clusters": {"intervention": j_t, "comparison": j_c, "total": j, "mean_size": _r(m, 1)},
            "mde_range": None if small else {"low": _r(min(mdes)), "high": _r(max(mdes)), "power": target_power},
            "power_range": None if small else {"low": _r(min(powers)), "high": _r(max(powers))},
            "meets_mde_target": None if (small or mde_target is None or mde_mid is None) else bool(mde_mid <= mde_target),
            "precision_unavailable_reason": "too_few_clusters" if small else None,
            "sensitivity": [] if small else sens,
            "risks": risks, "reasons": reasons,
        }

    # single group
    sg_reasons = list(common_reasons) + ["single_group_no_causal"]
    small_sg = j < MIN_CLUSTERS_PER_ARM
    if small_sg:
        sg_reasons.append("too_few_clusters_for_precision")
    sg_mdes = [single_group_mde(j, A(i), target_power) for i in (icc_low, icc_high)]
    designs.append({
        "design": "single_group", "admissible": calendar_ok and j >= 1, "analysis_mode": "built_in",
        "causal_ceiling": "descriptive_change", "clusters": {"intervention": j, "comparison": 0, "total": j, "mean_size": _r(m, 1)},
        "mde_range": None if small_sg else {"low": _r(min(sg_mdes)), "high": _r(max(sg_mdes)), "power": target_power,
                                            "note": "change_detection_not_effect"},
        "power_range": None if small_sg else {
            "low": _r(min(single_group_power(j, e, A(i)) for i in (icc_low, icc_high) for e in (effect_low, effect_high))),
            "high": _r(max(single_group_power(j, e, A(i)) for i in (icc_low, icc_high) for e in (effect_low, effect_high)))},
        "meets_mde_target": None, "precision_unavailable_reason": "too_few_clusters" if small_sg else None,
        "sensitivity": [] if small_sg else [{"icc": _r(i), "effect": _r(e), "power": _r(single_group_power(j, e, A(i)))}
                                            for i in (icc_low, icc_mid, icc_high) for e in (effect_low, eff_mid, effect_high)],
        "risks": {"contamination": "not_applicable", "baseline_imbalance": "not_applicable", "secular_trend": "high"},
        "reasons": sg_reasons,
    })
    per_arm = min(j_t, j_c)
    designs.append(two_arm_block(
        "matched_comparison", "adjusted_association", ["observational_comparison"],
        {"contamination": contamination_risk, "baseline_imbalance": "high" if per_arm < 10 else "moderate", "secular_trend": "low"}))
    rct_extra = [] if per_arm >= MIN_CLUSTERS_PER_ARM else ["too_few_clusters_randomization"]
    designs.append(two_arm_block(
        "cluster_randomized", "causal_estimate", rct_extra,
        {"contamination": contamination_risk, "baseline_imbalance": "moderate" if per_arm < 10 else "low", "secular_trend": "low"}))
    its_reasons = list(common_reasons) + ["protocol_only_external_analysis"]
    if n_pre_measurements < MIN_ITS_PRE:
        its_reasons.append("its_needs_pre_points")
    designs.append({"design": "interrupted_time_series", "admissible": calendar_ok and n_pre_measurements >= MIN_ITS_PRE and n_post_measurements >= 1,
                    "analysis_mode": "protocol_only_external_analysis", "causal_ceiling": "external_analysis_required",
                    "clusters": {"intervention": j, "comparison": 0, "total": j, "mean_size": _r(m, 1)}, "mde_range": None,
                    "power_range": None, "meets_mde_target": None, "precision_unavailable_reason": "external_analysis",
                    "sensitivity": [], "risks": {"contamination": "not_applicable", "baseline_imbalance": "not_applicable",
                                                 "secular_trend": "modelled_externally"}, "reasons": its_reasons})
    periods = n_pre_measurements + n_post_measurements
    sw_reasons = list(common_reasons) + ["protocol_only_external_analysis"]
    if j < MIN_SW_CLUSTERS:
        sw_reasons.append("stepped_wedge_needs_clusters")
    if periods < 3:
        sw_reasons.append("stepped_wedge_needs_periods")
    designs.append({"design": "stepped_wedge", "admissible": calendar_ok and j >= MIN_SW_CLUSTERS and periods >= 3,
                    "analysis_mode": "protocol_only_external_analysis", "causal_ceiling": "external_analysis_required",
                    "clusters": {"intervention": j, "comparison": 0, "total": j, "mean_size": _r(m, 1)}, "mde_range": None,
                    "power_range": None, "meets_mde_target": None, "precision_unavailable_reason": "external_analysis",
                    "sensitivity": [], "risks": {"contamination": "low", "baseline_imbalance": "low", "secular_trend": "modelled_externally"},
                    "reasons": sw_reasons})
    return {
        "method_version": METHOD_VERSION_DESIGN,
        "assumptions": {"n_clusters": j, "mean_cluster_size": _r(m, 1), "icc_range": [icc_low, icc_high], "baseline_r": baseline_r,
                        "attrition": attrition, "effect_range_sd": [effect_low, effect_high], "mde_target_sd": mde_target,
                        "alpha": alpha, "target_power": target_power, "calendar_weeks": calendar_weeks,
                        "intervention_weeks": intervention_weeks, "allocation": "equal_split_ceil_floor"},
        "formula": "MDE = (t_{1-a/2,df} + t_{power,df}) * sqrt((1-r^2) * (1+(m'-1)ICC) * (1/(J_T m') + 1/(J_C m'))), df = J-2",
        "designs": designs,
        "auto_approval": False,
        "warnings": ["planning_approximation_no_guarantee", "effect_in_sd_units", "same_r_squared_at_both_levels_assumed"],
    }
