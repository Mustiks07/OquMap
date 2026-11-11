"""Weekly calendar service: current vs proposed calendar of topics by week, with an explanation for every move.

* Current calendar: the current teaching plan (hours per topic) filled week by week in program order with the
  organisation's default calendar (start date, number of weeks, weekly hours, holidays). It is a derived,
  reproducible baseline, not a stored timetable.
* Proposed calendar: CP-SAT (``analytics/calendar.py``) with the requested settings, optionally with hours from
  an hours-plan scenario (``plan_analysis_id``) — e.g. from the decision sandbox.
* Each topic that moves gets machine-generated reasons (hours changed, earlier topics changed, weeks became
  unavailable, weekly load changed, fixed window, waits for a prerequisite, order relaxed, solver trade-off).
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..analytics import calendar as cal
from ..errors import ApiError, not_found
from . import analysis as an
from . import planning

DEFAULT_START = date(2026, 8, 31)  # Monday of the week with 1 September 2026
DEFAULT_WEEKS = 34
DEFAULT_WEEKLY_HOURS = 4
# Conventional break weeks for the demo year (configure from the school's order): autumn, winter (2), spring.
DEFAULT_UNAVAILABLE = [8, 17, 18, 29]
MAX_WEEKS = 45

LABELS = {
    "topic_hours": ("Тема {topic_code}: нужно разместить {value} ч", "{topic_code} тақырыбы: {value} сағ орналастыру керек"),
    "weekly_load": ("Недельная нагрузка не больше заданной", "Апталық жүктеме берілгеннен аспайды"),
    "holidays": ("Недели {weeks_h} недоступны (каникулы)", "{weeks_h} апталары қолжетімсіз (демалыс)"),
    "fixed_window": ("Тема {topic_code}: только недели {from_h}–{to_h}", "{topic_code} тақырыбы: тек {from_h}–{to_h} апталар"),
    "prerequisite": ("{before} должна закончиться до начала {topic_code} (пререквизит)", "{before} {topic_code} басталғанға дейін аяқталуы керек (пререквизит)"),
    "program_order": ("{before} идёт раньше {topic_code} (порядок программы)", "{before} {topic_code} алдында (бағдарлама реті)"),
}

REASONS = {
    "hours_changed": ("часы темы изменились: {from_h} → {to_h} ч", "тақырып сағаттары өзгерді: {from_h} → {to_h} сағ"),
    "earlier_topics_hours": ("у предшествующих тем {sign}{n} ч", "алдыңғы тақырыптарда {sign}{n} сағ"),
    "new_unavailable_weeks": ("недоступны недели {weeks}", "{weeks} апталары қолжетімсіз"),
    "weeks_released": ("снова доступны недели {weeks}", "{weeks} апталары қайта қолжетімді"),
    "weekly_load_changed": ("недельная нагрузка {from_h} → {to_h} ч", "апталық жүктеме {from_h} → {to_h} сағ"),
    "fixed_window": ("закреплена за неделями {from_h}–{to_h}", "{from_h}–{to_h} апталарына бекітілген"),
    "waits_for_prerequisite": ("ждёт окончания пререквизита {before}", "{before} пререквизитінің аяқталуын күтеді"),
    "order_relaxed": ("порядок программы не обязателен — тема поставлена раньше {before}", "бағдарлама реті міндетті емес — тақырып {before} алдына қойылды"),
    "solver_tradeoff": ("перераспределение решателем при тех же ограничениях", "сол шектеулер кезінде шешуші қайта бөлді"),
    "unchanged": ("без изменений", "өзгеріссіз"),
}


class FixedWindow(BaseModel):
    topic: str
    from_week: int | None = None  # 1-based for users
    to_week: int | None = None


class CalendarRequest(BaseModel):
    dataset_id: str
    start_date: date = DEFAULT_START
    n_weeks: int = DEFAULT_WEEKS
    weekly_hours: int = DEFAULT_WEEKLY_HOURS
    week_hours: dict[int, int] = Field(default_factory=dict)  # 1-based week → hours (overrides)
    unavailable_weeks: list[int] | None = None  # 1-based; None → default holidays
    topic_hours: dict[str, int] = Field(default_factory=dict)  # code → hours override
    plan_analysis_id: str | None = None
    plan_preset: str = "balanced"
    fixed: list[FixedWindow] = Field(default_factory=list)
    keep_order: bool = True
    filters: an.Filters = Field(default_factory=an.Filters)


def _prereqs(session: Session, meta) -> list[tuple[str, str]]:
    obj_topic = {o.id: o.topic_id for o in meta.objectives}
    code = {t.id: t.code for t in meta.topics}
    rels = session.scalars(select(m.ObjectiveRelation).where(m.ObjectiveRelation.target_objective_id.in_(list(obj_topic))))
    pairs = set()
    for r in rels:
        a, b = code.get(obj_topic.get(r.source_objective_id)), code.get(obj_topic.get(r.target_objective_id))
        if a and b and a != b:
            pairs.add((a, b))
    return sorted(pairs)


def _weeks(start: date, n: int) -> list[dict]:
    return [{"index": i + 1, "start": (start + timedelta(weeks=i)).isoformat(),
             "end": (start + timedelta(weeks=i, days=4)).isoformat()} for i in range(n)]


def context(session: Session, org_id: str, dataset_id: str, filters: an.Filters, user_id: str | None) -> dict:
    pc = planning.plan_context(session, org_id, dataset_id, filters, user_id)
    if not pc["topics"]:
        raise ApiError("no_plan", "В наборе нет учебного плана для календаря", 422)
    meta = an.load_meta(session, org_id, dataset_id)
    topics = [cal.CalTopic(t["code"], t["current_hours"], t["title_ru"], t["topic_id"]) for t in pc["topics"]]
    cur = cal.sequential_fill(topics, [DEFAULT_WEEKLY_HOURS] * DEFAULT_WEEKS, set(w - 1 for w in DEFAULT_UNAVAILABLE))
    return {"defaults": {"start_date": DEFAULT_START.isoformat(), "n_weeks": DEFAULT_WEEKS, "weekly_hours": DEFAULT_WEEKLY_HOURS,
                         "unavailable_weeks": DEFAULT_UNAVAILABLE},
            "weeks": _weeks(DEFAULT_START, DEFAULT_WEEKS),
            "topics": [{"code": t["code"], "title_ru": t["title_ru"], "title_kz": t["title_kz"], "hours": t["current_hours"],
                        "status": t["topic_status"]} for t in pc["topics"]],
            "prerequisites": [{"before": a, "topic": b} for a, b in _prereqs(session, meta)],
            "current": _schedule_out(cur), "plan": pc["plan"],
            "note_ru": "Действующий календарь построен последовательным заполнением недель часами текущего плана в порядке "
                       "программы с условными каникулами; настройте даты и нагрузку под приказ школы."}


def _schedule_out(sched: dict) -> dict:
    return {code: {str(w + 1): h for w, h in sorted((k, v) for k, v in weeks.items() if isinstance(k, int))}
            | ({"unplaced": weeks["unplaced"]} if "unplaced" in weeks else {}) for code, weeks in sched.items()}


def _span(weeks: dict) -> tuple[int, int] | None:
    ws = sorted(w for w in weeks if isinstance(w, int))
    return (ws[0], ws[-1]) if ws else None


def _hours_from_plan(session: Session, org_id: str, dataset_id: str, analysis_id: str, preset: str) -> dict[str, int]:
    run = session.scalar(select(m.AnalysisRun).where(m.AnalysisRun.id == analysis_id, m.AnalysisRun.org_id == org_id))
    if run is None or run.kind != "plan" or run.dataset_id != dataset_id:
        raise not_found("plan_analysis", analysis_id)
    sc = next((s for s in run.result["scenarios"] if s["preset"] == preset), None)
    if sc is None or sc["status"] not in ("optimal", "feasible"):
        raise ApiError("plan_not_feasible", "Выбранный сценарий плана не имеет допустимого решения", 422)
    return {c["code"]: c["after"] for c in sc["changes"]}


def solve(session: Session, org_id: str, req: CalendarRequest, user_id: str | None) -> dict:
    if not 1 <= req.n_weeks <= MAX_WEEKS:
        raise ApiError("invalid_parameter", f"Недель: 1–{MAX_WEEKS}", 422)
    if not 0 <= req.weekly_hours <= 40 or any(not 0 <= v <= 40 for v in req.week_hours.values()):
        raise ApiError("invalid_parameter", "Недельная нагрузка 0–40 ч", 422)
    ds = an.get_dataset(session, org_id, req.dataset_id)
    ctx = context(session, org_id, req.dataset_id, req.filters, user_id)
    codes = [t["code"] for t in ctx["topics"]]
    hours_cur = {t["code"]: t["hours"] for t in ctx["topics"]}
    hours_new = dict(hours_cur)
    if req.plan_analysis_id:
        hours_new.update(_hours_from_plan(session, org_id, req.dataset_id, req.plan_analysis_id, req.plan_preset))
    for c, h in req.topic_hours.items():
        if c not in hours_new:
            raise ApiError("unknown_topic", "Тема не найдена в плане", 422, {"topic": c, "known": codes})
        if not 0 <= h <= 200:
            raise ApiError("invalid_parameter", "Часы темы 0–200", 422, {"topic": c})
        hours_new[c] = h
    unavailable_1 = DEFAULT_UNAVAILABLE if req.unavailable_weeks is None else req.unavailable_weeks
    if any(not 1 <= w <= req.n_weeks for w in unavailable_1) or any(not 1 <= w <= req.n_weeks for w in req.week_hours):
        raise ApiError("invalid_parameter", "Номер недели вне диапазона", 422)
    fixed = {}
    for fw in req.fixed:
        if fw.topic not in hours_new:
            raise ApiError("unknown_topic", "Тема не найдена в плане", 422, {"topic": fw.topic})
        for v in (fw.from_week, fw.to_week):
            if v is not None and not 1 <= v <= req.n_weeks:
                raise ApiError("invalid_parameter", "Номер недели вне диапазона", 422, {"topic": fw.topic})
        fixed[fw.topic] = fw
    capacity = [req.week_hours.get(i + 1, req.weekly_hours) for i in range(req.n_weeks)]
    unavailable = {w - 1 for w in unavailable_1}
    topics = [cal.CalTopic(c, hours_new[c], fixed_from=(fixed[c].from_week - 1 if c in fixed and fixed[c].from_week else None),
                           fixed_to=(fixed[c].to_week - 1 if c in fixed and fixed[c].to_week else None))
              for c in codes if hours_new[c] > 0]
    meta = an.load_meta(session, org_id, req.dataset_id)
    prereqs = _prereqs(session, meta)
    cur_topics = [cal.CalTopic(c, hours_cur[c]) for c in codes]
    current = cal.sequential_fill(cur_topics, [DEFAULT_WEEKLY_HOURS] * DEFAULT_WEEKS, {w - 1 for w in DEFAULT_UNAVAILABLE})
    problem = cal.CalProblem(topics=topics, capacity=capacity, unavailable=unavailable, prerequisites=prereqs,
                             keep_order=req.keep_order, current={c: {k: v for k, v in w.items() if isinstance(k, int)} for c, w in current.items()})

    def compute():
        res = cal.solve(problem)
        out = {"status": res["status"], "method_version": res["method_version"], "solver": res["solver"],
               "validation": res["validation"], "weeks": _weeks(req.start_date, req.n_weeks),
               "capacity": capacity, "unavailable_weeks": sorted(unavailable_1), "keep_order": req.keep_order,
               "hours": {"current": hours_cur, "proposed": hours_new}, "prerequisites": [{"before": a, "topic": b} for a, b in prereqs],
               "current": _schedule_out(current), "proposed": None, "load": None, "moves": [], "conflict": None,
               "is_forecast": False,
               "note_ru": "Календарь распределяет часы тем по учебным неделям. Это план, а не расписание уроков и не прогноз результатов."}
        if res["status"] == "infeasible" and res["conflict"]:
            out["conflict"] = _label_conflict(res["conflict"])
        if res["schedule"] is not None:
            sched = res["schedule"]
            out["proposed"] = _schedule_out(sched)
            out["load"] = [{"week": w + 1, "capacity": capacity[w], "unavailable": w in unavailable,
                            "current": sum(current[c].get(w, 0) for c in current if True),
                            "proposed": sum(sched[c].get(w, 0) for c in sched)} for w in range(req.n_weeks)]
            out["moves"] = _explain(codes, hours_cur, hours_new, current, sched, problem, req, ctx)
        return out

    params = req.model_dump(mode="json", exclude={"filters", "dataset_id"})
    return an.persist_or_reuse(session, org_id, ds, "calendar", req.filters.model_dump(), params, cal.METHOD_VERSION_CALENDAR, compute, user_id)


def _label_conflict(conflict: dict) -> dict:
    items = []
    for c in conflict["constraints"]:
        p = {**c, "weeks_h": ", ".join(str(w + 1) for w in c.get("weeks", [])),
             "from_h": (c["from_week"] + 1) if c.get("from_week") is not None else 1,
             "to_h": (c["to_week"] + 1) if c.get("to_week") is not None else "конца"}
        ru, kz = LABELS.get(c["constraint"], (c["constraint"], c["constraint"]))
        items.append({**c, "message_ru": ru.format(**p), "message_kz": kz.format(**p)})
    ar = conflict.get("arithmetic")
    if ar:
        ar = {**ar, "from_week": ar["from_week"] + 1, "to_week": ar["to_week"] + 1,
              "message_ru": f"Нужно {ar['hours_needed']} ч, а в неделях {ar['from_week'] + 1}–{ar['to_week'] + 1} доступно {ar['hours_available']} ч."}
    return {**conflict, "constraints": items, "arithmetic": ar}


def _explain(codes, hours_cur, hours_new, current, sched, problem: cal.CalProblem, req: CalendarRequest, ctx) -> list[dict]:
    default_unav = {w - 1 for w in DEFAULT_UNAVAILABLE}
    added = sorted(problem.unavailable - default_unav)
    released = sorted(default_unav - problem.unavailable)
    cap_changed = req.weekly_hours != DEFAULT_WEEKLY_HOURS or bool(req.week_hours)
    out = []
    cum = 0
    for c in codes:
        cs, ns = _span(current.get(c, {})), _span(sched.get(c, {}))
        reasons = []

        def add(code, reasons=reasons, **kw):
            ru, kz = REASONS[code]
            reasons.append({"code": code, "params": kw, "text_ru": ru.format(**kw), "text_kz": kz.format(**kw)})

        moved = cs != ns or hours_cur[c] != hours_new[c]
        if moved:
            if hours_cur[c] != hours_new[c]:
                add("hours_changed", from_h=hours_cur[c], to_h=hours_new[c])
            if cum:
                add("earlier_topics_hours", sign="+" if cum > 0 else "−", n=abs(cum))
            last = ns[1] if ns else (cs[1] if cs else -1)
            if [w for w in added if w <= last]:
                add("new_unavailable_weeks", weeks=", ".join(str(w + 1) for w in added if w <= last))
            if [w for w in released if w <= last]:
                add("weeks_released", weeks=", ".join(str(w + 1) for w in released if w <= last))
            if cap_changed:
                add("weekly_load_changed", from_h=DEFAULT_WEEKLY_HOURS, to_h=req.weekly_hours)
            t = next((x for x in problem.topics if x.code == c), None)
            if t and ns and (t.fixed_from is not None and ns[0] == t.fixed_from or t.fixed_to is not None and ns[1] == t.fixed_to):
                add("fixed_window", from_h=(t.fixed_from or 0) + 1, to_h=(t.fixed_to + 1) if t.fixed_to is not None else req.n_weeks)
            if ns:
                for a, b in problem.prerequisites:
                    sa = _span(sched.get(a, {}))
                    if b == c and sa and sa[1] == ns[0]:
                        add("waits_for_prerequisite", before=a)
                if not problem.keep_order:
                    i = codes.index(c)
                    for prev in codes[:i]:
                        sp = _span(sched.get(prev, {}))
                        if sp and sp[0] > ns[0]:
                            add("order_relaxed", before=prev)
                            break
            if not reasons:
                add("solver_tradeoff")
        else:
            add("unchanged")
        cum += hours_new[c] - hours_cur[c]
        out.append({"topic": c, "moved": moved,
                    "current": {"start": cs[0] + 1, "end": cs[1] + 1} if cs else None,
                    "proposed": {"start": ns[0] + 1, "end": ns[1] + 1} if ns else None,
                    "shift_start": (ns[0] - cs[0]) if cs and ns else None, "shift_end": (ns[1] - cs[1]) if cs and ns else None,
                    "hours": {"current": hours_cur[c], "proposed": hours_new[c]}, "reasons": reasons})
    return out
