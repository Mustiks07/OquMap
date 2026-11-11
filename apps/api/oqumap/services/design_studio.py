"""Experiment Design Studio service: resolves cluster sizes from the dataset (optional) and renders reasons."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import design_studio as eds
from ..errors import ApiError, not_found
from ..schemas import interventions as S
from .common import get_dataset
from .measurement_messages import render
from .pilots import MIN_CLUSTERS_RANDOMIZED, MIN_ITS_PRE_POINTS


def _clusters_from_dataset(session: Session, org_id: str, body: S.DesignStudioRequest) -> tuple[list[int], str]:
    ds = get_dataset(session, org_id, body.dataset_id)
    cohorts = list(session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == ds.id, m.Cohort.org_id == org_id,
                                                          m.Cohort.id.in_(body.cohort_ids))))
    if len(cohorts) != len(set(body.cohort_ids)):
        raise not_found("cohort", next(c for c in body.cohort_ids if c not in {x.id for x in cohorts}))
    sizes = {c.id: session.query(m.Learner).filter(m.Learner.cohort_id == c.id).count() for c in cohorts}
    schools = {c.school_id for c in cohorts}
    if body.assignment_unit == "school":
        per_school: dict[str, int] = {}
        for c in cohorts:
            per_school[c.school_id] = per_school.get(c.school_id, 0) + sizes[c.id]
        return sorted(per_school.values()), "low"
    # class-level assignment inside the same schools → comparison classes may share teachers/materials
    return sorted(sizes.values()), "high" if len(schools) < len(cohorts) else "moderate"


def evaluate(session: Session, org_id: str, body: S.DesignStudioRequest) -> dict:
    if body.icc_low > body.icc_high or body.effect_low > body.effect_high:
        raise ApiError("validation_error", "Нижняя граница диапазона больше верхней", 422)
    if body.dataset_id:
        sizes, contamination = _clusters_from_dataset(session, org_id, body)
    else:
        if not body.cluster_sizes:
            raise ApiError("validation_error", "Укажите размеры кластеров или набор данных и классы", 422)
        sizes, contamination = list(body.cluster_sizes), "high" if body.classes_share_schools else "moderate"
    res = eds.evaluate(cluster_sizes=sizes, icc_low=body.icc_low, icc_high=body.icc_high, baseline_r=body.baseline_r,
                       attrition=body.attrition, effect_low=body.effect_low, effect_high=body.effect_high, mde_target=body.mde_target,
                       comparison_available=body.comparison_available, n_pre_measurements=body.n_pre_measurements,
                       n_post_measurements=body.n_post_measurements, calendar_weeks=body.calendar_weeks,
                       intervention_weeks=body.intervention_weeks, contamination_risk=contamination, alpha=body.alpha,
                       target_power=body.target_power)
    params = {"min": eds.MIN_CLUSTERS_PER_ARM, "intervention_weeks": body.intervention_weeks, "calendar_weeks": body.calendar_weeks,
              "n": body.n_pre_measurements}
    for d in res["designs"]:
        p = {**params, "design": d["design"]}
        if d["design"] == "cluster_randomized":
            p["min"] = MIN_CLUSTERS_RANDOMIZED
        if d["design"] == "interrupted_time_series":
            p["min"] = MIN_ITS_PRE_POINTS
        if d["design"] == "stepped_wedge":
            p["min"] = eds.MIN_SW_CLUSTERS
        d["messages"] = [render(code, p, "fail" if code in ("calendar_insufficient", "no_comparison_group",
                                                           "too_few_clusters_randomization", "its_needs_pre_points",
                                                           "stepped_wedge_needs_clusters", "stepped_wedge_needs_periods") else "info")
                         for code in d["reasons"]]
    res["warning_messages"] = [render(w) for w in res["warnings"]]
    return res
