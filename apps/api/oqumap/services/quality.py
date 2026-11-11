"""Assessment Quality Lab — database-backed service.

Each (assessment, dataset version, rules) result is persisted as an immutable ``AnalysisRun`` snapshot of kind
``assessment_quality`` (same provenance mechanism as the other analyses), so the screen and any export quote one
computation. Results contain aggregates only — never learner identifiers.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import assessment_quality as aq
from ..analytics import scoring
from ..errors import ApiError, not_found
from . import analysis as an
from .measurement_messages import render

KIND = "assessment_quality"


class QualityParams(BaseModel):
    attempt_rule: str = "first"
    omitted_policy: str = "as_incorrect"

    def validate_values(self) -> None:
        if self.attempt_rule not in scoring.ATTEMPT_RULES:
            raise ApiError("invalid_parameter", "attempt_rule", 422, {"allowed": list(scoring.ATTEMPT_RULES)})
        if self.omitted_policy not in scoring.OMITTED_POLICIES:
            raise ApiError("invalid_parameter", "omitted_policy", 422, {"allowed": list(scoring.OMITTED_POLICIES)})


def _assessment(session: Session, org_id: str, assessment_id: str, dataset_id: str | None = None) -> m.Assessment:
    q = select(m.Assessment).where(m.Assessment.id == assessment_id, m.Assessment.org_id == org_id)
    if dataset_id:
        q = q.where(m.Assessment.dataset_id == dataset_id)
    a = session.scalar(q)
    if a is None:
        raise not_found("assessment", assessment_id)
    return a


def _sittings(session: Session, meta: an.DatasetFrame, assessment: m.Assessment) -> tuple[list[str], dict]:
    rows = session.execute(select(m.Sitting.learner_id, m.Sitting.status, m.Learner.cohort_id)
                           .join(m.Learner, m.Learner.id == m.Sitting.learner_id)
                           .where(m.Sitting.assessment_id == assessment.id, m.Sitting.org_id == meta.dataset.org_id)).all()
    present = [r[0] for r in rows if r[1] == "present"]
    absent = sum(1 for r in rows if r[1] == "absent")
    cohorts = {r[2] for r in rows}
    assigned = 0
    if cohorts:
        assigned = session.query(m.Learner).filter(m.Learner.cohort_id.in_(cohorts), m.Learner.dataset_id == meta.dataset.id).count()
    return present, {"assigned": assigned, "present": len(present), "absent": absent,
                     "no_record": max(0, assigned - len(present) - absent), "cohorts": sorted(cohorts)}


def _items_meta(meta: an.DatasetFrame, item_ids: list[str]) -> dict[str, aq.ItemMeta]:
    return {i: aq.ItemMeta(i, meta.items[i].code, meta.items[i].max_points, meta.items[i].answer_key, list(meta.items[i].options or []))
            for i in item_ids}


def _learner_groups(session: Session, meta: an.DatasetFrame, learner_ids: list[str]) -> pd.DataFrame:
    if not learner_ids:
        return pd.DataFrame(columns=["learner_id", "cohort_id"])
    rows = session.execute(select(m.Learner.id, m.Learner.cohort_id).where(m.Learner.dataset_id == meta.dataset.id)).all()
    df = pd.DataFrame(rows, columns=["learner_id", "cohort_id"])
    return df[df["learner_id"].isin(set(learner_ids))]


def compute_assessment_quality(session: Session, meta: an.DatasetFrame, a: m.Assessment, params: QualityParams) -> dict:
    form = meta.forms[a.form_id]
    scale = meta.scales[form.scale_id]
    item_ids = list(meta.form_items[form.id])
    items = _items_meta(meta, item_ids)
    raw = an.load_responses(session, meta, [a.id])
    selected = scoring.select_attempts(raw, params.attempt_rule)
    present, counts = _sittings(session, meta, a)
    share, status = aq.item_matrix(selected, present, item_ids, items, params.omitted_policy)
    form_q = aq.form_quality(share, status, items, counts)
    totals = aq.learner_totals(share, items)

    links = meta.links
    obj_code = {o.id: o.code for o in meta.objectives}
    topic_of = {o.id: o.topic_id for o in meta.objectives}
    topic_code = {t.id: t.code for t in meta.topics}
    item_rows = []
    for iid in item_ids:
        row = aq.item_quality(iid, share, status, selected, items, totals)
        lk = links[links["item_id"] == iid] if not links.empty else links
        row["objectives"] = [{"objective_id": r.objective_id, "code": obj_code.get(r.objective_id), "status": r.status,
                              "weight": float(r.weight), "topic_code": topic_code.get(topic_of.get(r.objective_id))}
                             for r in lk.itertuples()] if not links.empty else []
        row["misconceptions"] = sorted({o.get("misconception") for o in meta.items[iid].options
                                        if o.get("misconception") and not o.get("correct")})
        if not any(o["status"] == "confirmed" for o in row["objectives"]):
            row["flags"].append({"code": "mapping_unconfirmed", "severity": "info", "params": {}})
        row["flags"] = [render(f["code"], f["params"], f["severity"]) for f in row["flags"]]
        row["stem_ru"] = meta.items[iid].stem_ru
        row["stem_kz"] = meta.items[iid].stem_kz
        item_rows.append(row)

    # slices by language and grade (present learners only), with small-group suppression
    groups = _learner_groups(session, meta, list(share.index))
    slices = {}
    if not groups.empty:
        tot = totals.rename("total").reset_index()
        g = groups.merge(tot, on="learner_id")
        g["language"] = g["cohort_id"].map(lambda c: meta.cohorts[c].language)
        g["grade"] = g["cohort_id"].map(lambda c: str(meta.cohorts[c].grade))
        for dim in ("language", "grade"):
            rows = []
            for val, sub in g.groupby(dim):
                vals = sub["total"].dropna()
                rows.append({"value": val, "n": int(len(vals)), "mean": float(vals.mean()) if len(vals) else None,
                             "median": float(vals.median()) if len(vals) else None,
                             "sd": float(vals.std(ddof=1)) if len(vals) > 1 else None})
            slices[dim] = aq.suppress_slices(rows)
    retake_rows = int(len(raw) - len(selected)) if not raw.empty else 0
    alpha = form_q["reliability"]["cronbach_alpha"]
    limitations = [render("quality_single_administration"), render("quality_flags_are_signals"),
                   render("quality_absent_excluded")]
    if alpha["value"] is None:
        limitations.append(render("alpha_not_available", {"reason": alpha["unavailable_reason"]}, "warn"))
    if meta.dataset.is_synthetic:
        limitations.append(render("quality_synthetic"))
    flag_counts: dict[str, int] = {}
    for r in item_rows:
        for f in r["flags"]:
            flag_counts[f["code"]] = flag_counts.get(f["code"], 0) + 1
    return {
        "assessment": {"assessment_id": a.id, "code": a.code, "stage": a.stage,
                       "administered_on": a.administered_on.isoformat() if a.administered_on else None,
                       "form_id": form.id, "form_code": form.code, "form_name": form.name, "scale_code": scale.code,
                       "linking_method": scale.linking_method, "dataset_id": meta.dataset.id},
        "rules": {"attempt_rule": params.attempt_rule, "omitted_policy": params.omitted_policy,
                  "pooling": "single_administration_only",
                  "upper_lower_rule": "corrected_total_27pct_ties_by_learner_id",
                  "item_total": "pearson_item_share_vs_rest_total"},
        "form": form_q,
        "slices": slices,
        "items": item_rows,
        "flag_counts": flag_counts,
        "n_flagged_items": sum(1 for r in item_rows if any(f["severity"] == "warn" for f in r["flags"])),
        "exclusions": {
            "absent_learners": counts["absent"],
            "assigned_without_sitting_record": counts["no_record"],
            "rows_excluded_by_attempt_rule": retake_rows,
            "learners_with_repeat_attempts": int(raw.loc[raw["attempt"] > 1, "learner_id"].nunique()) if not raw.empty else 0,
            "responses_outside_form": int((~raw["item_id"].isin(item_ids)).sum()) if not raw.empty else 0,
            "rejected_import_rows_in_dataset": int(sum(b.rows_rejected for b in session.scalars(select(m.ImportBatch).where(
                m.ImportBatch.dataset_id == meta.dataset.id, m.ImportBatch.status == "committed")))),
        },
        "thresholds": {"too_easy_p": aq.TOO_EASY_P, "too_hard_p": aq.TOO_HARD_P, "low_discrimination": aq.LOW_DISCRIMINATION,
                       "high_omission": aq.HIGH_OMISSION, "non_functional_share": aq.NON_FUNCTIONAL_SHARE,
                       "min_learners_alpha": aq.MIN_LEARNERS_ALPHA, "min_learners_item_total": aq.MIN_LEARNERS_ITEM_TOTAL,
                       "min_slice_learners": aq.MIN_SLICE_LEARNERS},
        "limitations": limitations,
    }


def _envelope(res: dict, meta: an.DatasetFrame) -> dict:
    ctx = res["context"]
    return {
        "method_version": aq.METHOD_VERSION_QUALITY,
        "dataset_id": meta.dataset.id,
        "dataset_version": ctx["dataset_version"],
        "current_dataset_version": ctx["current_dataset_version"],
        "is_stale": ctx["is_stale"],
        "is_synthetic": meta.dataset.is_synthetic,
        "generated_at": ctx["computed_at"],
        "provenance": {"analysis_id": ctx["analysis_id"], "code_version": ctx["code_version"], "kind": KIND,
                       "method_version": ctx["method_version"]},
        **res["result"],
    }


def assessment_quality(session: Session, org_id: str, assessment_id: str, params: QualityParams,
                       user_id: str | None = None, dataset_id: str | None = None) -> dict:
    params.validate_values()
    a = _assessment(session, org_id, assessment_id, dataset_id)
    meta = an.load_meta(session, org_id, a.dataset_id)
    res = an.persist_or_reuse(session, org_id, meta.dataset, KIND, params.model_dump(), {"assessment_id": a.id},
                              aq.METHOD_VERSION_QUALITY, lambda: compute_assessment_quality(session, meta, a, params), user_id)
    return _envelope(res, meta)


def _summary(full: dict) -> dict:
    f = full["form"]
    return {
        "assessment": full["assessment"], "method_version": full["method_version"], "dataset_version": full["dataset_version"],
        "generated_at": full["generated_at"], "provenance": full["provenance"], "is_synthetic": full["is_synthetic"],
        "denominators": f["denominators"], "completion_rate": f["completion_rate"], "omission_rate": f["omission_rate"],
        "mean_score": f["score_distribution"]["mean"], "cronbach_alpha": f["reliability"]["cronbach_alpha"],
        "n_items": f["denominators"]["n_items"], "n_flagged_items": full["n_flagged_items"], "flag_counts": full["flag_counts"],
    }


def list_assessments(session: Session, org_id: str, dataset_id: str | None, params: QualityParams,
                     user_id: str | None = None) -> dict:
    params.validate_values()
    q = select(m.Dataset).where(m.Dataset.org_id == org_id)
    if dataset_id:
        an.get_dataset(session, org_id, dataset_id)  # 404 for foreign / missing
        q = q.where(m.Dataset.id == dataset_id)
    rows = []
    for ds in session.scalars(q.order_by(m.Dataset.created_at)):
        for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == ds.id, m.Assessment.org_id == org_id)
                                 .order_by(m.Assessment.code)):
            rows.append(_summary(assessment_quality(session, org_id, a.id, params, user_id)) | {
                "dataset": {"id": ds.id, "code": ds.code, "name_ru": ds.name_ru, "name_kz": ds.name_kz}})
    return {"method_version": aq.METHOD_VERSION_QUALITY, "rules": params.model_dump(), "assessments": rows}


def item_items(session: Session, org_id: str, assessment_id: str, params: QualityParams, user_id: str | None,
               dataset_id: str | None = None, flag: str | None = None) -> dict:
    full = assessment_quality(session, org_id, assessment_id, params, user_id, dataset_id)
    items = full["items"]
    if flag:
        items = [r for r in items if any(f["code"] == flag for f in r["flags"])]
    return {k: full[k] for k in ("method_version", "dataset_id", "dataset_version", "generated_at", "provenance",
                                 "assessment", "rules", "thresholds", "limitations", "is_synthetic")} | {"items": items}


def item_detail(session: Session, org_id: str, item_id: str, params: QualityParams, user_id: str | None,
                dataset_id: str | None = None) -> dict:
    """Per-administration statistics of one item. Administrations are listed separately, never pooled."""
    params.validate_values()
    item = session.get(m.Item, item_id)
    pv = session.get(m.ProgramVersion, item.program_version_id) if item else None
    if item is None or pv is None or (pv.org_id is not None and pv.org_id != org_id):
        raise not_found("item", item_id)
    q = (select(m.Assessment).join(m.FormItem, m.FormItem.form_id == m.Assessment.form_id)
         .where(m.FormItem.item_id == item.id, m.Assessment.org_id == org_id))
    if dataset_id:
        an.get_dataset(session, org_id, dataset_id)
        q = q.where(m.Assessment.dataset_id == dataset_id)
    admins = []
    for a in session.scalars(q.order_by(m.Assessment.code)):
        full = assessment_quality(session, org_id, a.id, params, user_id)
        row = next((r for r in full["items"] if r["item_id"] == item.id), None)
        if row is not None:
            admins.append({"assessment": full["assessment"], "dataset_version": full["dataset_version"],
                           "provenance": full["provenance"], "generated_at": full["generated_at"], "stats": row})
    return {
        "method_version": aq.METHOD_VERSION_QUALITY,
        "item": {"item_id": item.id, "code": item.code, "version": item.version, "item_type": item.item_type,
                 "stem_ru": item.stem_ru, "stem_kz": item.stem_kz, "options": item.options, "answer_key": item.answer_key,
                 "max_points": item.max_points},
        "administrations": admins,
        "pooled": None,
        "pooled_unavailable_reason": "administrations_not_pooled",
        "limitations": [render("quality_single_administration"), render("quality_flags_are_signals")],
    }
