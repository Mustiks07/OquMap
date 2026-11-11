"""Assessment Quality Lab — pure functions (no database access).

Method ``aq-v1`` (docs/ASSESSMENT_QUALITY.md). All statistics are computed **within one administration of one
form** (an ``Assessment``); different forms / scales are never pooled.

Input frame ``responses`` (one row per *selected* attempt, see ``select_attempts``) has columns:
    learner_id, item_id, status (answered|omitted), score (float|None), max_points, response_value
``present`` is the list of learners with a ``present`` sitting. Absent learners have no score (never 0).
A present learner without a row for an item is counted as ``missing`` (not shown / not reached / not
recorded) — separately from ``omitted`` (shown and skipped) and from wrong answers (answered, score 0).

Every statistic that cannot be computed returns ``None`` together with an explicit reason code. Flags are
review signals for a methodist, never an automatic verdict on an item.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .scoring import finite_or_none

METHOD_VERSION_QUALITY = "aq-v1"

# Minimum sizes (pre-registered, documented in docs/ASSESSMENT_QUALITY.md)
MIN_LEARNERS_ALPHA = 30
MIN_ITEMS_ALPHA = 3
MIN_LEARNERS_ITEM_TOTAL = 30
MIN_LEARNERS_UPPER_LOWER = 30
UPPER_LOWER_SHARE = 0.27  # Kelley's 27% rule
MIN_SLICE_LEARNERS = 20
MIN_ANSWERED_DISTRACTOR = 20

# Review-signal thresholds (conventional screening values, not verdicts)
TOO_EASY_P = 0.90
TOO_HARD_P = 0.20
LOW_DISCRIMINATION = 0.20
HIGH_OMISSION = 0.10
NON_FUNCTIONAL_SHARE = 0.05


@dataclass
class Stat:
    value: float | None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"value": finite_or_none(self.value), "unavailable_reason": None if finite_or_none(self.value) is not None else (self.reason or "not_computable")}


@dataclass
class ItemMeta:
    item_id: str
    code: str
    max_points: float
    answer_key: str | None
    options: list[dict] = field(default_factory=list)  # [{key, text, correct, misconception}]


# ---------------------------------------------------------------------------
# Elementary statistics
# ---------------------------------------------------------------------------


def pearson(x: np.ndarray, y: np.ndarray) -> Stat:
    """Pearson correlation with explicit reasons (zero variance / too few pairs)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        return Stat(None, "too_few_pairs")
    sx, sy = x.std(), y.std()
    if sx == 0 or sy == 0:
        return Stat(None, "zero_variance")
    return Stat(float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy)))


def cronbach_alpha(matrix: np.ndarray, min_learners: int = MIN_LEARNERS_ALPHA, min_items: int = MIN_ITEMS_ALPHA) -> Stat:
    """alpha = k/(k-1) * (1 - sum(var_item) / var_total) on a complete learner × item matrix of item score
    shares. Sample variances (ddof=1). Not computed when n or k is too small or total variance is zero."""
    mat = np.asarray(matrix, dtype=float)
    if mat.ndim != 2 or mat.shape[1] < min_items:
        return Stat(None, "too_few_items")
    mat = mat[np.isfinite(mat).all(axis=1)]
    n, k = mat.shape
    if n < min_learners:
        return Stat(None, "too_few_learners")
    total_var = mat.sum(axis=1).var(ddof=1)
    if total_var <= 0:
        return Stat(None, "zero_total_variance")
    item_var = mat.var(axis=0, ddof=1).sum()
    return Stat(float(k / (k - 1) * (1 - item_var / total_var)))


def upper_lower_discrimination(item_share: np.ndarray, rest_total: np.ndarray, learner_ids: list[str],
                               share: float = UPPER_LOWER_SHARE, min_learners: int = MIN_LEARNERS_UPPER_LOWER) -> dict:
    """D = mean item share in the upper group − mean item share in the lower group.

    Rule (documented): learners are ordered by the *corrected* total (rest score, the item itself excluded),
    ties broken by learner id for determinism; each group holds floor(27% · n) learners."""
    n = len(item_share)
    if n < min_learners:
        return {"value": None, "unavailable_reason": "too_few_learners", "group_size": 0, "p_upper": None, "p_lower": None}
    order = sorted(range(n), key=lambda i: (rest_total[i], learner_ids[i]))
    g = int(math.floor(share * n))
    lower = [item_share[i] for i in order[:g]]
    upper = [item_share[i] for i in order[-g:]]
    pu, pl = float(np.mean(upper)), float(np.mean(lower))
    return {"value": pu - pl, "unavailable_reason": None, "group_size": g, "p_upper": pu, "p_lower": pl}


def distribution(scores: np.ndarray, bins: int = 10) -> dict:
    """Summary of normalised total scores (0..1)."""
    s = np.asarray(scores, dtype=float)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None, "floor_share": None,
                "ceiling_share": None, "histogram": [], "unavailable_reason": "no_present_learners"}
    edges = np.linspace(0, 1, bins + 1)
    counts, _ = np.histogram(np.clip(s, 0, 1), bins=edges)
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(np.median(s)),
        "sd": float(s.std(ddof=1)) if len(s) > 1 else None,
        "min": float(s.min()),
        "max": float(s.max()),
        "floor_share": float((s <= 0).mean()),
        "ceiling_share": float((s >= 1).mean()),
        "histogram": [{"from": float(edges[i]), "to": float(edges[i + 1]), "count": int(counts[i])} for i in range(bins)],
        "unavailable_reason": None,
    }


# ---------------------------------------------------------------------------
# Item × learner matrix
# ---------------------------------------------------------------------------


def item_matrix(responses: pd.DataFrame, present: list[str], item_ids: list[str], items: dict[str, ItemMeta],
                omitted_policy: str = "as_incorrect") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (share matrix, status matrix) indexed by present learners × form items.

    share: score/max for answered; 0 for omitted under ``as_incorrect``; NaN for omitted under ``exclude``
    and for missing rows. status: 'answered' | 'omitted' | 'missing'."""
    idx = pd.Index(sorted(set(present)), name="learner_id")
    share = pd.DataFrame(np.nan, index=idx, columns=item_ids)
    status = pd.DataFrame("missing", index=idx, columns=item_ids)
    if responses.empty or len(idx) == 0:
        return share, status
    df = responses[responses["learner_id"].isin(idx) & responses["item_id"].isin(item_ids)]
    for r in df.itertuples(index=False):
        mp = items[r.item_id].max_points or 1.0
        if r.status == "answered":
            share.at[r.learner_id, r.item_id] = float(r.score or 0.0) / mp
            status.at[r.learner_id, r.item_id] = "answered"
        elif r.status == "omitted":
            status.at[r.learner_id, r.item_id] = "omitted"
            share.at[r.learner_id, r.item_id] = 0.0 if omitted_policy == "as_incorrect" else np.nan
    return share, status


def learner_totals(share: pd.DataFrame, items: dict[str, ItemMeta]) -> pd.Series:
    """Normalised total = Σ points / Σ max_points over items with a usable value (partial credit safe)."""
    mp = np.array([items[c].max_points or 1.0 for c in share.columns])
    pts = share.to_numpy() * mp
    usable = np.isfinite(pts)
    earned = np.where(usable, pts, 0).sum(axis=1)
    possible = (usable * mp).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        tot = np.where(possible > 0, earned / possible, np.nan)
    return pd.Series(tot, index=share.index)


# ---------------------------------------------------------------------------
# Form-level and item-level analysis
# ---------------------------------------------------------------------------


def form_quality(share: pd.DataFrame, status: pd.DataFrame, items: dict[str, ItemMeta], counts: dict) -> dict:
    """Form metrics with correct denominators. ``counts``: assigned, present, absent, no_record."""
    n_present = len(share.index)
    k = len(share.columns)
    expected = n_present * k
    st = status.to_numpy()
    answered = int((st == "answered").sum())
    omitted = int((st == "omitted").sum())
    missing = int((st == "missing").sum())
    totals = learner_totals(share, items)
    # alpha on complete cases (missing rows — and omitted under 'exclude' — make a learner incomplete)
    alpha = cronbach_alpha(share.to_numpy())
    complete = int(np.isfinite(share.to_numpy()).all(axis=1).sum()) if k else 0
    zero_var = [c for c in share.columns if np.nanvar(share[c].to_numpy(dtype=float)) == 0] if n_present else []
    assigned = counts.get("assigned", 0)
    return {
        "denominators": {
            "assigned": assigned, "present": counts.get("present", n_present), "absent": counts.get("absent", 0),
            "no_sitting_record": counts.get("no_record", 0), "n_items": k, "expected_item_responses": expected,
        },
        "participation_rate": (counts.get("present", n_present) / assigned) if assigned else None,
        "completion_rate": (answered / expected) if expected else None,
        "omission_rate": (omitted / expected) if expected else None,
        "missing_rate": (missing / expected) if expected else None,
        "item_responses": {"answered": answered, "omitted": omitted, "missing": missing},
        "score_distribution": distribution(totals.to_numpy()),
        "reliability": {
            "cronbach_alpha": alpha.as_dict(),
            "n_complete_learners": complete,
            "n_items": k,
            "n_zero_variance_items": len(zero_var),
            "min_learners": MIN_LEARNERS_ALPHA,
            "min_items": MIN_ITEMS_ALPHA,
            "note": "complete_cases_item_share_matrix",
        },
    }


def item_quality(item_id: str, share: pd.DataFrame, status: pd.DataFrame, responses: pd.DataFrame,
                 items: dict[str, ItemMeta], totals: pd.Series) -> dict:
    meta = items[item_id]
    col_share = share[item_id]
    col_status = status[item_id]
    n_present = int(len(col_share))
    n_answered = int((col_status == "answered").sum())
    n_omitted = int((col_status == "omitted").sum())
    n_missing = int((col_status == "missing").sum())
    usable = col_share.dropna()
    p_value = float(usable.mean()) if len(usable) else None
    answered_share = col_share[col_status == "answered"]
    p_answered = float(answered_share.mean()) if len(answered_share) else None

    # corrected (rest) total: the learner's total without this item, same normalisation
    others = [c for c in share.columns if c != item_id]
    rest = learner_totals(share[others], items) if others else pd.Series(np.nan, index=share.index)
    both = pd.DataFrame({"item": col_share, "rest": rest}).dropna()
    if len(both) < MIN_LEARNERS_ITEM_TOTAL:
        r_it = Stat(None, "too_few_learners")
    else:
        r_it = pearson(both["item"].to_numpy(), both["rest"].to_numpy())
    ul = upper_lower_discrimination(both["item"].tolist(), both["rest"].tolist(), [str(i) for i in both.index])

    # distractor analysis on answered rows
    rv = responses[(responses["item_id"] == item_id) & (responses["status"] == "answered")]
    rv = rv[rv["learner_id"].isin(share.index)]
    chosen = rv.set_index("learner_id")["response_value"].astype("string").str.strip().str.upper()
    option_rows = []
    known_keys = set()
    key = (meta.answer_key or "").strip().upper()
    for opt in meta.options:
        okey = str(opt.get("key", "")).strip().upper()
        known_keys.add(okey)
        who = chosen[chosen == okey].index
        cnt = int(len(who))
        rest_vals = rest.reindex(who).dropna()
        indicator = pd.Series(0.0, index=rest.dropna().index)
        indicator.loc[indicator.index.intersection(who)] = 1.0
        pb = (pearson(indicator.to_numpy(), rest.dropna().reindex(indicator.index).to_numpy())
              if n_answered >= MIN_ANSWERED_DISTRACTOR else Stat(None, "too_few_answered"))
        option_rows.append({
            "key": opt.get("key"), "text": opt.get("text"), "is_key": okey == key,
            "misconception": opt.get("misconception"), "count": cnt,
            "share_of_answered": (cnt / n_answered) if n_answered else None,
            "mean_rest_score": float(rest_vals.mean()) if len(rest_vals) else None,
            "point_biserial_rest": pb.as_dict(),
        })
    invalid = int((~chosen.isin(list(known_keys))).sum()) if meta.options else 0

    flags = item_flags(p_value, r_it.value, ul["value"], (n_omitted / (n_answered + n_omitted)) if (n_answered + n_omitted) else None,
                       option_rows, n_answered)
    return {
        "item_id": item_id, "code": meta.code, "max_points": meta.max_points,
        "denominators": {"present": n_present, "answered": n_answered, "omitted": n_omitted, "missing": n_missing},
        "p_value": p_value,
        "p_value_definition": "mean_score_share_present_learners_omitted_per_policy",
        "p_value_among_answered": p_answered,
        "omission_rate": (n_omitted / (n_answered + n_omitted)) if (n_answered + n_omitted) else None,
        "missing_rate": (n_missing / n_present) if n_present else None,
        "item_rest_correlation": r_it.as_dict(),
        "upper_lower": ul,
        "options": option_rows,
        "invalid_response_values": invalid,
        "flags": flags,
    }


def item_flags(p: float | None, r_it: float | None, d: float | None, omit: float | None, options: list[dict],
               n_answered: int) -> list[dict]:
    """Review signals. Each flag names the rule that produced it; none is an automatic verdict."""
    out: list[dict] = []

    def add(code: str, severity: str, **params):
        out.append({"code": code, "severity": severity, "params": params})

    if p is not None and p > TOO_EASY_P:
        add("too_easy", "info", p_value=p, threshold=TOO_EASY_P)
    if p is not None and p < TOO_HARD_P:
        add("too_hard", "warn", p_value=p, threshold=TOO_HARD_P)
    disc = [x for x in (r_it, d) if x is not None]
    if disc and min(disc) < 0:
        add("negative_discrimination", "warn", item_rest_r=r_it, upper_lower_d=d)
    elif disc and min(disc) < LOW_DISCRIMINATION:
        add("low_discrimination", "info", item_rest_r=r_it, upper_lower_d=d, threshold=LOW_DISCRIMINATION)
    if omit is not None and omit > HIGH_OMISSION:
        add("high_omission", "warn", omission_rate=omit, threshold=HIGH_OMISSION)
    if n_answered >= MIN_ANSWERED_DISTRACTOR and options:
        key_opt = next((o for o in options if o["is_key"]), None)
        nonfunc = [o["key"] for o in options if not o["is_key"] and (o["share_of_answered"] or 0) < NON_FUNCTIONAL_SHARE]
        if nonfunc:
            add("non_functional_distractors", "info", options=nonfunc, threshold=NON_FUNCTIONAL_SHARE)
        suspicious = []
        for o in options:
            if o["is_key"]:
                continue
            pb = o["point_biserial_rest"]["value"]
            beats_key = (key_opt is not None and o["mean_rest_score"] is not None and key_opt["mean_rest_score"] is not None
                         and o["count"] >= 5 and o["mean_rest_score"] > key_opt["mean_rest_score"])
            if (pb is not None and pb > 0.05) or beats_key:
                suspicious.append(o["key"])
        if suspicious:
            add("suspicious_distractor", "warn", options=suspicious)
        if key_opt is not None and any(o["count"] > key_opt["count"] for o in options if not o["is_key"]):
            add("key_chosen_less_than_distractor", "warn", key=key_opt["key"])
    return out


def suppress_slices(slices: list[dict], min_n: int = MIN_SLICE_LEARNERS) -> list[dict]:
    """Primary suppression of groups below ``min_n`` plus complementary suppression: if exactly one group is
    suppressed, the next smallest group is suppressed too so that it cannot be derived from the total."""
    out = [dict(s) for s in slices]
    small = [s for s in out if s["n"] < min_n]
    for s in small:
        s["suppressed"] = True
    if len(small) == 1:
        rest = sorted([s for s in out if not s.get("suppressed")], key=lambda s: s["n"])
        if rest:
            rest[0]["suppressed"] = True
            rest[0]["suppression"] = "complementary"
    for s in out:
        if s.get("suppressed"):
            s.setdefault("suppression", "primary")
            for k in ("mean", "median", "sd"):
                s[k] = None
            s["n"] = None
        else:
            s["suppressed"] = False
            s["suppression"] = None
    return out
