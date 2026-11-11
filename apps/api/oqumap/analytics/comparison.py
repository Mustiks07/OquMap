"""Comparison of two materials (editions) on comparable groups — pure functions.

Method ``std-v1`` (docs/METHODOLOGY.md §4):
* outcome = learner score share on the selected topic in the outcome assessment;
* direct standardisation over *pre-registered* baseline strata with shared weights;
* uncertainty = percentile cluster bootstrap, resampling the assignment unit (class, or school when the
  edition is constant within every school) within each arm; no interval below MIN_CLUSTERS per arm;
* empty strata are never extrapolated: the adjusted estimate is withheld.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scoring import finite_or_none

METHOD_VERSION_COMPARISON = "std-v1"
MIN_CLUSTERS_PER_ARM = 5
MIN_STRATUM_N = 10
MIN_BASELINE_COVERAGE = 0.7
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261111

# Registered strata schemes (defined before looking at outcomes; the API only accepts these codes).
STRATA_SCHEMES: dict[str, list[tuple[str, float | None]]] = {
    # code -> list of (stratum code, exclusive upper bound of baseline share; None = no bound)
    "pre_three_level": [("low", 0.5), ("mid", 0.75), ("high", None)],
    "pre_two_level": [("low", 0.5), ("high", None)],
}

WEIGHT_MODES = ("pooled", "equal", "arm_a", "arm_b")


def assign_stratum(share: float | None, scheme: str) -> str | None:
    if share is None or not np.isfinite(share):
        return None
    for code, upper in STRATA_SCHEMES[scheme]:
        if upper is None or share < upper:
            return code
    return None  # pragma: no cover


@dataclass
class Reason:
    code: str
    severity: str  # info | warn | fail
    params: dict

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "params": self.params}


def _weights(analysable: pd.DataFrame, strata: list[str], mode: str, arm_a: str, arm_b: str) -> dict[str, float]:
    if mode == "equal":
        return {k: 1.0 / len(strata) for k in strata}
    if mode == "pooled":
        base = analysable
    elif mode == "arm_a":
        base = analysable[analysable["arm"] == arm_a]
    elif mode == "arm_b":
        base = analysable[analysable["arm"] == arm_b]
    else:
        raise ValueError(f"unknown weight mode {mode}")
    total = len(base)
    if total == 0:
        return {k: 0.0 for k in strata}
    return {k: float((base["stratum"] == k).sum()) / total for k in strata}


def standardized_mean(stratum_means: dict[str, float | None], weights: dict[str, float]) -> float | None:
    total = 0.0
    for k, w in weights.items():
        if w <= 0:
            continue
        m = stratum_means.get(k)
        if m is None:
            return None
        total += w * m
    return total


def cluster_unit_for(learners: pd.DataFrame) -> str:
    """Assignment unit: 'school' if every school uses a single arm, otherwise 'class'."""
    per_school = learners.groupby("school_id")["arm"].nunique()
    if len(per_school) > 0 and (per_school == 1).all():
        return "school"
    return "class"


def _bootstrap(
    analysable: pd.DataFrame,
    strata: list[str],
    weights: dict[str, float],
    arm: str,
    cluster_col: str,
    rng: np.random.Generator,
    replicates: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Returns (adjusted replicates, raw replicates, invalid share) for one arm."""
    d = analysable[analysable["arm"] == arm]
    clusters = d[cluster_col].unique()
    G = len(clusters)
    idx = {c: i for i, c in enumerate(clusters)}
    K = len(strata)
    S = np.zeros((G, K))
    N = np.zeros((G, K))
    kidx = {k: j for j, k in enumerate(strata)}
    for c, k, y in zip(d[cluster_col], d["stratum"], d["outcome"], strict=True):
        S[idx[c], kidx[k]] += y
        N[idx[c], kidx[k]] += 1
    draws = rng.integers(0, G, size=(replicates, G))
    Sb = S[draws].sum(axis=1)  # (B, K)
    Nb = N[draws].sum(axis=1)
    w = np.array([weights[k] for k in strata])
    pos = w > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(Nb > 0, Sb / np.where(Nb > 0, Nb, 1), np.nan)
    valid = ~np.isnan(means[:, pos]).any(axis=1)
    adj = np.where(valid, np.nansum(means * w, axis=1), np.nan)
    raw = Sb.sum(axis=1) / np.maximum(Nb.sum(axis=1), 1)
    return adj, raw, float(1 - valid.mean())


def _raw_bootstrap(d: pd.DataFrame, cluster_col: str, rng: np.random.Generator, replicates: int) -> np.ndarray:
    clusters = d[cluster_col].unique()
    sums = d.groupby(cluster_col)["outcome"].sum().reindex(clusters).to_numpy()
    ns = d.groupby(cluster_col)["outcome"].size().reindex(clusters).to_numpy()
    draws = rng.integers(0, len(clusters), size=(replicates, len(clusters)))
    return sums[draws].sum(axis=1) / ns[draws].sum(axis=1)


def compare_arms(
    learners: pd.DataFrame,
    arm_a: str,
    arm_b: str,
    strata_scheme: str = "pre_three_level",
    weight_mode: str = "pooled",
    context_reasons: list[Reason] | None = None,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
    adjustment_possible: bool = True,
) -> dict:
    """Compare outcome between arms.

    ``learners`` columns: learner_id, arm, cohort_id, school_id, teacher_id, outcome (share or NaN when no
    outcome measurement), baseline (share or NaN). ``context_reasons`` are checks computed by the caller
    from metadata (forms/scales, language, grade, periods, mapping status)."""
    if strata_scheme not in STRATA_SCHEMES:
        raise ValueError(f"unknown strata scheme {strata_scheme}")
    if weight_mode not in WEIGHT_MODES:
        raise ValueError(f"unknown weight mode {weight_mode}")
    reasons: list[Reason] = list(context_reasons or [])
    strata = [code for code, _ in STRATA_SCHEMES[strata_scheme]]
    df = learners[learners["arm"].isin([arm_a, arm_b])].copy()

    def arm_counts(sub: pd.DataFrame) -> dict:
        return {
            "n_learners": int(sub["learner_id"].nunique()),
            "n_classes": int(sub["cohort_id"].nunique()),
            "n_schools": int(sub["school_id"].nunique()),
            "n_teachers": int(sub["teacher_id"].nunique()),
        }

    with_outcome = df[df["outcome"].notna()]
    exclusions = {
        arm: {
            "no_outcome": int(((df["arm"] == arm) & df["outcome"].isna()).sum()),
            "no_baseline": int(((df["arm"] == arm) & df["outcome"].notna() & df["baseline"].isna()).sum()),
        }
        for arm in (arm_a, arm_b)
    }

    raw = {}
    for arm in (arm_a, arm_b):
        sub = with_outcome[with_outcome["arm"] == arm]
        raw[arm] = {"mean": finite_or_none(sub["outcome"].mean()) if len(sub) else None, **arm_counts(sub)}

    # --- design checks computed from data -------------------------------------------------------
    for arm in (arm_a, arm_b):
        sub = with_outcome[with_outcome["arm"] == arm]
        if sub.empty:
            reasons.append(Reason("arm_without_outcome", "fail", {"arm": arm}))
            continue
        if sub["teacher_id"].nunique() == 1:
            reasons.append(Reason("edition_confounded_with_teacher", "fail", {"arm": arm}))
        elif sub["school_id"].nunique() == 1:
            reasons.append(Reason("edition_confounded_with_school", "fail", {"arm": arm}))

    cluster_unit = cluster_unit_for(with_outcome) if not with_outcome.empty else "class"
    cluster_col = "school_id" if cluster_unit == "school" else "cohort_id"
    if cluster_unit == "school" and not with_outcome.empty:
        reasons.append(Reason("assignment_at_school_level", "warn", {}))
    clusters_per_arm = {
        arm: int(with_outcome.loc[with_outcome["arm"] == arm, cluster_col].nunique()) for arm in (arm_a, arm_b)
    }
    few_clusters = any(v < MIN_CLUSTERS_PER_ARM for v in clusters_per_arm.values())
    if few_clusters:
        reasons.append(
            Reason("few_clusters", "warn", {"min": MIN_CLUSTERS_PER_ARM, "unit": cluster_unit, **clusters_per_arm})
        )

    analysable = with_outcome[with_outcome["baseline"].notna()].copy()
    analysable["stratum"] = [assign_stratum(b, strata_scheme) for b in analysable["baseline"]]
    coverage = (len(analysable) / len(with_outcome)) if len(with_outcome) else 0.0
    if not adjustment_possible:
        reasons.append(Reason("no_baseline_measure", "warn", {}))
    elif coverage < MIN_BASELINE_COVERAGE:
        reasons.append(Reason("low_baseline_coverage", "warn", {"coverage": round(coverage, 3)}))

    weights = _weights(analysable, strata, weight_mode, arm_a, arm_b) if adjustment_possible else {}
    table = []
    stratum_means: dict[str, dict[str, float | None]] = {arm_a: {}, arm_b: {}}
    empty_strata = []
    small_strata = []
    for k in strata:
        row = {"stratum": k, "weight": weights.get(k)}
        for arm, label in ((arm_a, "a"), (arm_b, "b")):
            sub = analysable[(analysable["arm"] == arm) & (analysable["stratum"] == k)]
            m = finite_or_none(sub["outcome"].mean()) if len(sub) else None
            row[f"n_{label}"] = int(len(sub))
            row[f"mean_{label}"] = m
            stratum_means[arm][k] = m
            if adjustment_possible and weights.get(k, 0) > 0:
                if len(sub) == 0:
                    empty_strata.append({"stratum": k, "arm": arm})
                elif len(sub) < MIN_STRATUM_N:
                    small_strata.append({"stratum": k, "arm": arm, "n": int(len(sub))})
        table.append(row)
    if empty_strata:
        reasons.append(Reason("empty_stratum", "fail", {"strata": empty_strata}))
    if small_strata:
        reasons.append(Reason("small_stratum", "warn", {"strata": small_strata, "min": MIN_STRATUM_N}))

    adjusted = {arm_a: None, arm_b: None}
    adjusted_reason = None
    if not adjustment_possible:
        adjusted_reason = "no_baseline_measure"
    elif empty_strata:
        adjusted_reason = "empty_stratum"
    elif analysable.empty:
        adjusted_reason = "no_analysable_learners"
    else:
        for arm in (arm_a, arm_b):
            adjusted[arm] = standardized_mean(stratum_means[arm], weights)

    hard_fail = any(r.severity == "fail" and r.code != "empty_stratum" for r in reasons)
    status = "not_comparable" if hard_fail else ("limited" if any(r.severity in ("warn", "fail") for r in reasons) else "comparable")

    # --- uncertainty -----------------------------------------------------------------------------
    diff_raw = None
    if raw[arm_a]["mean"] is not None and raw[arm_b]["mean"] is not None:
        diff_raw = raw[arm_b]["mean"] - raw[arm_a]["mean"]
    diff_adj = None
    if adjusted[arm_a] is not None and adjusted[arm_b] is not None:
        diff_adj = adjusted[arm_b] - adjusted[arm_a]

    ci = {"raw": None, "adjusted": None}
    ci_reason = None
    if status == "not_comparable":
        ci_reason = "not_comparable"
    elif few_clusters:
        ci_reason = "too_few_clusters"
    else:
        rng = np.random.default_rng(seed)
        alpha = (1 - confidence) / 2
        ra = _raw_bootstrap(with_outcome[with_outcome["arm"] == arm_a], cluster_col, rng, replicates)
        rb = _raw_bootstrap(with_outcome[with_outcome["arm"] == arm_b], cluster_col, rng, replicates)
        d = rb - ra
        ci["raw"] = {"low": float(np.quantile(d, alpha)), "high": float(np.quantile(d, 1 - alpha))}
        if diff_adj is not None:
            aa, _, inv_a = _bootstrap(analysable, strata, weights, arm_a, cluster_col, rng, replicates)
            ab, _, inv_b = _bootstrap(analysable, strata, weights, arm_b, cluster_col, rng, replicates)
            invalid = max(inv_a, inv_b)
            if invalid > 0.05:
                ci_reason = "unstable_bootstrap_empty_strata"
            else:
                dd = (ab - aa)[~np.isnan(ab - aa)]
                ci["adjusted"] = {"low": float(np.quantile(dd, alpha)), "high": float(np.quantile(dd, 1 - alpha))}
        else:
            ci_reason = adjusted_reason

    if status == "not_comparable":
        inference_level = "descriptive"
    elif diff_adj is not None:
        inference_level = "adjusted_association"
    else:
        inference_level = "descriptive"

    ranking_allowed = status != "not_comparable" and diff_adj is not None
    if diff_adj is None or ci["adjusted"] is None:
        signal = "undetermined"
    elif ci["adjusted"]["low"] > 0:
        signal = "b_higher"
    elif ci["adjusted"]["high"] < 0:
        signal = "a_higher"
    else:
        signal = "no_clear_difference"  # an interval containing zero is not proof of equality

    return {
        "method_version": METHOD_VERSION_COMPARISON,
        "arms": {"a": arm_a, "b": arm_b},
        "status": status,
        "reasons": [r.as_dict() for r in reasons],
        "inference_level": inference_level,
        "causal_protocol_available": False,
        "ranking_allowed": ranking_allowed,
        "signal": signal,
        "raw": {"a": raw[arm_a], "b": raw[arm_b], "difference": finite_or_none(diff_raw)},
        "adjusted": {
            "a": finite_or_none(adjusted[arm_a]),
            "b": finite_or_none(adjusted[arm_b]),
            "difference": finite_or_none(diff_adj),
            "unavailable_reason": adjusted_reason,
            "weights": {k: finite_or_none(v) for k, v in weights.items()},
            "weight_mode": weight_mode,
            "strata_scheme": strata_scheme,
            "strata": table,
        },
        "uncertainty": {
            "method": "cluster_bootstrap_percentile",
            "cluster_unit": cluster_unit,
            "clusters_per_arm": {"a": clusters_per_arm[arm_a], "b": clusters_per_arm[arm_b]},
            "replicates": replicates,
            "seed": seed,
            "confidence": confidence,
            "raw_difference_ci": ci["raw"],
            "adjusted_difference_ci": ci["adjusted"],
            "unavailable_reason": ci_reason,
        },
        "baseline_coverage": finite_or_none(coverage),
        "exclusions": {"a": exclusions[arm_a], "b": exclusions[arm_b]},
    }
