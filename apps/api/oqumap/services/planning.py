"""Hours planning on top of a teaching plan and the current topic analysis."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import planner as pl
from ..errors import ApiError, not_found
from . import analysis as an
from .messages import PLAN_STATUS, label_constraint

PRESETS = ("balanced", "minimal_changes", "focus_problem_topics")


class TopicInput(BaseModel):
    topic_id: str | None = None
    code: str
    title: str = ""
    current_hours: int
    priority: float = 1.0
    min_hours: int | None = None
    max_hours: int | None = None
    fixed: bool = False
    elapsed_hours: int = 0
    max_change: int | None = None


class PlanSolveRequest(BaseModel):
    dataset_id: str
    plan_id: str | None = None
    filters: an.Filters = Field(default_factory=an.Filters)
    topics: list[TopicInput]
    budget: int
    change_penalty: float = 0.05
    diminishing_rate: float | None = None
    presets: list[str] = Field(default_factory=lambda: ["balanced"])
    time_limit_seconds: float = 5.0
    source_analysis_id: str | None = None


def plan_context(session: Session, org_id: str, dataset_id: str, filters: an.Filters, user_id: str | None) -> dict:
    """Current plan + suggested priorities derived from the topic analysis (editable by the methodist)."""
    ds = an.get_dataset(session, org_id, dataset_id)
    plan = session.scalar(select(m.TeachingPlan).where(m.TeachingPlan.dataset_id == ds.id, m.TeachingPlan.org_id == org_id)
                          .order_by(m.TeachingPlan.created_at.desc(), m.TeachingPlan.version.desc()))
    ov = an.overview(session, org_id, dataset_id, filters, user_id)
    by_topic = {t["topic_id"]: t for t in ov["result"]["topics"]}
    deficits = [t["deficit"] for t in by_topic.values() if t["deficit"] is not None]
    dmax = max(deficits) if deficits else 1.0
    topics = []
    if plan is not None:
        rows = list(session.scalars(select(m.PlanTopicHours).where(m.PlanTopicHours.plan_id == plan.id)))
        tmap = {t.id: t for t in session.scalars(select(m.Topic).where(m.Topic.id.in_([r.topic_id for r in rows])))}
        for r in sorted(rows, key=lambda r: tmap[r.topic_id].order_index):
            t = tmap[r.topic_id]
            ot = by_topic.get(t.id, {})
            if ot.get("deficit") is not None:
                prio, basis = round(ot["deficit"] / dmax, 3), "deficit"
            else:
                prio, basis = 0.5, "not_measured_default"
            topics.append({
                "topic_id": t.id, "code": t.code, "title_ru": t.title_ru, "title_kz": t.title_kz,
                "current_hours": r.planned_hours, "elapsed_hours": r.elapsed_hours, "min_hours": r.min_hours,
                "max_hours": r.max_hours, "actual_hours": r.actual_hours, "priority": prio, "priority_basis": basis,
                "topic_status": ot.get("status"), "score": (ot.get("score") or {}).get("mean"),
                "recommend_diagnostic": basis != "deficit",
            })
    return {
        "plan": None if plan is None else {"id": plan.id, "name": plan.name, "scope": plan.scope, "horizon": plan.horizon,
                                           "version": plan.version, "status": plan.status, "plan_group_id": plan.plan_group_id},
        "topics": topics,
        "budget": sum(t["current_hours"] for t in topics),
        "priority_rule": "priority = deficit / max(deficit) по темам с подтверждённой разметкой; неизмеренные темы — 0,5 "
                         "и рекомендация провести диагностику (не обнуляется).",
        "weights_version": "priority-weights-v1",
        "source_analysis_id": ov["context"]["analysis_id"],
        "is_calendar": False,
        "illustration_20h": {
            "budget": 20,
            "topics": [
                {"code": "R", "title": "Повторение", "current_hours": 4, "min_hours": 3, "priority": 0.2},
                {"code": "TARGET", "title": "Целевой трудный раздел", "current_hours": 8, "min_hours": 8, "max_hours": 10, "priority": 1.0},
                {"code": "CONS", "title": "Закрепление освоенного раздела", "current_hours": 4, "min_hours": 3, "priority": 0.2},
                {"code": "CHECK", "title": "Проверка и разбор", "current_hours": 4, "min_hours": 4, "priority": 0.5},
            ],
        },
    }


def solve(session: Session, org_id: str, req: PlanSolveRequest, user_id: str | None) -> dict:
    ds = an.get_dataset(session, org_id, req.dataset_id)
    for p in req.presets:
        if p not in PRESETS:
            raise ApiError("invalid_parameter", "Неизвестный сценарий", 422, {"allowed": list(PRESETS)})
    if not req.topics:
        raise ApiError("invalid_parameter", "Нет тем для планирования", 422)
    if req.time_limit_seconds <= 0 or req.time_limit_seconds > 30:
        raise ApiError("invalid_parameter", "Лимит времени 0–30 с", 422)
    if req.plan_id:
        plan = session.scalar(select(m.TeachingPlan).where(m.TeachingPlan.id == req.plan_id, m.TeachingPlan.org_id == org_id))
        if plan is None:
            raise not_found("plan", req.plan_id)
    problem = pl.PlanProblem(
        topics=[pl.TopicConstraint(topic_id=t.topic_id or f"block:{t.code}", code=t.code, title=t.title,
                                   current_hours=t.current_hours, priority=t.priority, min_hours=t.min_hours,
                                   max_hours=t.max_hours, fixed=t.fixed, elapsed_hours=t.elapsed_hours,
                                   max_change=t.max_change) for t in req.topics],
        budget=req.budget, change_penalty=req.change_penalty, diminishing_rate=req.diminishing_rate,
        time_limit_seconds=req.time_limit_seconds,
    )

    def compute():
        scenarios = []
        for name in req.presets:
            res = pl.solve(pl.preset(problem, name))
            res["preset"] = name
            res["status_message_ru"], res["status_message_kz"] = PLAN_STATUS[res["status"]]
            if res.get("conflict"):
                res["conflict"]["constraints"] = [label_constraint(c) for c in res["conflict"]["constraints"]]
            scenarios.append(res)
        return {"scenarios": scenarios, "budget": req.budget, "is_calendar": False,
                "input": {"topics": [t.model_dump() for t in req.topics], "change_penalty": req.change_penalty,
                          "diminishing_rate": req.diminishing_rate},
                "source_analysis_id": req.source_analysis_id,
                "note_ru": "План часов по темам; распределение по неделям — в «Календаре по неделям». Целевая функция распределяет "
                           "педагогический приоритет и не является прогнозом роста баллов."}

    params = req.model_dump(exclude={"filters", "dataset_id"})
    return an.persist_or_reuse(session, org_id, ds, "plan", req.filters.model_dump(), params, pl.METHOD_VERSION_PLANNER,
                               compute, user_id)
