"""Paired follow-up: when the same learners (stable learner IDs) took both the earlier and the later
measurement on common items of one scale, the within-learner change is estimated directly.

change = mean over learners of (after − before); uncertainty = percentile cluster bootstrap over classes (the
class is resampled with all its learners). Still observed dynamics, not an effect of a decision: without a
control group, maturation and teaching in general also change scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PAIRS = 30
MIN_CLUSTERS = 3
REPLICATES = 1000


def paired_change(before: pd.DataFrame, after: pd.DataFrame, seed: int = 20260911) -> dict:
    """before/after: columns learner_id, cohort_id, score. Returns availability, n, mean change and CI."""
    if before.empty or after.empty:
        return {"available": False, "reason": "no_scores", "n_pairs": 0}
    b = before.groupby("learner_id").agg(before=("score", "mean"), cohort_id=("cohort_id", "first"))
    a = after.groupby("learner_id").agg(after=("score", "mean"))
    pairs = b.join(a, how="inner").dropna()
    n = int(len(pairs))
    if n == 0:
        return {"available": False, "reason": "no_shared_learner_ids", "n_pairs": 0}
    clusters = pairs["cohort_id"].nunique()
    if n < MIN_PAIRS or clusters < MIN_CLUSTERS:
        return {"available": False, "reason": "too_few_pairs", "n_pairs": n, "n_classes": int(clusters)}
    pairs = pairs.assign(d=pairs["after"] - pairs["before"])
    by = {c: g["d"].to_numpy() for c, g in pairs.groupby("cohort_id")}
    keys = list(by)
    rng = np.random.default_rng(seed)
    reps = np.empty(REPLICATES)
    for i in range(REPLICATES):
        pick = rng.integers(0, len(keys), len(keys))
        reps[i] = np.concatenate([by[keys[j]] for j in pick]).mean()
    low, high = np.percentile(reps, [2.5, 97.5])
    return {"available": True, "n_pairs": n, "n_classes": int(clusters), "before": float(pairs["before"].mean()),
            "after": float(pairs["after"].mean()), "mean_change": float(pairs["d"].mean()),
            "ci": {"low": float(low), "high": float(high)}, "method": "paired_cluster_bootstrap_percentile",
            "replicates": REPLICATES}
