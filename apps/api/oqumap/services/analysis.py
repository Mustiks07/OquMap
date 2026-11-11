"""Database-backed analyses. Every result is persisted as an immutable AnalysisRun snapshot.

The same (dataset version, filters, params, method version) returns the same analysis_id, so the screen,
the assistant and the exported report quote one snapshot. A snapshot whose dataset version is older than
the dataset's current version is reported as stale (never silently mixed with new data).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import scoring
from ..analytics.comparison import STRATA_SCHEMES, WEIGHT_MODES, Reason, compare_arms
from ..config import CODE_VERSION
from ..demo.content import MISCONCEPTIONS
from ..errors import ApiError, not_found
from .common import fingerprint, get_dataset
from .messages import render_reasons

METHOD_VERSION = f"{scoring.METHOD_VERSION_SCORING}+std-v1"
BANDS = {"difficult": 0.55, "attention": 0.70}  # conventional thresholds, not mastery probabilities
MIN_LEARNERS_TOPIC = 30
MIN_CLASSES_TOPIC = 3


class Filters(BaseModel):
    """Shared analysis filters. The same object flows through overview, topic, comparison, plan, assistant
    and export (contract: docs/API.md#filters)."""

    school_ids: list[str] = Field(default_factory=list)
    cohort_ids: list[str] = Field(default_factory=list)
    edition_ids: list[str] = Field(default_factory=list)
    language: str | None = None
    outcome_stage: str = "post"
    attempt_rule: str = "first"
    omitted_policy: str = "as_incorrect"
    aggregation: str = "learner"
    mapping_status: str = "confirmed_only"  # confirmed_only | include_proposed

    def validate_values(self) -> None:
        if self.attempt_rule not in scoring.ATTEMPT_RULES:
            raise ApiError("invalid_filter", "attempt_rule", 422, {"allowed": scoring.ATTEMPT_RULES})
        if self.omitted_policy not in scoring.OMITTED_POLICIES:
            raise ApiError("invalid_filter", "omitted_policy", 422, {"allowed": scoring.OMITTED_POLICIES})
        if self.aggregation not in scoring.AGGREGATIONS:
            raise ApiError("invalid_filter", "aggregation", 422, {"allowed": scoring.AGGREGATIONS})
        if self.mapping_status not in ("confirmed_only", "include_proposed"):
            raise ApiError("invalid_filter", "mapping_status", 422)
        if self.outcome_stage not in ("pre", "post", "followup"):
            raise ApiError("invalid_filter", "outcome_stage", 422)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass
class DatasetFrame:
    dataset: m.Dataset
    topics: list[m.Topic]
    objectives: list[m.LearningObjective]
    items: dict[str, m.Item]
    links: pd.DataFrame  # item_id, objective_id, weight, status
    cohorts: dict[str, m.Cohort]
    schools: dict[str, m.School]
    editions: dict[str, m.TextbookEdition]
    cohort_edition: dict[tuple[str, str], str]  # (cohort_id, topic_id) -> edition_id
    assessments: dict[str, m.Assessment]
    forms: dict[str, m.AssessmentForm]
    scales: dict[str, m.Scale]
    form_items: dict[str, list[str]]
    exposures: list[m.MaterialExposure] = field(default_factory=list)


def load_meta(session: Session, org_id: str, dataset_id: str) -> DatasetFrame:
    ds = get_dataset(session, org_id, dataset_id)
    pv = ds.program_version_id
    topics = list(session.scalars(select(m.Topic).where(m.Topic.program_version_id == pv).order_by(m.Topic.order_index)))
    objectives = list(session.scalars(select(m.LearningObjective).where(m.LearningObjective.program_version_id == pv)
                                      .order_by(m.LearningObjective.code)))
    items = {i.id: i for i in session.scalars(select(m.Item).where(m.Item.program_version_id == pv))}
    link_rows = session.execute(select(m.ItemObjective.item_id, m.ItemObjective.objective_id, m.ItemObjective.weight,
                                       m.ItemObjective.status, m.ItemObjective.origin, m.ItemObjective.id)
                                .where(m.ItemObjective.item_id.in_(list(items)), m.ItemObjective.org_id == org_id)).all()
    links = pd.DataFrame(link_rows, columns=["item_id", "objective_id", "weight", "status", "origin", "link_id"])
    cohorts = {c.id: c for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == ds.id))}
    schools = {s.id: s for s in session.scalars(select(m.School).where(m.School.dataset_id == ds.id))}
    editions = {e.id: e for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == org_id))}
    exposures = list(session.scalars(select(m.MaterialExposure).where(m.MaterialExposure.dataset_id == ds.id)))
    ce: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in exposures:
        if e.usage_level == "primary":
            ce[(e.cohort_id, e.topic_id)].add(e.edition_id)
    cohort_edition = {k: next(iter(v)) if len(v) == 1 else "__mixed__" for k, v in ce.items()}
    assessments = {a.id: a for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == ds.id))}
    forms = {f.id: f for f in session.scalars(select(m.AssessmentForm).where(m.AssessmentForm.program_version_id == pv))}
    scales = {s.id: s for s in session.scalars(select(m.Scale).where((m.Scale.org_id == org_id) | m.Scale.org_id.is_(None)))}
    form_items: dict[str, list[str]] = defaultdict(list)
    for fi in session.scalars(select(m.FormItem).where(m.FormItem.form_id.in_(list(forms))).order_by(m.FormItem.position)):
        form_items[fi.form_id].append(fi.item_id)
    return DatasetFrame(ds, topics, objectives, items, links, cohorts, schools, editions, cohort_edition, assessments,
                        forms, scales, form_items, exposures)


def load_responses(session: Session, meta: DatasetFrame, assessment_ids: list[str]) -> pd.DataFrame:
    cols = ["learner_id", "cohort_id", "school_id", "teacher_id", "assessment_id", "item_id", "attempt", "status",
            "score", "response_value", "max_points"]
    if not assessment_ids:
        return pd.DataFrame(columns=cols)
    q = (select(m.Response.learner_id, m.Learner.cohort_id, m.Response.assessment_id, m.Response.item_id,
                m.Response.attempt, m.Response.status, m.Response.score, m.Response.response_value)
         .join(m.Learner, m.Learner.id == m.Response.learner_id)
         .where(m.Response.dataset_id == meta.dataset.id, m.Response.org_id == meta.dataset.org_id,
                m.Response.assessment_id.in_(assessment_ids)))
    df = pd.DataFrame(session.execute(q).all(), columns=["learner_id", "cohort_id", "assessment_id", "item_id", "attempt",
                                                         "status", "score", "response_value"])
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["school_id"] = df["cohort_id"].map(lambda c: meta.cohorts[c].school_id)
    df["teacher_id"] = df["cohort_id"].map(lambda c: meta.cohorts[c].teacher_id or f"none:{c}")
    df["max_points"] = df["item_id"].map(lambda i: meta.items[i].max_points)
    df["score"] = df["score"].astype(float)
    return df[cols]


def apply_filters(df: pd.DataFrame, meta: DatasetFrame, f: Filters, topic_id: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    keep = pd.Series(True, index=df.index)
    if f.school_ids:
        keep &= df["school_id"].isin(f.school_ids)
    if f.cohort_ids:
        keep &= df["cohort_id"].isin(f.cohort_ids)
    if f.language:
        keep &= df["cohort_id"].map(lambda c: meta.cohorts[c].language == f.language)
    if f.edition_ids:
        def ed_ok(c):
            if topic_id:
                return meta.cohort_edition.get((c, topic_id)) in f.edition_ids
            return any(meta.cohort_edition.get((c, t.id)) in f.edition_ids for t in meta.topics)
        keep &= df["cohort_id"].map(ed_ok)
    return df[keep]


def assessments_for_stage(meta: DatasetFrame, stage: str) -> list[m.Assessment]:
    return sorted([a for a in meta.assessments.values() if a.stage == stage], key=lambda a: a.code)


def effective_links(meta: DatasetFrame, mapping_status: str) -> pd.DataFrame:
    if meta.links.empty:
        return meta.links
    allowed = {"confirmed"} if mapping_status == "confirmed_only" else {"confirmed", "proposed"}
    return meta.links[meta.links["status"].isin(allowed)]


def absent_counts(session: Session, meta: DatasetFrame, assessment_ids: list[str], f: Filters) -> dict:
    rows = session.execute(select(m.Sitting.learner_id, m.Learner.cohort_id, m.Sitting.status)
                           .join(m.Learner, m.Learner.id == m.Sitting.learner_id)
                           .where(m.Sitting.dataset_id == meta.dataset.id, m.Sitting.assessment_id.in_(assessment_ids))).all()
    df = pd.DataFrame(rows, columns=["learner_id", "cohort_id", "status"])
    if df.empty:
        return {"present": 0, "absent": 0}
    df["school_id"] = df["cohort_id"].map(lambda c: meta.cohorts[c].school_id)
    df = apply_filters(df, meta, f)
    return {"present": int((df["status"] == "present").sum()), "absent": int((df["status"] == "absent").sum())}


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


def _context(run: m.AnalysisRun, ds: m.Dataset) -> dict:
    return {
        "analysis_id": run.id,
        "dataset_id": ds.id,
        "dataset_version": run.dataset_version,
        "current_dataset_version": ds.version,
        "is_stale": run.dataset_version != ds.version,
        "is_synthetic": ds.is_synthetic,
        "filters": run.filters,
        "method_version": run.method_version,
        "code_version": run.code_version,
        "computed_at": run.created_at.isoformat(),
        "kind": run.kind,
    }


def persist_or_reuse(session: Session, org_id: str, ds: m.Dataset, kind: str, filters: dict, params: dict,
                     method_version: str, compute, user_id: str | None) -> dict:
    from .mappings import mapping_hash

    fp = fingerprint(ds.id, ds.version, kind, filters, params, method_version, CODE_VERSION, mapping_hash(session, org_id))
    run = session.scalar(select(m.AnalysisRun).where(m.AnalysisRun.org_id == org_id, m.AnalysisRun.input_fingerprint == fp))
    if run is None:
        result = compute()
        run = m.AnalysisRun(org_id=org_id, dataset_id=ds.id, dataset_version=ds.version, kind=kind, filters=filters,
                            params=params, method_version=method_version, code_version=CODE_VERSION,
                            input_fingerprint=fp, result=_clean(result), created_by=user_id)
        session.add(run)
        session.commit()
    return {"context": _context(run, ds), "result": run.result}


def get_run(session: Session, org_id: str, analysis_id: str) -> dict:
    run = session.scalar(select(m.AnalysisRun).where(m.AnalysisRun.id == analysis_id, m.AnalysisRun.org_id == org_id))
    if run is None:
        raise not_found("analysis", analysis_id)
    ds = session.get(m.Dataset, run.dataset_id)
    return {"context": _context(run, ds), "result": run.result, "params": run.params}


def _clean(obj):
    """Recursively replace NaN/Infinity with None and numpy scalars with Python types."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return scoring.finite_or_none(float(obj))
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _band(score: float | None) -> str | None:
    if score is None:
        return None
    if score < BANDS["difficult"]:
        return "difficult"
    if score < BANDS["attention"]:
        return "attention"
    return "stable"


def _topic_unit_map(meta: DatasetFrame) -> dict[str, str]:
    return {o.id: o.topic_id for o in meta.objectives}


def overview(session: Session, org_id: str, dataset_id: str, f: Filters, user_id: str | None = None) -> dict:
    f.validate_values()
    meta = load_meta(session, org_id, dataset_id)

    def compute():
        outcome = assessments_for_stage(meta, f.outcome_stage)
        a_ids = [a.id for a in outcome]
        resp = apply_filters(load_responses(session, meta, a_ids), meta, f)
        resp = scoring.select_attempts(resp, f.attempt_rule)
        unit_map = _topic_unit_map(meta)
        confirmed = effective_links(meta, "confirmed_only")
        proposed_any = effective_links(meta, "include_proposed")
        links = effective_links(meta, f.mapping_status)
        items_on_forms = {i for a in outcome for i in meta.form_items[a.form_id]}
        topics_out = []
        heat = []
        cohorts_in = sorted(set(resp["cohort_id"]), key=lambda c: meta.cohorts[c].code) if not resp.empty else []
        for t in meta.topics:
            objs = [o for o in meta.objectives if o.topic_id == t.id]
            w = scoring.item_unit_weights(links, unit_map, t.id)
            w = w[w["item_id"].isin(items_on_forms)]
            w_conf = scoring.item_unit_weights(confirmed, unit_map, t.id)
            w_conf = w_conf[w_conf["item_id"].isin(items_on_forms)]
            w_prop = scoring.item_unit_weights(proposed_any, unit_map, t.id)
            w_prop = w_prop[w_prop["item_id"].isin(items_on_forms)]
            measured_objs = set()
            for o in objs:
                lk = links[(links["objective_id"] == o.id) & links["item_id"].isin(items_on_forms)]
                if not lk.empty:
                    measured_objs.add(o.id)
            scores = scoring.learner_unit_scores(resp, w, f.omitted_policy)
            summ = scoring.summarize_scores(scores, f.aggregation)
            if w_prop.empty:
                status, reason = "not_measured", "no_items_on_forms"
            elif w_conf.empty and f.mapping_status == "confirmed_only":
                status, reason = "unverified_mapping", "only_proposed_links"
            elif summ.n_learners < MIN_LEARNERS_TOPIC or summ.n_classes < MIN_CLASSES_TOPIC:
                status, reason = "insufficient_data", "small_sample"
            else:
                status, reason = (_band(summ.mean) or "no_data"), None
            topics_out.append({
                "topic_id": t.id, "code": t.code, "title_ru": t.title_ru, "title_kz": t.title_kz,
                "status": status, "status_reason": reason,
                "score": summ.as_dict() if status not in ("not_measured", "unverified_mapping") else None,
                "band": _band(summ.mean) if status not in ("not_measured", "unverified_mapping") else None,
                "n_items": int(len(w)), "n_items_proposed_only": int(len(set(w_prop["item_id"]) - set(w_conf["item_id"]))),
                "objectives_total": len(objs), "objectives_measured": len(measured_objs),
                "coverage": (len(measured_objs) / len(objs)) if objs else None,
                "deficit": (1 - summ.mean) if (summ.mean is not None and status not in ("not_measured", "unverified_mapping")) else None,
            })
            if not scores.empty and status not in ("not_measured", "unverified_mapping"):
                cm = scores.groupby("cohort_id")["score"].agg(["mean", "size"])
                for c in cohorts_in:
                    if c in cm.index:
                        heat.append({"topic_id": t.id, "cohort_id": c, "mean": float(cm.loc[c, "mean"]),
                                     "n": int(cm.loc[c, "size"])})
        measured = [t for t in topics_out if t["deficit"] is not None and t["status"] != "insufficient_data"]
        priorities = sorted(measured, key=lambda t: -t["deficit"])[:3]
        abs_ = absent_counts(session, meta, a_ids, f)
        return {
            "outcome_assessments": [{"id": a.id, "code": a.code, "form": meta.forms[a.form_id].code,
                                     "scale": meta.scales[meta.forms[a.form_id].scale_id].code} for a in outcome],
            "topics": topics_out,
            "priorities": [{"topic_id": t["topic_id"], "code": t["code"], "deficit": t["deficit"],
                            "score": t["score"]["mean"]} for t in priorities],
            "coverage_gaps": [{"topic_id": t["topic_id"], "code": t["code"], "status": t["status"]}
                              for t in topics_out if t["status"] in ("not_measured", "unverified_mapping")],
            "heatmap": {"cohorts": [{"cohort_id": c, "code": meta.cohorts[c].code,
                                     "school_code": meta.schools[meta.cohorts[c].school_id].code,
                                     "edition_code": _cohort_edition_code(meta, c)} for c in cohorts_in],
                        "cells": heat},
            "counts": {**scoring.counts(resp), "n_responses": int(len(resp)), "absent_sittings": abs_["absent"],
                       "omitted_responses": int((resp["status"] == "omitted").sum()) if not resp.empty else 0},
            "bands": BANDS,
            "rules": {"attempt_rule": f.attempt_rule, "omitted_policy": f.omitted_policy, "aggregation": f.aggregation,
                      "mapping_status": f.mapping_status},
        }

    return persist_or_reuse(session, org_id, meta.dataset, "overview", f.model_dump(), {}, METHOD_VERSION, compute, user_id)


def _cohort_edition_code(meta: DatasetFrame, cohort_id: str) -> str | None:
    eds = {meta.cohort_edition.get((cohort_id, t.id)) for t in meta.topics} - {None}
    if len(eds) == 1:
        e = next(iter(eds))
        return meta.editions[e].code if e in meta.editions else "mixed"
    return "mixed" if eds else None


# ---------------------------------------------------------------------------
# Topic evidence
# ---------------------------------------------------------------------------


def topic_evidence(session: Session, org_id: str, dataset_id: str, topic_id: str, f: Filters,
                   user_id: str | None = None) -> dict:
    f.validate_values()
    meta = load_meta(session, org_id, dataset_id)
    topic = next((t for t in meta.topics if t.id == topic_id), None)
    if topic is None:
        raise not_found("topic", topic_id)

    def compute():
        outcome = assessments_for_stage(meta, f.outcome_stage)
        a_ids = [a.id for a in outcome]
        raw = apply_filters(load_responses(session, meta, a_ids), meta, f, topic.id)
        resp = scoring.select_attempts(raw, f.attempt_rule)
        unit_map = _topic_unit_map(meta)
        obj_map = {o.id: o.id for o in meta.objectives}
        links = effective_links(meta, f.mapping_status)
        items_on_forms = {i for a in outcome for i in meta.form_items[a.form_id]}
        w = scoring.item_unit_weights(links, unit_map, topic.id)
        w = w[w["item_id"].isin(items_on_forms)]
        scores = scoring.learner_unit_scores(resp, w, f.omitted_policy)
        summ = scoring.summarize_scores(scores, f.aggregation)

        objectives = []
        for o in [o for o in meta.objectives if o.topic_id == topic.id]:
            all_links = meta.links[(meta.links["objective_id"] == o.id) & meta.links["item_id"].isin(items_on_forms)]
            n_conf = int((all_links["status"] == "confirmed").sum())
            n_prop = int((all_links["status"] == "proposed").sum())
            ow = scoring.item_unit_weights(links, obj_map, o.id)
            ow = ow[ow["item_id"].isin(items_on_forms)]
            osc = scoring.summarize_scores(scoring.learner_unit_scores(resp, ow, f.omitted_policy), f.aggregation)
            if n_conf + n_prop == 0:
                st, rsn, sc = "not_measured", "no_items_on_forms", None
            elif ow.empty:
                st, rsn, sc = "unverified_mapping", "only_proposed_links", None
            else:
                st, rsn, sc = "measured", None, osc.as_dict()
            objectives.append({"objective_id": o.id, "code": o.code, "text_ru": o.text_ru, "text_kz": o.text_kz,
                               "n_items_confirmed": n_conf, "n_items_proposed": n_prop, "status": st,
                               "status_reason": rsn, "score": sc})

        istats = scoring.item_statistics(resp).set_index("item_id") if not resp.empty else pd.DataFrame()
        dcounts = scoring.distractor_counts(resp)
        items_out = []
        misconception_learners: dict[str, set] = defaultdict(set)
        misconception_items: dict[str, set] = defaultdict(set)
        answered_learners = set(resp.loc[resp["item_id"].isin(w["item_id"]) & (resp["status"] == "answered"), "learner_id"]) if not resp.empty else set()
        topic_items = sorted(w["item_id"], key=lambda i: meta.items[i].code)
        for iid in topic_items:
            it = meta.items[iid]
            st = istats.loc[iid] if (not istats.empty and iid in istats.index) else None
            dc = dcounts[dcounts["item_id"] == iid] if not dcounts.empty else pd.DataFrame()
            n_ans = int(st["n_answered"]) if st is not None else 0
            opts = []
            for opt in it.options:
                cnt = int(dc.loc[dc["response_value"] == opt["key"], "count"].sum()) if not dc.empty else 0
                opts.append({"key": opt["key"], "text": opt["text"], "correct": opt["correct"],
                             "misconception": opt["misconception"], "count": cnt,
                             "share": (cnt / n_ans) if n_ans else None})
                if opt["misconception"] and cnt and opt["misconception"] != "calc_error":
                    sel = resp[(resp["item_id"] == iid) & (resp["response_value"] == opt["key"])]["learner_id"]
                    misconception_learners[opt["misconception"]].update(sel)
                    misconception_items[opt["misconception"]].add(it.code)
            item_links = meta.links[meta.links["item_id"] == iid]
            items_out.append({
                "item_id": iid, "code": it.code, "stem_ru": it.stem_ru, "stem_kz": it.stem_kz,
                "objectives": [{"objective_id": r.objective_id, "code": next(o.code for o in meta.objectives if o.id == r.objective_id),
                                "weight": float(r.weight), "status": r.status, "link_id": r.link_id}
                               for r in item_links.itertuples()],
                "topic_weight": float(w.loc[w["item_id"] == iid, "w"].iloc[0]),
                "n_answered": n_ans, "n_omitted": int(st["n_omitted"]) if st is not None else 0,
                "p_correct": scoring.finite_or_none(st["p_correct"]) if st is not None else None,
                "omit_rate": scoring.finite_or_none(st["omit_rate"]) if st is not None else None,
                "options": opts,
            })
        n_ans_learners = len(answered_learners)
        misconceptions = []
        for code, learners in sorted(misconception_learners.items(), key=lambda kv: -len(kv[1])):
            ru, kz, check = MISCONCEPTIONS[code]
            misconceptions.append({
                "code": code, "label_ru": ru, "label_kz": kz, "diagnostic_check_ru": check,
                "n_learners": len(learners), "share_of_learners": (len(learners) / n_ans_learners) if n_ans_learners else None,
                "items": sorted(misconception_items[code]),
                "interpretation": "hypothesis",  # a chosen distractor is a signal to verify, not a diagnosis
            })

        class_rows = []
        if not scores.empty:
            for cid, g in scores.groupby("cohort_id"):
                c = meta.cohorts[cid]
                class_rows.append({"cohort_id": cid, "code": c.code, "school_code": meta.schools[c.school_id].code,
                                   "edition_code": (meta.editions[meta.cohort_edition[(cid, topic.id)]].code
                                                    if meta.cohort_edition.get((cid, topic.id)) in meta.editions else None),
                                   "n": int(len(g)), "mean": float(g["score"].mean())})
        class_rows.sort(key=lambda r: r["code"])

        prereq = _prerequisites(session, meta, topic, resp, links, items_on_forms, f)
        sources = _topic_sources(session, org_id, meta, topic)
        abs_ = absent_counts(session, meta, a_ids, f)
        repeat_learners = int(raw.loc[raw["attempt"] > 1, "learner_id"].nunique()) if not raw.empty else 0
        rejected = _rejected_import_rows(session, meta.dataset)
        if not w.empty and summ.n_learners and summ.n_learners >= MIN_LEARNERS_TOPIC and summ.n_classes >= MIN_CLASSES_TOPIC:
            status = _band(summ.mean)
        elif w.empty:
            any_links = meta.links[meta.links["item_id"].isin(items_on_forms) &
                                   meta.links["objective_id"].isin([o.id for o in meta.objectives if o.topic_id == topic.id])]
            status = "unverified_mapping" if not any_links.empty else "not_measured"
        else:
            status = "insufficient_data"
        return {
            "topic": {"topic_id": topic.id, "code": topic.code, "title_ru": topic.title_ru, "title_kz": topic.title_kz},
            "status": status,
            "summary": summ.as_dict() if not w.empty else None,
            "band": _band(summ.mean) if not w.empty else None,
            "objectives": objectives,
            "items": items_out,
            "misconceptions": misconceptions,
            "classes": class_rows,
            "prerequisites": prereq,
            "sources": sources,
            "exclusions": {
                "absent_sittings": abs_["absent"],
                "omitted_responses": int(resp.loc[resp["item_id"].isin(w["item_id"]), "status"].eq("omitted").sum()) if not resp.empty else 0,
                "learners_with_repeat_attempts": repeat_learners,
                "rejected_import_rows": rejected,
            },
            "rules": {"attempt_rule": f.attempt_rule, "omitted_policy": f.omitted_policy, "aggregation": f.aggregation,
                      "mapping_status": f.mapping_status},
            "outcome_assessments": [a.code for a in outcome],
        }

    return persist_or_reuse(session, org_id, meta.dataset, "topic_evidence", f.model_dump(), {"topic_id": topic.id},
                            METHOD_VERSION, compute, user_id)


def _rejected_import_rows(session: Session, ds: m.Dataset) -> int:
    return int(sum(b.rows_rejected for b in session.scalars(select(m.ImportBatch).where(
        m.ImportBatch.dataset_id == ds.id, m.ImportBatch.status == "committed"))))


def _prerequisites(session, meta: DatasetFrame, topic: m.Topic, resp, links, items_on_forms, f: Filters) -> list[dict]:
    obj_ids = {o.id for o in meta.objectives if o.topic_id == topic.id}
    rels = list(session.scalars(select(m.ObjectiveRelation).where(m.ObjectiveRelation.target_objective_id.in_(obj_ids))))
    out = []
    obj_by_id = {o.id: o for o in meta.objectives}
    unit_map = {o.id: o.id for o in meta.objectives}
    pre_assess = assessments_for_stage(meta, "pre")
    seen = set()
    for r in rels:
        src = obj_by_id.get(r.source_objective_id)
        if src is None or src.id in obj_ids or src.id in seen:
            continue
        seen.add(src.id)
        ow = scoring.item_unit_weights(links, unit_map, src.id)
        ow = ow[ow["item_id"].isin(items_on_forms)]
        sc = scoring.summarize_scores(scoring.learner_unit_scores(resp, ow, f.omitted_policy), f.aggregation) if not ow.empty else None
        src_topic = next(t for t in meta.topics if t.id == src.topic_id)
        out.append({"objective_id": src.id, "code": src.code, "text_ru": src.text_ru, "text_kz": src.text_kz,
                    "topic_code": src_topic.code, "target_code": obj_by_id[r.target_objective_id].code,
                    "confirmed": r.confirmed, "score": sc.as_dict() if sc else None,
                    "measured_in": "outcome" if sc else ("not_measured" if not pre_assess else "not_on_outcome_forms")})
    return out


def _topic_sources(session: Session, org_id: str, meta: DatasetFrame, topic: m.Topic) -> list[dict]:
    obj_ids = [o.id for o in meta.objectives if o.topic_id == topic.id]
    rows = session.execute(
        select(m.FragmentObjective, m.ContentFragment, m.Document)
        .join(m.ContentFragment, m.ContentFragment.id == m.FragmentObjective.fragment_id)
        .join(m.Document, m.Document.id == m.ContentFragment.document_id)
        .where(m.FragmentObjective.org_id == org_id, m.FragmentObjective.objective_id.in_(obj_ids),
               m.FragmentObjective.status != "rejected", m.ContentFragment.org_id == org_id)
    ).all()
    out = []
    obj_by_id = {o.id: o for o in meta.objectives}
    for fo, frag, doc in rows:
        ed = meta.editions.get(doc.edition_id) if doc.edition_id else None
        out.append({"link_id": fo.id, "source_id": frag.id, "objective_code": obj_by_id[fo.objective_id].code,
                    "status": fo.status, "origin": fo.origin, "role": fo.role,
                    "edition_code": ed.code if ed else None, "edition_title": ed.title if ed else doc.filename,
                    "page_physical": frag.page_physical, "page_printed": frag.page_printed, "anchor": frag.anchor,
                    "document_version": frag.document_version, "excerpt": frag.text[:280]})
    out.sort(key=lambda r: (r["status"] != "confirmed", r["edition_code"] or "", r["anchor"]))
    return out


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class ComparisonRequest(BaseModel):
    dataset_id: str
    topic_id: str
    edition_a_id: str
    edition_b_id: str
    filters: Filters = Field(default_factory=Filters)
    strata_scheme: str = "pre_three_level"
    weight_mode: str = "pooled"
    include_topic_table: bool = False


def learner_scores_for(meta: DatasetFrame, resp: pd.DataFrame, topic_id: str, links: pd.DataFrame,
                       item_filter: set[str] | None, f: Filters) -> pd.DataFrame:
    w = scoring.item_unit_weights(links, _topic_unit_map(meta), topic_id)
    if item_filter is not None:
        w = w[w["item_id"].isin(item_filter)]
    return scoring.learner_unit_scores(resp, w, f.omitted_policy)


def baseline_scores(meta: DatasetFrame, session: Session, f: Filters) -> tuple[pd.DataFrame, bool]:
    pre = assessments_for_stage(meta, "pre")
    if not pre:
        return pd.DataFrame(columns=["learner_id", "score"]), False
    resp = apply_filters(load_responses(session, meta, [a.id for a in pre]), meta, f)
    resp = scoring.select_attempts(resp, f.attempt_rule)
    if resp.empty:
        return pd.DataFrame(columns=["learner_id", "score"]), False
    # Baseline = total score share on the pre-assessment (all items equally weighted by max points).
    w = pd.DataFrame({"item_id": resp["item_id"].unique(), "w": 1.0})
    return scoring.learner_unit_scores(resp, w, f.omitted_policy)[["learner_id", "score"]], True


def comparison(session: Session, org_id: str, req: ComparisonRequest, user_id: str | None = None) -> dict:
    req.filters.validate_values()
    if req.strata_scheme not in STRATA_SCHEMES:
        raise ApiError("invalid_parameter", "Неизвестная схема страт", 422, {"allowed": list(STRATA_SCHEMES)})
    if req.weight_mode not in WEIGHT_MODES:
        raise ApiError("invalid_parameter", "Неизвестный режим весов", 422, {"allowed": list(WEIGHT_MODES)})
    if req.edition_a_id == req.edition_b_id:
        raise ApiError("invalid_parameter", "Выберите два разных издания", 422)
    meta = load_meta(session, org_id, req.dataset_id)
    topic = next((t for t in meta.topics if t.id == req.topic_id), None)
    if topic is None:
        raise not_found("topic", req.topic_id)
    for e in (req.edition_a_id, req.edition_b_id):
        if e not in meta.editions:
            raise not_found("edition", e)
    f = req.filters.model_copy(update={"edition_ids": []})  # arms are defined by the two editions

    def compute():
        res = _compare_topic(session, meta, topic, req, f)
        if req.include_topic_table:
            table = []
            for t in meta.topics:
                if t.id == topic.id:
                    r = res
                else:
                    r = _compare_topic(session, meta, t, req, f, replicates=500)
                table.append({"topic_id": t.id, "code": t.code, "status": r["status"],
                              "raw_difference": r["raw"]["difference"], "adjusted_difference": r["adjusted"]["difference"],
                              "ci": r["uncertainty"]["adjusted_difference_ci"], "signal": r["signal"]})
            res["topic_table"] = {"rows": table, "exploratory": True,
                                  "note_code": "multiple_comparisons_exploratory"}
        return res

    params = req.model_dump(exclude={"filters", "dataset_id"})
    return persist_or_reuse(session, org_id, meta.dataset, "comparison", f.model_dump(), params,
                            METHOD_VERSION, compute, user_id)


def _compare_topic(session: Session, meta: DatasetFrame, topic: m.Topic, req: ComparisonRequest, f: Filters,
                   replicates: int = 2000) -> dict:
    a_id, b_id = req.edition_a_id, req.edition_b_id
    outcome = assessments_for_stage(meta, f.outcome_stage)
    resp = apply_filters(load_responses(session, meta, [a.id for a in outcome]), meta, f)
    resp = scoring.select_attempts(resp, f.attempt_rule)
    links = effective_links(meta, f.mapping_status)
    context: list[Reason] = []

    # Arms: cohort edition for this topic
    resp = resp.copy()
    resp["arm"] = resp["cohort_id"].map(lambda c: meta.cohort_edition.get((c, topic.id)))
    mixed = sorted({meta.cohorts[c].code for c in resp.loc[resp["arm"] == "__mixed__", "cohort_id"].unique()})
    if mixed:
        context.append(Reason("mixed_exposure_excluded", "warn", {"classes": mixed}))
    resp = resp[resp["arm"].isin([a_id, b_id])]

    # Forms and scales per arm
    forms_by_arm = {arm: sorted({meta.assessments[x].form_id for x in resp.loc[resp["arm"] == arm, "assessment_id"].unique()})
                    for arm in (a_id, b_id)}
    item_filter = None
    all_forms = set(forms_by_arm[a_id]) | set(forms_by_arm[b_id])
    scales = {meta.forms[fid].scale_id for fid in all_forms}
    if len(all_forms) > 1:
        if len(scales) > 1 or any(meta.scales[s].linking_method == "none" for s in scales):
            context.append(Reason("forms_not_linked", "fail", {
                "forms": sorted(meta.forms[fid].code for fid in all_forms),
                "scales": sorted(meta.scales[s].code for s in scales)}))
        else:
            common = set.intersection(*(set(meta.form_items[fid]) for fid in all_forms))
            item_filter = common
            context.append(Reason("common_items_only", "info", {"n_common_items": len(common)}))
    # Mapping status for the topic items in use
    item_ids = set(resp["item_id"].unique())
    topic_obj = {o.id for o in meta.objectives if o.topic_id == topic.id}
    tl = meta.links[meta.links["item_id"].isin(item_ids) & meta.links["objective_id"].isin(topic_obj)]
    if not tl.empty and (tl["status"] == "confirmed").sum() == 0:
        context.append(Reason("mapping_unverified", "warn" if f.mapping_status == "include_proposed" else "fail", {}))
    # Language / grade / period
    def cohort_attr(arm, attr):
        return sorted({getattr(meta.cohorts[c], attr) for c in resp.loc[resp["arm"] == arm, "cohort_id"].unique()})
    langs = {arm: cohort_attr(arm, "language") for arm in (a_id, b_id)}
    if langs[a_id] and langs[b_id] and langs[a_id] != langs[b_id]:
        context.append(Reason("language_mismatch", "warn", {"a": langs[a_id], "b": langs[b_id]}))
    grades = {arm: cohort_attr(arm, "grade") for arm in (a_id, b_id)}
    if grades[a_id] and grades[b_id] and grades[a_id] != grades[b_id]:
        context.append(Reason("grade_mismatch", "fail", {"a": grades[a_id], "b": grades[b_id]}))
    years = {arm: cohort_attr(arm, "academic_year") for arm in (a_id, b_id)}
    if years[a_id] and years[b_id] and not set(years[a_id]) & set(years[b_id]):
        context.append(Reason("periods_do_not_overlap", "warn", {"a": years[a_id], "b": years[b_id]}))
    ed_a, ed_b = meta.editions[a_id], meta.editions[b_id]
    if ed_a.language != ed_b.language:
        context.append(Reason("edition_language_differs", "warn", {"a": ed_a.language, "b": ed_b.language}))

    outcome_scores = learner_scores_for(meta, resp, topic.id, links, item_filter, f)
    arm_of = resp.drop_duplicates("learner_id").set_index("learner_id")["arm"]
    base, has_base = baseline_scores(meta, session, f)
    learners = outcome_scores.rename(columns={"score": "outcome"})[["learner_id", "cohort_id", "school_id", "teacher_id", "outcome"]]
    learners["arm"] = learners["learner_id"].map(arm_of)
    learners = learners.merge(base.rename(columns={"score": "baseline"}), on="learner_id", how="left")
    # Learners in the arm's classes without any outcome (absent) are counted as exclusions.
    res = compare_arms(learners, a_id, b_id, req.strata_scheme, req.weight_mode, context, replicates=replicates,
                       adjustment_possible=has_base)
    res["topic"] = {"topic_id": topic.id, "code": topic.code, "title_ru": topic.title_ru, "title_kz": topic.title_kz}
    res["editions"] = {"a": {"id": a_id, "code": ed_a.code, "title": ed_a.title},
                       "b": {"id": b_id, "code": ed_b.code, "title": ed_b.title}}
    res["forms"] = {"a": [meta.forms[x].code for x in forms_by_arm[a_id]], "b": [meta.forms[x].code for x in forms_by_arm[b_id]]}
    res["reasons"] = render_reasons(res["reasons"], {a_id: ed_a.code, b_id: ed_b.code})
    return res


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------


def dataset_quality(session: Session, org_id: str, dataset_id: str) -> dict:
    meta = load_meta(session, org_id, dataset_id)
    ds = meta.dataset
    batches = list(session.scalars(select(m.ImportBatch).where(m.ImportBatch.dataset_id == ds.id).order_by(m.ImportBatch.created_at)))
    a_rows = []
    for a in sorted(meta.assessments.values(), key=lambda a: a.code):
        n_resp = session.query(m.Response).filter(m.Response.assessment_id == a.id).count()
        omitted = session.query(m.Response).filter(m.Response.assessment_id == a.id, m.Response.status == "omitted").count()
        retakes = session.query(m.Response).filter(m.Response.assessment_id == a.id, m.Response.attempt > 1).count()
        present = session.query(m.Sitting).filter(m.Sitting.assessment_id == a.id, m.Sitting.status == "present").count()
        absent = session.query(m.Sitting).filter(m.Sitting.assessment_id == a.id, m.Sitting.status == "absent").count()
        form = meta.forms[a.form_id]
        a_rows.append({"assessment_id": a.id, "code": a.code, "stage": a.stage, "form": form.code,
                       "scale": meta.scales[form.scale_id].code, "linking_method": meta.scales[form.scale_id].linking_method,
                       "administered_on": a.administered_on.isoformat() if a.administered_on else None,
                       "n_responses": n_resp, "omitted": omitted, "retake_rows": retakes, "present": present,
                       "absent": absent, "n_items": len(meta.form_items[a.form_id])})
    grades = session.query(m.GradeRecord).filter(m.GradeRecord.dataset_id == ds.id).count()
    level = ds.data_level
    capabilities = {
        "grades_only": {"possible": ["grades_overview"], "missing": ["item_level_responses", "item_objective_links",
                                                                      "baseline_assessment", "material_exposure"]},
        "item_responses": {"possible": ["topic_diagnostics", "error_analysis"],
                           "missing": ["baseline_assessment_or_exposure_for_comparison"]},
        "pre_post_with_exposure": {"possible": ["topic_diagnostics", "error_analysis", "adjusted_comparison",
                                                "hours_planning"], "missing": ["randomised_protocol_for_causal_claims"]},
    }[level]
    return {
        "dataset": dataset_summary(ds),
        "counts": {"schools": len(meta.schools), "classes": len(meta.cohorts),
                   "learners": session.query(m.Learner).filter(m.Learner.dataset_id == ds.id).count(),
                   "teachers": session.query(m.Teacher).filter(m.Teacher.dataset_id == ds.id).count(),
                   "grade_records": grades},
        "assessments": a_rows,
        "imports": [batch_summary(b) for b in batches],
        "data_level": level,
        "capabilities": capabilities,
        "editions_in_use": sorted({meta.editions[e].code for e in meta.cohort_edition.values() if e in meta.editions}),
        "versions": [{"version": v.version, "reason": v.reason, "at": v.created_at.isoformat(), "import_batch_id": v.import_batch_id}
                     for v in session.scalars(select(m.DatasetVersionEvent).where(m.DatasetVersionEvent.dataset_id == ds.id)
                                              .order_by(m.DatasetVersionEvent.version))],
        "attempt_rule_note": "first",
    }


def dataset_summary(ds: m.Dataset) -> dict:
    return {"id": ds.id, "code": ds.code, "name_ru": ds.name_ru, "name_kz": ds.name_kz,
            "description_ru": ds.description_ru, "description_kz": ds.description_kz, "is_synthetic": ds.is_synthetic,
            "scenario": ds.scenario, "data_level": ds.data_level, "version": ds.version,
            "version_updated_at": ds.version_updated_at.isoformat(), "program_version_id": ds.program_version_id,
            "manifest": ds.manifest}


def batch_summary(b: m.ImportBatch) -> dict:
    return {"id": b.id, "filename": b.filename, "kind": b.kind, "status": b.status, "file_sha256": b.file_sha256,
            "transform_version": b.transform_version, "rows_total": b.rows_total, "rows_accepted": b.rows_accepted,
            "rows_rejected": b.rows_rejected, "created_at": b.created_at.isoformat(),
            "committed_at": b.committed_at.isoformat() if b.committed_at else None,
            "resulting_dataset_version": b.resulting_dataset_version, "is_synthetic": b.is_synthetic,
            "dataset_id": b.dataset_id}
