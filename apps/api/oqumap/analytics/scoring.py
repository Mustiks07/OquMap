"""Pure scoring and aggregation functions (no database access).

Input frame ``responses`` has one row per attempt with columns:
    learner_id, cohort_id, school_id, teacher_id, item_id, attempt, status, score, max_points,
    response_value
``weights`` maps (item_id, topic_or_objective) -> weight, built from item-objective links whose weights
sum to 1 per item. See docs/METHODOLOGY.md.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

METHOD_VERSION_SCORING = "scoring-v1"

ATTEMPT_RULES = ("first", "last")
OMITTED_POLICIES = ("as_incorrect", "exclude")
AGGREGATIONS = ("learner", "class")


def finite_or_none(x) -> float | None:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


def select_attempts(responses: pd.DataFrame, rule: str = "first") -> pd.DataFrame:
    """Keep exactly one attempt per (learner, item). ``first`` = lowest attempt number, ``last`` = highest.

    A learner who re-took an item is never counted as an extra learner or extra observation."""
    if rule not in ATTEMPT_RULES:
        raise ValueError(f"unknown attempt rule {rule}")
    if responses.empty:
        return responses.copy()
    ordered = responses.sort_values(["learner_id", "item_id", "attempt"], ascending=[True, True, rule == "first"])
    return ordered.drop_duplicates(["learner_id", "item_id"], keep="first").reset_index(drop=True)


def item_unit_weights(links: pd.DataFrame, unit_of_objective: dict[str, str], unit: str) -> pd.DataFrame:
    """Weight of each item for an analysis unit (a topic or an objective).

    ``links``: columns item_id, objective_id, weight (weights of one item sum to 1).
    For a topic the weight is the sum of the item's link weights to objectives of that topic, so an item
    linked to two objectives of the same topic contributes 1, and an item split across two topics
    contributes its share to each. Returns columns item_id, w."""
    if links.empty:
        return pd.DataFrame(columns=["item_id", "w"])
    sel = links[links["objective_id"].map(lambda o: unit_of_objective.get(o) == unit)]
    if sel.empty:
        return pd.DataFrame(columns=["item_id", "w"])
    return sel.groupby("item_id", as_index=False)["weight"].sum().rename(columns={"weight": "w"})


def learner_unit_scores(
    responses: pd.DataFrame,
    item_weights: pd.DataFrame,
    omitted_policy: str = "as_incorrect",
) -> pd.DataFrame:
    """Score share per learner for one unit: sum(w*score)/sum(w*max).

    * answered rows contribute their measured score (0 is a real zero);
    * omitted rows contribute 0 earned (``as_incorrect``) or are dropped from numerator and
      denominator (``exclude``);
    * learners absent from the sitting have no rows and therefore no score (never 0).
    Returns learner_id, cohort_id, school_id, teacher_id, earned, possible, score, n_items, n_omitted."""
    if omitted_policy not in OMITTED_POLICIES:
        raise ValueError(f"unknown omitted policy {omitted_policy}")
    cols = ["learner_id", "cohort_id", "school_id", "teacher_id", "earned", "possible", "score", "n_items", "n_omitted"]
    if responses.empty or item_weights.empty:
        return pd.DataFrame(columns=cols)
    df = responses.merge(item_weights, on="item_id", how="inner")
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["is_omitted"] = df["status"] == "omitted"
    if omitted_policy == "exclude":
        df = df[~df["is_omitted"]]
    df["earned"] = np.where(df["is_omitted"], 0.0, df["score"].fillna(0.0)) * df["w"]
    df["possible"] = df["max_points"] * df["w"]
    g = df.groupby(["learner_id", "cohort_id", "school_id", "teacher_id"], dropna=False, as_index=False).agg(
        earned=("earned", "sum"),
        possible=("possible", "sum"),
        n_items=("item_id", "nunique"),
        n_omitted=("is_omitted", "sum"),
    )
    g = g[g["possible"] > 0].copy()
    g["score"] = g["earned"] / g["possible"]
    return g[cols].reset_index(drop=True)


@dataclass
class MeanSummary:
    mean: float | None
    ci_low: float | None
    ci_high: float | None
    ci_method: str | None
    ci_unavailable_reason: str | None
    n_learners: int
    n_classes: int
    n_schools: int
    aggregation: str

    def as_dict(self) -> dict:
        return {
            "mean": finite_or_none(self.mean),
            "ci_low": finite_or_none(self.ci_low),
            "ci_high": finite_or_none(self.ci_high),
            "ci_method": self.ci_method,
            "ci_unavailable_reason": self.ci_unavailable_reason,
            "n_learners": self.n_learners,
            "n_classes": self.n_classes,
            "n_schools": self.n_schools,
            "aggregation": self.aggregation,
        }


MIN_CLUSTERS_FOR_CI = 5


def summarize_scores(scores: pd.DataFrame, aggregation: str = "learner", confidence: float = 0.95) -> MeanSummary:
    """Aggregate learner scores. Learner-level: mean over learners with a cluster-robust (class) standard
    error and t(G-1) interval. Class-level: mean of class means with t(G-1) interval over class means.

    Responses are never treated as independent observations; the cluster is the class."""
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"unknown aggregation {aggregation}")
    if scores.empty:
        return MeanSummary(None, None, None, None, "no_data", 0, 0, 0, aggregation)
    n = len(scores)
    G = scores["cohort_id"].nunique()
    S = scores["school_id"].nunique()
    y = scores["score"].to_numpy(dtype=float)
    if aggregation == "learner":
        mean = float(y.mean())
        if G < MIN_CLUSTERS_FOR_CI:
            return MeanSummary(mean, None, None, None, "too_few_clusters", n, G, S, aggregation)
        resid = scores.assign(r=y - mean).groupby("cohort_id")["r"].sum().to_numpy()
        se = math.sqrt(G / (G - 1) * float((resid**2).sum())) / n
        method = "cluster_robust_t_class"
    else:
        class_means = scores.groupby("cohort_id")["score"].mean().to_numpy()
        mean = float(class_means.mean())
        if G < MIN_CLUSTERS_FOR_CI:
            return MeanSummary(mean, None, None, None, "too_few_clusters", n, G, S, aggregation)
        se = float(class_means.std(ddof=1)) / math.sqrt(G)
        method = "t_over_class_means"
    tcrit = float(stats.t.ppf(0.5 + confidence / 2, df=G - 1))
    lo, hi = mean - tcrit * se, mean + tcrit * se
    return MeanSummary(mean, max(0.0, lo), min(1.0, hi), method, None, n, G, S, aggregation)


def item_statistics(responses: pd.DataFrame) -> pd.DataFrame:
    """Per-item counts on the selected attempts: answered, omitted, mean score among answered."""
    if responses.empty:
        return pd.DataFrame(columns=["item_id", "n_answered", "n_omitted", "p_correct", "omit_rate"])
    df = responses.copy()
    df["answered"] = df["status"] == "answered"
    df["omitted"] = df["status"] == "omitted"
    df["share"] = np.where(df["answered"], df["score"] / df["max_points"], np.nan)
    g = df.groupby("item_id", as_index=False).agg(
        n_answered=("answered", "sum"), n_omitted=("omitted", "sum"), p_correct=("share", "mean")
    )
    total = g["n_answered"] + g["n_omitted"]
    g["omit_rate"] = np.where(total > 0, g["n_omitted"] / total, np.nan)
    return g


def distractor_counts(responses: pd.DataFrame) -> pd.DataFrame:
    """Counts of chosen options per item among answered rows."""
    if responses.empty:
        return pd.DataFrame(columns=["item_id", "response_value", "count"])
    df = responses[(responses["status"] == "answered") & responses["response_value"].notna()]
    return df.groupby(["item_id", "response_value"], as_index=False).size().rename(columns={"size": "count"})


def counts(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"n_learners": 0, "n_classes": 0, "n_schools": 0}
    return {
        "n_learners": int(frame["learner_id"].nunique()),
        "n_classes": int(frame["cohort_id"].nunique()),
        "n_schools": int(frame["school_id"].nunique()),
    }


def iter_units(values: Iterable[str]) -> list[str]:
    return sorted(set(values))
