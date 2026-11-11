"""Follow-up measurement and the learning loop (method ``loop-v1``, docs/LEARNING_LOOP.md).

Outcome of a pilot = change in the learner score share on the pilot's topic/objective between the baseline and
the outcome assessment, measured on one scale:
* identical form → all items of the topic/objective; same scale with a linking method → common items only;
  otherwise the result is ``invalid_due_to_comparability`` (no change is computed across unlinked scales);
* paired analysis only for learners present at both measurements (``matched``); absent learners are never 0;
* uncertainty: cluster-robust (class) standard error with t(G−1); no interval below 5 classes per arm;
* comparison designs: difference of mean paired changes (DiD); optional pre-registered adjustment by baseline
  strata (direct standardisation, cluster bootstrap) — only when declared in the analysis plan;
* status rules are fixed and ordered; low/unknown fidelity → ``invalid_due_to_fidelity`` (never "ineffective");
* the causal level is derived from the design and data checks, never from a model's confidence.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..analytics import scoring
from ..analytics.comparison import STRATA_SCHEMES, assign_stratum
from ..config import CODE_VERSION
from ..db import new_id, utcnow
from ..errors import ApiError, forbidden, not_found
from ..schemas import interventions as S
from . import analysis as an
from . import interventions as ivs
from .auth import Principal
from .common import audit, fingerprint
from .fidelity import DETAIL_ROLES, fidelity_for, logs_fingerprint
from .measurement_messages import CAUSAL_LEVELS, FIDELITY_LABELS, STATUS_LABELS, label, render
from .pilots import get_pilot, pilot_cohorts

METHOD_VERSION_LOOP = "loop-v1"
MIN_CLUSTERS_CI = 5
MIN_COHORT_CELL = 10
HIGH_ATTRITION = 0.40
MODERATE_ATTRITION = 0.20
DIFFERENTIAL_ATTRITION = 0.10
BASELINE_IMBALANCE = 0.10
HETEROGENEITY_SHARE = 1 / 3
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 20261111


# ---------------------------------------------------------------------------
# Pure statistics
# ---------------------------------------------------------------------------


def cluster_mean(values: np.ndarray, clusters: np.ndarray, min_clusters: int = MIN_CLUSTERS_CI) -> dict:
    """Mean with a cluster-robust SE: SE = sqrt(G/(G−1) · Σ_g (Σ_{i∈g}(y_i − ȳ))²) / n; CI = ȳ ± t(G−1)·SE."""
    y = np.asarray(values, dtype=float)
    g = np.asarray(clusters)
    n = len(y)
    G = len(set(g.tolist()))
    if n == 0:
        return {"mean": None, "se": None, "ci_low": None, "ci_high": None, "n": 0, "n_clusters": 0, "df": None,
                "ci_unavailable_reason": "no_data"}
    mean = float(y.mean())
    out = {"mean": mean, "se": None, "ci_low": None, "ci_high": None, "n": n, "n_clusters": G, "df": None,
           "ci_unavailable_reason": None}
    if G < min_clusters:
        out["ci_unavailable_reason"] = "too_few_clusters"
        return out
    resid = pd.Series(y - mean).groupby(g).sum().to_numpy()
    se = math.sqrt(G / (G - 1) * float((resid ** 2).sum())) / n
    t = float(stats.t.ppf(0.975, G - 1))
    out.update({"se": se, "df": G - 1, "ci_low": mean - t * se, "ci_high": mean + t * se})
    return out


def difference_of_means(a: dict, b: dict) -> dict:
    """a − b with SE = sqrt(SE_a² + SE_b²) and conservative df = min(G_a, G_b) − 1."""
    if a["mean"] is None or b["mean"] is None:
        return {"estimate": None, "se": None, "ci_low": None, "ci_high": None, "df": None, "ci_unavailable_reason": "no_data"}
    est = a["mean"] - b["mean"]
    if a["se"] is None or b["se"] is None:
        return {"estimate": est, "se": None, "ci_low": None, "ci_high": None, "df": None,
                "ci_unavailable_reason": a["ci_unavailable_reason"] or b["ci_unavailable_reason"] or "too_few_clusters"}
    se = math.sqrt(a["se"] ** 2 + b["se"] ** 2)
    df = min(a["n_clusters"], b["n_clusters"]) - 1
    t = float(stats.t.ppf(0.975, df))
    return {"estimate": est, "se": se, "ci_low": est - t * se, "ci_high": est + t * se, "df": df, "ci_unavailable_reason": None}


def standardized_change(df: pd.DataFrame, weights: dict[str, float]) -> float | None:
    total = 0.0
    for k, w in weights.items():
        if w <= 0:
            continue
        sub = df[df["stratum"] == k]
        if sub.empty:
            return None
        total += w * float(sub["change"].mean())
    return total


def adjusted_did(matched: pd.DataFrame, scheme: str, seed: int = BOOTSTRAP_SEED, replicates: int = BOOTSTRAP_REPLICATES) -> dict:
    """Pre-registered adjustment: direct standardisation of paired changes over baseline strata with pooled
    weights; percentile cluster bootstrap (classes resampled within arm)."""
    d = matched.copy()
    d["stratum"] = d["pre"].map(lambda s: assign_stratum(s, scheme))
    strata = [k for k, _ in STRATA_SCHEMES[scheme]]
    weights = {k: float((d["stratum"] == k).mean()) for k in strata}
    arms = {a: d[d["arm"] == a] for a in ("intervention", "comparison")}
    si, sc = standardized_change(arms["intervention"], weights), standardized_change(arms["comparison"], weights)
    if si is None or sc is None:
        return {"estimate": None, "ci_low": None, "ci_high": None, "weights": weights, "unavailable_reason": "empty_stratum"}
    est = si - sc
    G = {a: arms[a]["cohort_id"].nunique() for a in arms}
    if min(G.values()) < MIN_CLUSTERS_CI:
        return {"estimate": est, "ci_low": None, "ci_high": None, "weights": weights, "unavailable_reason": "too_few_clusters"}
    rng = np.random.default_rng(seed)
    groups = {a: [g for _, g in arms[a].groupby("cohort_id")] for a in arms}
    reps = []
    for _ in range(replicates):
        vals = []
        for a in ("intervention", "comparison"):
            pick = rng.integers(0, len(groups[a]), len(groups[a]))
            vals.append(standardized_change(pd.concat([groups[a][i] for i in pick]), weights))
        if None not in vals:
            reps.append(vals[0] - vals[1])
    if len(reps) < 0.95 * replicates:
        return {"estimate": est, "ci_low": None, "ci_high": None, "weights": weights, "unavailable_reason": "bootstrap_invalid_share"}
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return {"estimate": est, "ci_low": float(lo), "ci_high": float(hi), "weights": weights, "unavailable_reason": None,
            "method": f"direct_standardisation_{scheme}_cluster_bootstrap_{replicates}"}


def decide_status(*, comparability_ok: bool, has_outcome: bool, analysis_supported: bool, n_matched: int, min_matched: int,
                  fidelity: str, attrition: float | None, ci: tuple[float | None, float | None], heterogeneous: bool) -> tuple[str, list[str]]:
    """Ordered, documented status rules (loop-v1). Returns (status, rule codes that fired)."""
    if not comparability_ok:
        return "invalid_due_to_comparability", ["forms_not_comparable"]
    if not has_outcome:
        return "needs_more_data", ["no_outcome_assessment"]
    if not analysis_supported:
        return "needs_more_data", ["analysis_not_implemented_for_design"]
    if n_matched < min_matched:
        return "needs_more_data", ["too_few_matched"]
    if fidelity in ("low", "unknown"):
        return "invalid_due_to_fidelity", [f"fidelity_{fidelity}"]
    if attrition is not None and attrition > HIGH_ATTRITION:
        return "needs_more_data", ["high_attrition"]
    lo, hi = ci
    if lo is None or hi is None:
        return "needs_more_data", ["too_few_clusters_ci"]
    if lo > 0:
        fired = (["fidelity_moderate"] if fidelity == "moderate" else []) + (["cohort_heterogeneity"] if heterogeneous else [])
        return ("mixed", fired) if fired else ("positive_signal", ["ci_above_zero"])
    if hi < 0:
        return "not_confirmed", ["negative_change_observed"]
    return "not_confirmed", ["ci_includes_zero"]


def achieved_causal_level(status: str, design: str, ceiling: str, *, adjusted_used: bool, baseline_imbalance: bool,
                          fidelity: str, attrition: float | None, differential: bool, randomization_ok: bool) -> str:
    if status in ("invalid_due_to_comparability", "invalid_due_to_fidelity", "needs_more_data"):
        return "none"
    if design == "single_group":
        return "descriptive_change"
    if design == "matched_comparison":
        if ceiling == "adjusted_association" and adjusted_used:
            return "adjusted_association"
        return "descriptive_comparison"
    if design in ("cluster_randomized", "stepped_wedge"):
        if randomization_ok and fidelity == "high" and (attrition or 0) <= MODERATE_ATTRITION and not differential and not baseline_imbalance:
            return "causal_estimate"
        return "adjusted_association" if adjusted_used else "descriptive_comparison"
    return "descriptive_comparison"


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _comparability(meta: an.DatasetFrame, baseline: m.Assessment, outcome: m.Assessment) -> tuple[bool, set[str], dict]:
    bf, of = meta.forms[baseline.form_id], meta.forms[outcome.form_id]
    bs, os_ = meta.scales[bf.scale_id], meta.scales[of.scale_id]
    params = {"baseline_form": bf.code, "baseline_scale": bs.code, "outcome_form": of.code, "outcome_scale": os_.code}
    if bf.id == of.id:
        return True, set(meta.form_items[bf.id]), {"code": "identical_form", **params}
    if bf.scale_id == of.scale_id and bs.linking_method != "none":
        common = set(meta.form_items[bf.id]) & set(meta.form_items[of.id])
        return bool(common), common, {"code": "common_items_only", **params}
    return False, set(), {"code": "forms_not_comparable", **params}


def _unit_weights(meta: an.DatasetFrame, pl: mm.Pilot, items: set[str]) -> pd.DataFrame:
    links = an.effective_links(meta, "confirmed_only")
    if pl.objective_id:
        w = scoring.item_unit_weights(links, {o.id: o.id for o in meta.objectives}, pl.objective_id)
    else:
        w = scoring.item_unit_weights(links, {o.id: o.topic_id for o in meta.objectives}, pl.topic_id)
    return w[w["item_id"].isin(items)]


def _scores(session: Session, meta: an.DatasetFrame, assessment: m.Assessment, weights: pd.DataFrame, plan: dict,
            learner_ids: set[str]) -> pd.DataFrame:
    resp = an.load_responses(session, meta, [assessment.id])
    resp = resp[resp["learner_id"].isin(learner_ids)]
    resp = scoring.select_attempts(resp, plan.get("attempt_rule", "first"))
    return scoring.learner_unit_scores(resp, weights, plan.get("omitted_policy", "as_incorrect"))[["learner_id", "cohort_id", "score"]]


def _present(session: Session, assessment_id: str, learner_ids: set[str]) -> tuple[set[str], set[str]]:
    rows = session.execute(select(m.Sitting.learner_id, m.Sitting.status).where(m.Sitting.assessment_id == assessment_id)).all()
    present = {lid for lid, st in rows if st == "present" and lid in learner_ids}
    absent = {lid for lid, st in rows if st == "absent" and lid in learner_ids}
    return present, absent


def _round(x):
    return None if x is None else float(x)


def compute_outcome(session: Session, pl: mm.Pilot, outcome_assessment_id: str | None, as_of: date | None,
                    detail: bool) -> dict:
    meta = an.load_meta(session, pl.org_id, pl.dataset_id)
    plan = pl.analysis_plan or {}
    min_matched = int(plan.get("min_matched_learners", 30))
    cohorts = pilot_cohorts(session, pl)
    arm_of = {c.cohort_id: c.arm for c in cohorts}
    learners = pd.DataFrame(session.execute(select(m.Learner.id, m.Learner.cohort_id).where(
        m.Learner.cohort_id.in_(list(arm_of)), m.Learner.org_id == pl.org_id)).all(), columns=["learner_id", "cohort_id"])
    learners["arm"] = learners["cohort_id"].map(arm_of)
    ids = set(learners["learner_id"])
    fid = fidelity_for(session, pl, as_of)
    fid_class = fid["overall"]["classification"]["code"]
    design = pl.design
    comparison_design = design in ("matched_comparison", "cluster_randomized")
    reasons: list[dict] = []
    if pl.is_synthetic:
        reasons.append(render("synthetic_data"))
    if pl.status == "active":
        reasons.append(render("interim_result", {}, "warn"))
    baseline = meta.assessments.get(pl.baseline_assessment_id or "")
    outcome = meta.assessments.get(outcome_assessment_id or "")
    base_result = {
        "design": design, "assignment_unit": pl.assignment_unit, "analysis_plan": plan, "rules": {
            "min_matched_learners": min_matched, "min_clusters_ci": MIN_CLUSTERS_CI, "high_attrition": HIGH_ATTRITION,
            "moderate_attrition": MODERATE_ATTRITION, "baseline_imbalance": BASELINE_IMBALANCE,
            "heterogeneity_share": HETEROGENEITY_SHARE, "scale": "score_share_0_1_on_pilot_items"},
        "fidelity": {"classification": fid["overall"]["classification"], "metrics": fid["overall"], "as_of": fid["as_of"].isoformat(),
                     "distribution": fid["distribution"]},
        "baseline_assessment": baseline.code if baseline else None, "outcome_assessment": outcome.code if outcome else None,
    }
    comparability = {"code": "no_outcome_assessment"}
    comp_ok, items = True, set()
    if baseline is None:
        comp_ok, comparability = False, {"code": "no_baseline_assessment"}
    elif outcome is not None:
        comp_ok, items, comparability = _comparability(meta, baseline, outcome)
    weights = _unit_weights(meta, pl, items) if items else pd.DataFrame(columns=["item_id", "w"])
    if comp_ok and outcome is not None and weights.empty:
        comp_ok, comparability = False, {"code": "no_common_outcome_items", **comparability}
    if not comp_ok and comparability.get("code") in ("forms_not_comparable", "no_common_outcome_items"):
        reasons.append(render(comparability["code"], {k: v for k, v in comparability.items() if k != "code"}, "fail"))
    elif comp_ok and outcome is not None:
        reasons.append(render(comparability["code"], {"n_items": int(len(weights))}, "info"))
    if outcome is None:
        reasons.append(render("no_outcome_assessment", {}, "warn"))

    arms_out: dict[str, dict] = {}
    matched = pd.DataFrame(columns=["learner_id", "cohort_id", "arm", "pre", "post", "change"])
    attrition = {}
    if comp_ok and outcome is not None:
        pre = _scores(session, meta, baseline, weights, plan, ids).rename(columns={"score": "pre"})
        post = _scores(session, meta, outcome, weights, plan, ids).rename(columns={"score": "post"})
        b_present, b_absent = _present(session, baseline.id, ids)
        o_present, o_absent = _present(session, outcome.id, ids)
        matched = learners.merge(pre[["learner_id", "pre"]], on="learner_id").merge(post[["learner_id", "post"]], on="learner_id")
        matched["change"] = matched["post"] - matched["pre"]
        for arm in ("intervention", "comparison"):
            lset = set(learners.loc[learners["arm"] == arm, "learner_id"])
            if not lset:
                continue
            mt = matched[matched["arm"] == arm]
            att = 1 - len(mt) / len(lset)
            attrition[arm] = att
            arms_out[arm] = {
                "assigned": len(lset), "matched": int(len(mt)), "n_classes": int(mt["cohort_id"].nunique()),
                "absent_at_baseline": len(lset & b_absent), "absent_at_outcome": len(lset & o_absent),
                "no_baseline_score": len(lset - set(pre["learner_id"])), "no_outcome_score": len(lset - set(post["learner_id"])),
                "attrition": att,
                "baseline_mean": _round(mt["pre"].mean()) if len(mt) else None,
                "outcome_mean": _round(mt["post"].mean()) if len(mt) else None,
                "change": cluster_mean(mt["change"].to_numpy(), mt["cohort_id"].to_numpy()),
            }
    n_matched = int(len(matched))
    total_assigned = sum(a["assigned"] for a in arms_out.values())
    overall_attr = (1 - n_matched / total_assigned) if total_assigned else None
    differential = bool(len(attrition) == 2 and abs(attrition["intervention"] - attrition.get("comparison", 0)) > DIFFERENTIAL_ATTRITION)
    if overall_attr is not None:
        if overall_attr > HIGH_ATTRITION:
            reasons.append(render("high_attrition", {"attrition": overall_attr, "threshold": HIGH_ATTRITION}, "warn"))
        elif overall_attr > MODERATE_ATTRITION:
            reasons.append(render("moderate_attrition", {"attrition": overall_attr}, "warn"))
    if differential:
        reasons.append(render("differential_attrition", {"a": attrition["intervention"], "b": attrition["comparison"]}, "warn"))

    analysis_supported = design in ("single_group", "matched_comparison", "cluster_randomized")
    if not analysis_supported:
        reasons.append(render("analysis_not_implemented_for_design", {"design": design}, "warn"))
    primary = {"estimand": "mean_paired_change" if not comparison_design else "difference_in_mean_changes",
               "estimate": None, "ci_low": None, "ci_high": None, "ci_unavailable_reason": None, "source": "raw"}
    raw = None
    adjusted = None
    imbalance = False
    if "intervention" in arms_out:
        ci_i = arms_out["intervention"]["change"]
        if comparison_design and "comparison" in arms_out:
            raw = difference_of_means(ci_i, arms_out["comparison"]["change"])
            bi, bc = arms_out["intervention"]["baseline_mean"], arms_out["comparison"]["baseline_mean"]
            if bi is not None and bc is not None and abs(bi - bc) > BASELINE_IMBALANCE:
                imbalance = True
                reasons.append(render("baseline_imbalance", {"diff": abs(bi - bc), "threshold": BASELINE_IMBALANCE}, "warn"))
            if plan.get("adjustment") == "baseline_strata":
                adjusted = adjusted_did(matched, plan.get("strata_scheme", "pre_three_level"))
        elif not comparison_design:
            raw = {"estimate": ci_i["mean"], "se": ci_i["se"], "ci_low": ci_i["ci_low"], "ci_high": ci_i["ci_high"],
                   "df": ci_i["df"], "ci_unavailable_reason": ci_i["ci_unavailable_reason"]}
        if raw is not None:
            use_adj = adjusted is not None and adjusted["estimate"] is not None
            src = adjusted if use_adj else raw
            primary.update({"estimate": src["estimate"], "ci_low": src["ci_low"], "ci_high": src["ci_high"],
                            "ci_unavailable_reason": src.get("ci_unavailable_reason") or src.get("unavailable_reason"),
                            "source": "adjusted" if use_adj else "raw"})
            if primary["ci_low"] is None and primary["estimate"] is not None:
                n_cl = arms_out["intervention"]["n_classes"]
                reasons.append(render("too_few_clusters_ci", {"n_clusters": n_cl, "min": MIN_CLUSTERS_CI}, "warn"))
    # cohort heterogeneity among intervention cohorts
    cohort_rows = []
    n_neg = n_tot = 0
    for cid, g in matched.groupby("cohort_id"):
        arm = arm_of.get(cid)
        mean_change = float(g["change"].mean())
        if arm == "intervention":
            n_tot += 1
            n_neg += int(mean_change < 0)
        co = meta.cohorts.get(cid)
        small = len(g) < MIN_COHORT_CELL
        cohort_rows.append({"cohort_id": cid, "code": co.code if co else None, "arm": arm,
                            "n_matched": None if small else int(len(g)),
                            "mean_change": None if small else mean_change, "suppressed": small})
    heterogeneous = n_tot >= 3 and n_neg / n_tot >= HETEROGENEITY_SHARE
    if heterogeneous:
        reasons.append(render("cohort_heterogeneity", {"n_negative": n_neg, "n_total": n_tot}, "warn"))
    if fid_class in ("low", "unknown", "moderate"):
        reasons.append(render(f"fidelity_{fid_class}", {}, "warn" if fid_class != "moderate" else "info"))
    if design == "single_group":
        reasons.append(render("single_group_no_causal", {}, "info"))
    elif design == "matched_comparison":
        reasons.append(render("observational_comparison", {}, "info"))

    status, fired = decide_status(comparability_ok=comp_ok, has_outcome=outcome is not None, analysis_supported=analysis_supported,
                                  n_matched=n_matched, min_matched=min_matched, fidelity=fid_class, attrition=overall_attr,
                                  ci=(primary["ci_low"], primary["ci_high"]), heterogeneous=heterogeneous)
    if "too_few_matched" in fired:
        reasons.append(render("too_few_matched", {"n": n_matched, "min": min_matched}, "warn"))
    if "negative_change_observed" in fired:
        reasons.append(render("negative_change_observed", {}, "warn"))
    rnd_ok = bool(pl.randomization) and design in ("cluster_randomized", "stepped_wedge")
    level = achieved_causal_level(status, design, pl.causal_ceiling, adjusted_used=primary["source"] == "adjusted",
                                  baseline_imbalance=imbalance, fidelity=fid_class, attrition=overall_attr,
                                  differential=differential, randomization_ok=rnd_ok)
    interpretation_ru = {
        "positive_signal": "Положительный сигнал при указанных ограничениях дизайна; повторите в другой когорте, прежде чем расширять.",
        "mixed": "Сигнал положительный, но реализация или результаты по классам неоднородны: требуется разбор до решения о расширении.",
        "not_confirmed": "Данные не подтверждают изменения, отличимого от неопределённости. Это не доказательство отсутствия эффекта.",
        "needs_more_data": "Данных недостаточно для вывода. Решение о судьбе интервенции по этим данным принимать нельзя.",
        "invalid_due_to_fidelity": "Интервенция выполнена не в запланированном объёме: результат нельзя считать проверкой интервенции — "
                                   "ни её эффективности, ни неэффективности.",
        "invalid_due_to_comparability": "Входное и итоговое измерения несопоставимы: изменение не измерено. Нужна сопоставимая форма.",
    }[status]
    return {
        **base_result,
        "comparability": comparability,
        "n_outcome_items": int(len(weights)),
        "arms": arms_out,
        "n_matched": n_matched,
        "attrition": overall_attr,
        "differential_attrition": differential,
        "raw": raw,
        "adjusted": adjusted if adjusted is not None else {"estimate": None, "unavailable_reason":
                                                           "not_preregistered" if comparison_design else "not_applicable_single_group"},
        "primary": primary,
        "status": status,
        "status_rules_fired": fired,
        "causal_level": level,
        "cohorts": cohort_rows if detail else None,
        "cohort_detail_visible": detail,
        "reasons": reasons,
        "interpretation_ru": interpretation_ru,
        "never_automatic": "Статус не меняет рекомендации и библиотеку автоматически; вывод сохраняет человек.",
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def outcome_payload(session: Session, o: mm.PilotOutcome, p: Principal | None = None) -> dict:
    pl = session.get(mm.Pilot, o.pilot_id)
    ds = session.get(m.Dataset, pl.dataset_id)
    result = dict(o.result)
    if p is not None and not (set(p.user.roles or []) & DETAIL_ROLES):
        result["cohorts"] = None
        result["cohort_detail_visible"] = False
    return {"id": o.id, "pilot_id": o.pilot_id, "status": o.status, "status_label": label(STATUS_LABELS, o.status),
            "causal_level": label(CAUSAL_LEVELS, o.causal_level), "causal_ceiling": label(CAUSAL_LEVELS, pl.causal_ceiling),
            "fidelity": label(FIDELITY_LABELS, o.fidelity_class), "method_version": o.method_version,
            "dataset_version": o.dataset_version, "current_dataset_version": ds.version, "is_stale": ds.version != o.dataset_version,
            "interim": o.interim, "created_at": o.created_at.isoformat(), "result": result}


def run_follow_up(session: Session, p: Principal, pilot_id: str, body: S.FollowUpRun) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status not in ("active", "completed"):
        raise ApiError("pilot_not_running", "Повторное измерение доступно для активного или завершённого пилота", 409,
                       {"status": pl.status})
    ds = session.get(m.Dataset, pl.dataset_id)
    if body.outcome_assessment_id and body.outcome_assessment_id != pl.outcome_assessment_id:
        a = session.get(m.Assessment, body.outcome_assessment_id)
        if a is None or a.dataset_id != pl.dataset_id or a.org_id != p.org_id:
            raise not_found("assessment", body.outcome_assessment_id)
        if a.administered_on and pl.start_date and a.administered_on < pl.start_date:
            raise ApiError("outcome_before_start", "Итоговое измерение проведено до начала пилота", 422)
        previous = pl.outcome_assessment_id
        pl.outcome_assessment_id = a.id
        session.add(mm.PilotEvent(org_id=p.org_id, pilot_id=pl.id, from_status=pl.status, to_status=pl.status,
                                  note=f"outcome_assessment:{a.code}", user_id=p.user_id))
        audit(session, p.org_id, p.user_id, "pilot.set_outcome_assessment", "pilot", pl.id, previous=previous, new=a.id)
        session.commit()
    detail = True  # stored result keeps cohort rows; payload hides them from roles without access
    as_of = body.as_of
    fp = fingerprint(pl.id, pl.snapshot_sha256, pl.design, pl.analysis_plan, pl.outcome_assessment_id, ds.version,
                     logs_fingerprint(session, pl), str(as_of or ""), pl.status == "active", METHOD_VERSION_LOOP, CODE_VERSION,
                     sorted((c.cohort_id, c.arm) for c in pilot_cohorts(session, pl)))
    o = session.scalar(select(mm.PilotOutcome).where(mm.PilotOutcome.org_id == p.org_id, mm.PilotOutcome.input_fingerprint == fp))
    if o is None:
        res = an._clean(compute_outcome(session, pl, pl.outcome_assessment_id, as_of, detail))
        o = mm.PilotOutcome(org_id=p.org_id, pilot_id=pl.id, dataset_version=ds.version, outcome_assessment_id=pl.outcome_assessment_id,
                            method_version=METHOD_VERSION_LOOP, input_fingerprint=fp, status=res["status"],
                            causal_level=res["causal_level"], fidelity_class=res["fidelity"]["classification"]["code"],
                            interim=pl.status == "active", result=res, created_by=p.user_id)
        session.add(o)
        session.flush()
        audit(session, p.org_id, p.user_id, "pilot.follow_up", "pilot", pl.id, outcome_id=o.id, status=o.status)
        session.commit()
    return outcome_payload(session, o, p)


def list_outcomes(session: Session, p: Principal, pilot_id: str) -> list[dict]:
    pl = get_pilot(session, p.org_id, pilot_id)
    rows = session.scalars(select(mm.PilotOutcome).where(mm.PilotOutcome.pilot_id == pl.id, mm.PilotOutcome.org_id == p.org_id)
                           .order_by(mm.PilotOutcome.created_at.desc()))
    return [outcome_payload(session, o, p) for o in rows]


def _valid_evidence_ids(session: Session, pl: mm.Pilot, ids: list[str], outcome_id: str) -> list[str]:
    """Evidence ids must belong to this pilot (outcomes, fidelity logs) or to the org's analyses / sources."""
    ok = []
    for eid in dict.fromkeys([outcome_id, *ids]):
        found = (session.scalar(select(mm.PilotOutcome.id).where(mm.PilotOutcome.id == eid, mm.PilotOutcome.pilot_id == pl.id))
                 or session.scalar(select(mm.FidelityLog.id).where(mm.FidelityLog.id == eid, mm.FidelityLog.pilot_id == pl.id))
                 or session.scalar(select(m.AnalysisRun.id).where(m.AnalysisRun.id == eid, m.AnalysisRun.org_id == pl.org_id))
                 or session.scalar(select(m.ContentFragment.id).where(m.ContentFragment.id == eid, m.ContentFragment.org_id == pl.org_id)))
        if not found:
            raise not_found("evidence", eid)
        ok.append(eid)
    return ok


def _next_decision(session: Session, p: Principal, pl: mm.Pilot, o: mm.PilotOutcome, c: mm.PilotConclusion, next_action: str) -> m.Decision:
    """Create the next version of the decision (or a first version) carrying the learning-loop record. The new
    version is a draft; approval follows the existing decision workflow."""
    ds = session.get(m.Dataset, pl.dataset_id)
    topic = session.get(m.Topic, pl.topic_id)
    loop = {"pilot_id": pl.id, "pilot_code": pl.code, "outcome_id": o.id, "outcome_status": o.status,
            "causal_level": o.causal_level, "fidelity_class": o.fidelity_class, "conclusion_id": c.id,
            "decision": c.decision, "summary_ru": c.summary_ru, "evidence_ids": c.evidence_ids,
            "intervention_id": pl.intervention_id, "intervention_version_id": pl.intervention_version_id}
    prev = session.get(m.Decision, pl.decision_id) if pl.decision_id else None
    action = next_action or {"continue": "Продолжить интервенцию по протоколу и повторить измерение.",
                             "modify": "Изменить интервенцию (новая версия) и запустить повторный пилот.",
                             "stop": "Остановить интервенцию; искать другой способ решения проблемы.",
                             "extend_data_collection": "Продолжить сбор данных до достаточного объёма."}[c.decision]
    if prev is not None:
        latest = session.scalar(select(m.Decision).where(m.Decision.decision_group_id == prev.decision_group_id,
                                                         m.Decision.org_id == p.org_id).order_by(m.Decision.version.desc()))
        snap = dict(latest.snapshot or {})
        snap["learning_loop"] = loop
        snap.setdefault("limitations", [])
        d = m.Decision(org_id=p.org_id, decision_group_id=latest.decision_group_id, version=latest.version + 1, dataset_id=ds.id,
                       dataset_version=ds.version, filters=latest.filters, target_group=latest.target_group,
                       topic_id=latest.topic_id, problem=latest.problem, hypothesis=latest.hypothesis, action=action,
                       responsible=latest.responsible, follow_up_date=None, follow_up_criterion=latest.follow_up_criterion,
                       analysis_ids=latest.analysis_ids, plan_analysis_id=latest.plan_analysis_id, snapshot=snap,
                       status="draft", created_by=p.user_id)
        if latest.status == "draft":
            latest.status = "superseded"
    else:
        snap = {"dataset": {"id": ds.id, "name_ru": ds.name_ru, "name_kz": ds.name_kz, "version": ds.version,
                            "is_synthetic": ds.is_synthetic},
                "filters": {}, "analyses": [], "sources": [], "learning_loop": loop,
                "limitations": ["Решение подготовлено по итогам пилота; см. ограничения вывода пилота."]}
        d = m.Decision(org_id=p.org_id, decision_group_id=new_id(), version=1, dataset_id=ds.id, dataset_version=ds.version,
                       filters={}, target_group=f"Классы пилота {pl.code}", topic_id=topic.id,
                       problem=pl.primary_outcome_ru or pl.title, hypothesis=pl.intervention_snapshot.get("title_ru", ""),
                       action=action, responsible=pl.owner or "—", follow_up_criterion="", analysis_ids=[],
                       snapshot=snap, status="draft", created_by=p.user_id)
    session.add(d)
    session.flush()
    audit(session, p.org_id, p.user_id, "decision.from_learning_loop", "decision", d.id, pilot_id=pl.id, conclusion_id=c.id)
    return d


def create_conclusion(session: Session, p: Principal, pilot_id: str, body: S.ConclusionCreate) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    o = session.scalar(select(mm.PilotOutcome).where(mm.PilotOutcome.id == body.outcome_id, mm.PilotOutcome.pilot_id == pl.id,
                                                     mm.PilotOutcome.org_id == p.org_id))
    if o is None:
        raise not_found("pilot_outcome", body.outcome_id)
    if body.decision == "stop" and o.status == "invalid_due_to_fidelity" and "fidelity" not in body.summary_ru.lower() \
            and "реализац" not in body.summary_ru.lower():
        raise ApiError("conclusion_misreads_fidelity",
                       "Результат не интерпретируется из-за недостаточной реализации: при решении «остановить» объясните, "
                       "что причина не в доказанной неэффективности (упомяните реализацию).", 422)
    evidence = _valid_evidence_ids(session, pl, body.evidence_ids, o.id)
    c = mm.PilotConclusion(org_id=p.org_id, pilot_id=pl.id, outcome_id=o.id, decision=body.decision,
                           summary_ru=ivs.clean_text(body.summary_ru, 4000), summary_kz=ivs.clean_text(body.summary_kz, 4000),
                           lessons_ru=ivs.clean_text(body.lessons_ru, 4000),
                           open_questions=[ivs.clean_text(q, 500) for q in body.open_questions if ivs.clean_text(q, 500)],
                           evidence_ids=evidence, created_by=p.user_id)
    session.add(c)
    session.flush()
    if body.create_next_decision_version:
        d = _next_decision(session, p, pl, o, c, ivs.clean_text(body.next_action_ru, 4000))
        c.next_decision_id = d.id
    if body.propose_evidence_update:
        res = o.result or {}
        session.add(mm.InterventionEvidenceEntry(
            org_id=p.org_id, intervention_id=pl.intervention_id, intervention_version_id=pl.intervention_version_id, pilot_id=pl.id,
            conclusion_id=c.id, outcome_id=o.id, outcome_status=o.status, causal_level=o.causal_level, fidelity_class=o.fidelity_class,
            design=pl.design, review_status="proposed",
            summary={"primary": res.get("primary"), "n_matched": res.get("n_matched"), "attrition": res.get("attrition"),
                     "topic_id": pl.topic_id, "objective_id": pl.objective_id, "decision": c.decision,
                     "dataset_id": pl.dataset_id, "is_synthetic": pl.is_synthetic}))
    audit(session, p.org_id, p.user_id, "pilot.conclusion", "pilot", pl.id, conclusion_id=c.id, decision=c.decision)
    session.commit()
    return conclusion_payload(session, c)


def conclusion_payload(session: Session, c: mm.PilotConclusion) -> dict:
    o = session.get(mm.PilotOutcome, c.outcome_id)
    e = session.scalar(select(mm.InterventionEvidenceEntry).where(mm.InterventionEvidenceEntry.conclusion_id == c.id))
    users = ivs._users(session, [c.created_by])
    return {"id": c.id, "pilot_id": c.pilot_id, "outcome_id": c.outcome_id, "outcome_status": o.status, "decision": c.decision,
            "summary_ru": c.summary_ru, "summary_kz": c.summary_kz, "lessons_ru": c.lessons_ru, "open_questions": c.open_questions,
            "evidence_ids": c.evidence_ids, "next_decision_id": c.next_decision_id,
            "evidence_entry": ({"id": e.id, "review_status": e.review_status, "outcome_status": e.outcome_status,
                                "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None} if e else None),
            "created_at": c.created_at.isoformat(), "created_by": users.get(c.created_by)}


def list_conclusions(session: Session, p: Principal, pilot_id: str) -> list[dict]:
    pl = get_pilot(session, p.org_id, pilot_id)
    rows = session.scalars(select(mm.PilotConclusion).where(mm.PilotConclusion.pilot_id == pl.id)
                           .order_by(mm.PilotConclusion.created_at.desc()))
    return [conclusion_payload(session, c) for c in rows]


def review_evidence(session: Session, p: Principal, entry_id: str, body: S.EvidenceReview) -> dict:
    """Human approval gate: only accepted entries enter the intervention evidence summary and suggestions."""
    p.require("approver")
    e = session.scalar(select(mm.InterventionEvidenceEntry).where(mm.InterventionEvidenceEntry.id == entry_id,
                                                                  mm.InterventionEvidenceEntry.org_id == p.org_id))
    if e is None:
        raise not_found("evidence_entry", entry_id)
    if e.review_status != "proposed":
        raise ApiError("invalid_state", "Запись уже рассмотрена", 409, {"review_status": e.review_status})
    if body.accept and e.outcome_status in ("invalid_due_to_fidelity", "invalid_due_to_comparability", "needs_more_data") \
            and not body.note.strip():
        raise ApiError("validation_error", "Для принятия неинтерпретируемого результата нужна пояснительная заметка", 422)
    e.review_status = "accepted" if body.accept else "rejected"
    e.reviewed_by, e.reviewed_at = p.user_id, utcnow()
    e.review_note = ivs.clean_text(body.note, 1000) or None
    audit(session, p.org_id, p.user_id, "intervention.evidence_review", "intervention", e.intervention_id, entry_id=e.id,
          accepted=body.accept)
    session.commit()
    iv = session.get(mm.Intervention, e.intervention_id)
    return ivs.evidence_summary(session, iv)


def learning_summary(session: Session, p: Principal, dataset_id: str | None = None) -> dict:
    q = select(mm.Pilot).where(mm.Pilot.org_id == p.org_id)
    if dataset_id:
        an.get_dataset(session, p.org_id, dataset_id)
        q = q.where(mm.Pilot.dataset_id == dataset_id)
    pilots = {pl.id: pl for pl in session.scalars(q)}
    conclusions = list(session.scalars(select(mm.PilotConclusion).where(mm.PilotConclusion.org_id == p.org_id,
                                                                        mm.PilotConclusion.pilot_id.in_(list(pilots)))
                                       .order_by(mm.PilotConclusion.created_at.desc())))
    entries = list(session.scalars(select(mm.InterventionEvidenceEntry).where(mm.InterventionEvidenceEntry.org_id == p.org_id,
                                                                              mm.InterventionEvidenceEntry.pilot_id.in_(list(pilots)))))
    by_iv: dict[str, dict] = {}
    for e in entries:
        iv = session.get(mm.Intervention, e.intervention_id)
        row = by_iv.setdefault(iv.id, {"intervention_id": iv.id, "code": iv.code, "accepted": {}, "proposed": 0, "rejected": 0})
        if e.review_status == "accepted":
            row["accepted"][e.outcome_status] = row["accepted"].get(e.outcome_status, 0) + 1
        elif e.review_status == "proposed":
            row["proposed"] += 1
        else:
            row["rejected"] += 1
    for row in by_iv.values():
        row["summary"] = ivs.evidence_summary(session, session.get(mm.Intervention, row["intervention_id"]))["repeated_positive_signal"]
    return {
        "interventions": sorted(by_iv.values(), key=lambda r: r["code"]),
        "lessons": [{"pilot_code": pilots[c.pilot_id].code, "conclusion_id": c.id, "decision": c.decision, "summary_ru": c.summary_ru,
                     "lessons_ru": c.lessons_ru, "outcome_status": session.get(mm.PilotOutcome, c.outcome_id).status,
                     "created_at": c.created_at.isoformat()} for c in conclusions],
        "open_questions": [{"pilot_code": pilots[c.pilot_id].code, "question": q} for c in conclusions for q in c.open_questions],
        "pending_evidence_reviews": [{"entry_id": e.id, "pilot_code": pilots[e.pilot_id].code,
                                      "intervention_code": session.get(mm.Intervention, e.intervention_id).code,
                                      "outcome_status": e.outcome_status, "fidelity_class": e.fidelity_class}
                                     for e in entries if e.review_status == "proposed"],
        "note_ru": "Организационное обучение фиксируется людьми: система не меняет рекомендации без принятых человеком записей.",
        "note_kz": "Ұйымдық оқу адамдармен тіркеледі: жүйе адам қабылдаған жазбаларсыз ұсыныстарды өзгертпейді.",
    }


_ = forbidden
