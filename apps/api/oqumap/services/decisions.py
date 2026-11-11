"""Decision cards: create (draft), approve (new version, history kept), follow-up (observed dynamics)."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import scoring
from ..analytics.comparison import compare_arms
from ..analytics.paired import paired_change
from ..db import new_id, utcnow
from ..errors import ApiError, not_found
from . import analysis as an
from .auth import Principal
from .common import audit
from .documents import source_payload
from .messages import COMPARABILITY, FOLLOW_UP, INFERENCE, render_reasons

STANDARD_LIMITS_RU = [
    "Данные наблюдательные: показатели описывают связь при указанных условиях и не доказывают причинного влияния.",
    "Распределение часов — результат планирования приоритетов при ограничениях, а не прогноз роста баллов.",
]


class DecisionCreate(BaseModel):
    dataset_id: str
    topic_id: str | None = None
    filters: an.Filters = Field(default_factory=an.Filters)
    target_group: str
    problem: str
    hypothesis: str
    action: str
    responsible: str
    follow_up_date: date | None = None
    follow_up_criterion: str = ""
    analysis_ids: list[str] = Field(default_factory=list)
    plan_analysis_id: str | None = None
    plan_preset: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    generation_id: str | None = None
    supersedes_id: str | None = None


def _run(session: Session, org_id: str, analysis_id: str) -> m.AnalysisRun:
    run = session.scalar(select(m.AnalysisRun).where(m.AnalysisRun.id == analysis_id, m.AnalysisRun.org_id == org_id))
    if run is None:
        raise not_found("analysis", analysis_id)
    return run


def create(session: Session, p: Principal, body: DecisionCreate) -> dict:
    p.require("methodist")
    ds = an.get_dataset(session, p.org_id, body.dataset_id)
    for fld in ("target_group", "problem", "hypothesis", "action", "responsible"):
        if not getattr(body, fld).strip():
            raise ApiError("validation_error", f"Поле {fld} не заполнено", 422, {"field": fld})
    runs = [_run(session, p.org_id, a) for a in body.analysis_ids]
    plan_run = _run(session, p.org_id, body.plan_analysis_id) if body.plan_analysis_id else None
    for r in runs + ([plan_run] if plan_run else []):
        if r.dataset_id != ds.id:
            raise ApiError("analysis_dataset_mismatch", "Анализ относится к другому набору данных", 422, {"analysis_id": r.id})
        if r.dataset_version != ds.version:
            raise ApiError("stale_analysis", "Анализ устарел: данные изменились. Пересчитайте анализ.", 409,
                           {"analysis_id": r.id, "analysis_version": r.dataset_version, "current_version": ds.version})
    sources = []
    for sid in body.source_ids:
        sources.append(source_payload(session, p.org_id, sid))  # raises 404 for missing/foreign sources

    snapshot: dict = {
        "dataset": {"id": ds.id, "name_ru": ds.name_ru, "name_kz": ds.name_kz, "version": ds.version, "is_synthetic": ds.is_synthetic},
        "filters": body.filters.model_dump(),
        "analyses": [{"analysis_id": r.id, "kind": r.kind, "dataset_version": r.dataset_version,
                      "method_version": r.method_version, "computed_at": r.created_at.isoformat()} for r in runs],
        "limitations": list(STANDARD_LIMITS_RU),
    }
    for r in runs:
        if r.kind == "topic_evidence":
            res = r.result
            snapshot["topic"] = {
                "analysis_id": r.id, **res["topic"], "status": res["status"], "summary": res["summary"],
                "objectives": [{"code": o["code"], "text_ru": o["text_ru"], "status": o["status"],
                                "mean": (o["score"] or {}).get("mean"), "n_learners": (o["score"] or {}).get("n_learners")}
                               for o in res["objectives"]],
                "misconceptions": [{k: x[k] for k in ("code", "label_ru", "n_learners", "share_of_learners", "items")}
                                   for x in res["misconceptions"][:3]],
                "items": [{"code": it["code"], "stem_ru": it["stem_ru"], "p_correct": it["p_correct"],
                           "n_answered": it["n_answered"], "n_omitted": it["n_omitted"]} for it in res["items"]],
                "exclusions": res["exclusions"], "rules": res["rules"],
            }
        elif r.kind == "comparison":
            res = r.result
            snapshot["comparison"] = {
                "analysis_id": r.id, "topic": res["topic"], "editions": res["editions"], "status": res["status"],
                "inference_level": res["inference_level"], "signal": res["signal"], "raw": res["raw"],
                "adjusted": {k: res["adjusted"][k] for k in ("a", "b", "difference", "unavailable_reason", "weights",
                                                              "weight_mode", "strata_scheme", "strata")},
                "uncertainty": res["uncertainty"], "reasons": res["reasons"],
            }
            snapshot["limitations"] += [x["message_ru"] for x in res["reasons"] if x["severity"] in ("warn", "fail")]
    if plan_run is not None:
        scen = next((s for s in plan_run.result["scenarios"] if s["preset"] == (body.plan_preset or s["preset"])), None)
        if scen is None or scen["status"] not in ("optimal", "feasible"):
            raise ApiError("plan_not_feasible", "Выбранный сценарий плана не имеет допустимого решения", 422)
        snapshot["plan"] = {"analysis_id": plan_run.id, "preset": scen["preset"], "status": scen["status"],
                            "status_message_ru": scen["status_message_ru"], "changes": scen["changes"],
                            "total_before": scen["total_before"], "total_after": scen["total_after"],
                            "validation": scen["validation"], "objective": scen["objective"],
                            "budget": plan_run.result["budget"], "is_calendar": False}
        snapshot["analyses"].append({"analysis_id": plan_run.id, "kind": "plan", "dataset_version": plan_run.dataset_version,
                                     "method_version": plan_run.method_version, "computed_at": plan_run.created_at.isoformat()})
    snapshot["sources"] = [{k: s[k] for k in ("source_id", "document_filename", "document_version", "document_sha256",
                                              "edition", "anchor", "page_physical", "page_printed", "heading", "text")}
                           for s in sources]
    if body.generation_id:
        g = session.scalar(select(m.AIGeneration).where(m.AIGeneration.id == body.generation_id, m.AIGeneration.org_id == p.org_id))
        if g is None:
            raise not_found("generation", body.generation_id)
        snapshot["ai"] = {"generation_id": g.id, "mode": g.mode, "task": g.task, "model": g.model,
                          "verification": g.verification}

    if body.supersedes_id:
        prev = session.scalar(select(m.Decision).where(m.Decision.id == body.supersedes_id, m.Decision.org_id == p.org_id))
        if prev is None:
            raise not_found("decision", body.supersedes_id)
        group, version = prev.decision_group_id, _max_version(session, prev.decision_group_id) + 1
    else:
        group, version = new_id(), 1
    d = m.Decision(org_id=p.org_id, decision_group_id=group, version=version, dataset_id=ds.id, dataset_version=ds.version,
                   filters=body.filters.model_dump(), target_group=body.target_group.strip(), topic_id=body.topic_id,
                   problem=body.problem.strip(), hypothesis=body.hypothesis.strip(), action=body.action.strip(),
                   responsible=body.responsible.strip(), follow_up_date=body.follow_up_date,
                   follow_up_criterion=body.follow_up_criterion.strip(), analysis_ids=body.analysis_ids,
                   plan_analysis_id=body.plan_analysis_id, snapshot=snapshot, status="draft", created_by=p.user_id)
    session.add(d)
    session.flush()
    audit(session, p.org_id, p.user_id, "decision.create", "decision", d.id, version=version, group=group)
    session.commit()
    return decision_payload(session, d)


def _max_version(session: Session, group: str) -> int:
    return int(session.scalar(select(func.max(m.Decision.version)).where(m.Decision.decision_group_id == group)) or 0)


def get(session: Session, org_id: str, decision_id: str) -> m.Decision:
    d = session.scalar(select(m.Decision).where(m.Decision.id == decision_id, m.Decision.org_id == org_id))
    if d is None:
        raise not_found("decision", decision_id)
    return d


def approve(session: Session, p: Principal, decision_id: str, note: str | None) -> dict:
    p.require("approver")
    d = get(session, p.org_id, decision_id)
    if d.version != _max_version(session, d.decision_group_id):
        raise ApiError("not_latest_version", "Утверждать можно только последнюю версию решения", 409)
    if d.status != "draft":
        raise ApiError("invalid_state", "Решение уже утверждено или заменено", 409, {"status": d.status})
    ds = session.get(m.Dataset, d.dataset_id)
    if ds.version != d.dataset_version:
        raise ApiError("stale_decision", "Данные изменились после подготовки решения; подготовьте новую версию", 409,
                       {"decision_version": d.dataset_version, "current_version": ds.version})
    approved = m.Decision(
        org_id=d.org_id, decision_group_id=d.decision_group_id, version=d.version + 1, dataset_id=d.dataset_id,
        dataset_version=d.dataset_version, filters=d.filters, target_group=d.target_group, topic_id=d.topic_id,
        problem=d.problem, hypothesis=d.hypothesis, action=d.action, responsible=d.responsible,
        follow_up_date=d.follow_up_date, follow_up_criterion=d.follow_up_criterion, analysis_ids=d.analysis_ids,
        plan_analysis_id=d.plan_analysis_id, snapshot=d.snapshot, status="approved", created_by=d.created_by,
        approved_by=p.user_id, approved_at=utcnow(), approval_note=(note or "").strip() or None)
    d.status = "superseded"
    session.add(approved)
    session.flush()
    audit(session, p.org_id, p.user_id, "decision.approve", "decision", approved.id, previous=d.id)
    session.commit()
    return decision_payload(session, approved)


def decision_payload(session: Session, d: m.Decision) -> dict:
    ds = session.get(m.Dataset, d.dataset_id)
    history = list(session.scalars(select(m.Decision).where(m.Decision.decision_group_id == d.decision_group_id,
                                                            m.Decision.org_id == d.org_id).order_by(m.Decision.version)))
    ups = list(session.scalars(select(m.FollowUp).where(m.FollowUp.decision_id.in_([h.id for h in history]))
                               .order_by(m.FollowUp.created_at)))
    users = {u.id: u.display_name for u in session.scalars(select(m.User).where(
        m.User.id.in_([x for h in history for x in (h.created_by, h.approved_by) if x])))}
    follow_ups = []
    for fu in ups:
        run = session.get(m.AnalysisRun, fu.analysis_id)
        follow_ups.append({"id": fu.id, "status": fu.status, "status_label_ru": FOLLOW_UP[fu.status][0],
                           "status_label_kz": FOLLOW_UP[fu.status][1], "analysis_id": fu.analysis_id,
                           "created_at": fu.created_at.isoformat(), "result": run.result if run else None,
                           "dataset_version": run.dataset_version if run else None})
    return {
        "id": d.id, "decision_group_id": d.decision_group_id, "version": d.version, "status": d.status,
        "dataset_id": d.dataset_id, "dataset_version": d.dataset_version, "current_dataset_version": ds.version,
        "is_stale": ds.version != d.dataset_version, "filters": d.filters, "target_group": d.target_group,
        "topic_id": d.topic_id, "problem": d.problem, "hypothesis": d.hypothesis, "action": d.action,
        "responsible": d.responsible, "follow_up_date": d.follow_up_date.isoformat() if d.follow_up_date else None,
        "follow_up_criterion": d.follow_up_criterion, "analysis_ids": d.analysis_ids, "plan_analysis_id": d.plan_analysis_id,
        "snapshot": d.snapshot, "created_at": d.created_at.isoformat(), "created_by": users.get(d.created_by),
        "approved_by": users.get(d.approved_by), "approved_at": d.approved_at.isoformat() if d.approved_at else None,
        "approval_note": d.approval_note, "outcome_status": d.outcome_status,
        "history": [{"id": h.id, "version": h.version, "status": h.status, "created_at": h.created_at.isoformat(),
                     "approved_at": h.approved_at.isoformat() if h.approved_at else None,
                     "approved_by": users.get(h.approved_by)} for h in history],
        "follow_ups": follow_ups,
        "is_synthetic": ds.is_synthetic,
    }


def list_decisions(session: Session, org_id: str, dataset_id: str | None) -> list[dict]:
    q = select(m.Decision).where(m.Decision.org_id == org_id)
    if dataset_id:
        q = q.where(m.Decision.dataset_id == dataset_id)
    rows = list(session.scalars(q.order_by(m.Decision.created_at.desc())))
    latest: dict[str, m.Decision] = {}
    for d in rows:
        if d.decision_group_id not in latest or d.version > latest[d.decision_group_id].version:
            latest[d.decision_group_id] = d
    return [{"id": d.id, "version": d.version, "status": d.status, "target_group": d.target_group, "problem": d.problem[:200],
             "topic_code": (d.snapshot.get("topic") or {}).get("code"), "created_at": d.created_at.isoformat(),
             "outcome_status": d.outcome_status, "dataset_id": d.dataset_id} for d in latest.values()]


# ---------------------------------------------------------------------------
# Follow-up
# ---------------------------------------------------------------------------


class FollowUpRequest(BaseModel):
    assessment_id: str | None = None  # default: latest 'followup' assessment of the dataset


def follow_up(session: Session, p: Principal, decision_id: str, req: FollowUpRequest) -> dict:
    p.require("methodist")
    d = get(session, p.org_id, decision_id)
    if not d.topic_id:
        raise ApiError("no_topic", "У решения нет темы для повторной проверки", 422)
    meta = an.load_meta(session, p.org_id, d.dataset_id)
    ds = meta.dataset
    if req.assessment_id:
        after_a = meta.assessments.get(req.assessment_id)
        if after_a is None:
            raise not_found("assessment", req.assessment_id)
    else:
        fus = an.assessments_for_stage(meta, "followup")
        if not fus:
            raise ApiError("no_follow_up_data", "В наборе нет повторной проверки. Загрузите файл повторной проверки.", 422)
        after_a = fus[-1]
    filters = an.Filters(**d.filters)
    before_as = an.assessments_for_stage(meta, filters.outcome_stage)
    topic = next(t for t in meta.topics if t.id == d.topic_id)

    def compute():
        reasons = []
        after_form = meta.forms[after_a.form_id]
        before_forms = {meta.forms[a.form_id].id for a in before_as}
        scales = {meta.forms[f].scale_id for f in before_forms} | {after_form.scale_id}
        if len(scales) > 1 or meta.scales[after_form.scale_id].linking_method == "none":
            reasons.append({"code": "forms_not_linked", "severity": "fail",
                            "params": {"forms": sorted({meta.forms[f].code for f in before_forms} | {after_form.code}),
                                       "scales": sorted(meta.scales[s].code for s in scales)}})
            common = set()
        else:
            common = set(meta.form_items[after_form.id])
            for f in before_forms:
                common &= set(meta.form_items[f])
            reasons.append({"code": "common_items_only", "severity": "info", "params": {"n_common_items": len(common)}})
        group_filters = filters.model_copy(update={"cohort_ids": []})
        links = an.effective_links(meta, filters.mapping_status)

        def group_scores(assessments, edition_ids):
            f = group_filters.model_copy(update={"edition_ids": edition_ids})
            resp = an.apply_filters(an.load_responses(session, meta, [a.id for a in assessments]), meta, f, topic.id)
            resp = scoring.select_attempts(resp, f.attempt_rule)
            return an.learner_scores_for(meta, resp, topic.id, links, common, f)

        base, has_base = an.baseline_scores(meta, session, group_filters)

        def dynamics(edition_ids):
            before = group_scores(before_as, edition_ids).assign(arm="before")
            after = group_scores([after_a], edition_ids).assign(arm="after")
            learners = pd.concat([before, after]).rename(columns={"score": "outcome"})
            learners = learners.merge(base.rename(columns={"score": "baseline"}), on="learner_id", how="left")
            res = compare_arms(learners, "before", "after", "pre_three_level", "pooled", [], adjustment_possible=has_base)
            res["reasons"] = [r for r in res["reasons"] if not r["code"].startswith("edition_confounded")]
            return res

        target_eds = filters.edition_ids
        target = dynamics(target_eds)
        comparison_group = None
        if target_eds:
            others = [e for e in meta.editions if e not in target_eds and any(v == e for v in meta.cohort_edition.values())]
            if others:
                comparison_group = dynamics(others)
        diff = target["adjusted"]["difference"] if target["adjusted"]["difference"] is not None else None
        ci = target["uncertainty"]["adjusted_difference_ci"]
        # paired design when the same learners (stable IDs) were measured before and after on common items
        paired = paired_change(group_scores(before_as, target_eds), group_scores([after_a], target_eds)) if common else \
            {"available": False, "reason": "forms_not_linked", "n_pairs": 0}
        design = "paired" if paired["available"] else "cohort"
        if design == "paired":
            diff, ci = paired["mean_change"], paired["ci"]
        if any(r["severity"] == "fail" for r in reasons) or diff is None or ci is None:
            status = "needs_more_data"
        elif ci["low"] > 0:
            status = "positive_signal"
        elif ci["high"] < 0:
            status = "needs_revision"
        else:
            status = "not_confirmed"
        did = None
        if comparison_group and comparison_group["adjusted"]["difference"] is not None and diff is not None:
            did = diff - comparison_group["adjusted"]["difference"]
        return {
            "decision_id": d.id, "topic": {"topic_id": topic.id, "code": topic.code, "title_ru": topic.title_ru},
            "before_assessments": [a.code for a in before_as], "after_assessment": after_a.code,
            "comparability": render_reasons(reasons), "status": status, "design": design, "paired": paired,
            "status_label_ru": FOLLOW_UP[status][0], "status_label_kz": FOLLOW_UP[status][1],
            "target": _dyn_summary(target), "comparison_group": _dyn_summary(comparison_group) if comparison_group else None,
            "difference_in_changes": did,
            "interpretation_level": "observed_dynamics",
            "note_ru": (("Те же ученики (стабильные ID) до и после на общих заданиях одной шкалы: изменение внутри ученика, "
                         "интервал — бутстрэп по классам. " if design == "paired" else
                         "Сравниваются когорты на общих заданиях одной шкалы со стандартизацией по входному уровню "
                         "(общих учеников с теми же ID нет). ")
                        + "Это наблюдаемая динамика, а не оценка воздействия решения: без протокола с контрольной "
                        "группой причинный процент улучшения не выводится."),
            "criterion": d.follow_up_criterion,
        }

    res = an.persist_or_reuse(session, p.org_id, ds, "follow_up", filters.model_dump(),
                              {"decision_id": d.id, "after_assessment_id": after_a.id}, an.METHOD_VERSION, compute, p.user_id)
    run_id = res["context"]["analysis_id"]
    if session.scalar(select(m.FollowUp).where(m.FollowUp.analysis_id == run_id, m.FollowUp.decision_id == d.id)) is None:
        session.add(m.FollowUp(org_id=p.org_id, decision_id=d.id, analysis_id=run_id, status=res["result"]["status"],
                               created_by=p.user_id))
        d.outcome_status = res["result"]["status"]
        audit(session, p.org_id, p.user_id, "decision.follow_up", "decision", d.id, analysis_id=run_id,
              status=res["result"]["status"])
        session.commit()
    return {**res, "decision": decision_payload(session, d)}


def _dyn_summary(res: dict) -> dict:
    return {
        "before": {"raw": res["raw"]["a"]["mean"], "adjusted": res["adjusted"]["a"], "n_learners": res["raw"]["a"]["n_learners"],
                   "n_classes": res["raw"]["a"]["n_classes"]},
        "after": {"raw": res["raw"]["b"]["mean"], "adjusted": res["adjusted"]["b"], "n_learners": res["raw"]["b"]["n_learners"],
                  "n_classes": res["raw"]["b"]["n_classes"]},
        "raw_change": res["raw"]["difference"], "adjusted_change": res["adjusted"]["difference"],
        "ci": res["uncertainty"]["adjusted_difference_ci"], "ci_unavailable_reason": res["uncertainty"]["unavailable_reason"],
        "cluster_unit": res["uncertainty"]["cluster_unit"], "reasons": render_reasons(res["reasons"]),
        "status": res["status"], "weights": res["adjusted"]["weights"],
    }


_ = (COMPARABILITY, INFERENCE)
