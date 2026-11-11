"""Decision Sandbox: compare 2–3 hour scenarios side by side with the current plan ("было").

A methodist describes an intent in plain words ("добавь 2 часа на T3 за счёт T7, T5 не трогать"); it is turned
into *typed* planner operations with a diff preview that the user confirms. Each scenario is solved by CP-SAT and
re-checked by the independent validator; the comparison shows hours, coverage of measured objectives,
prerequisite risks and other risks. The objective distributes pedagogical priority — it is not a forecast of
score gains. Results are stored as analysis runs (replayable by fingerprint) and can be turned into a decision.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ApiError
from . import analysis as an
from . import planning

METHOD_VERSION_SANDBOX = "sandbox-v1"
OPS = ("add", "remove", "set", "min", "max", "fix", "max_change", "priority", "budget")


OPS_SCHEMA = {"type": "object", "properties": {"ops": {"type": "array", "items": {
    "type": "object", "properties": {"op": {"type": "string", "enum": list(OPS)}, "topic": {"type": "string"}, "value": {"type": "number"}},
    "required": ["op"], "additionalProperties": False}}}, "required": ["ops"], "additionalProperties": False}


class Op(BaseModel):
    op: str
    topic: str | None = None  # topic code; None for budget / global max_change
    value: float | None = None


class Scenario(BaseModel):
    name: str
    ops: list[Op] = Field(default_factory=list)


class SandboxRequest(BaseModel):
    dataset_id: str
    scenarios: list[Scenario]
    filters: an.Filters = Field(default_factory=an.Filters)


class IntentRequest(BaseModel):
    dataset_id: str
    text: str
    base_ops: list[Op] = Field(default_factory=list)
    lang: str = "ru"


# ---------------------------------------------------------------------------
# Intent → typed operations
# ---------------------------------------------------------------------------

NUM = r"(\d{1,3})"
TOPIC = r"(T\d{1,2})"
PRI = r"(\d(?:[.,]\d+)?)"
PATTERNS: list[tuple[re.Pattern, callable]] = [
    (re.compile(rf"(?:добав\w*|увелич\w*|плюс|\+|қос\w*)\s*{NUM}\s*(?:ч\w*|сағ\w*)?\s*(?:на|к|для|по)?\s*(?:тем\w*\s*)?{TOPIC}", re.I),
     lambda g: [Op(op="add", topic=g[1].upper(), value=int(g[0]))]),
    (re.compile(rf"{TOPIC}\s*(?:на\s*)?\+\s*{NUM}", re.I), lambda g: [Op(op="add", topic=g[0].upper(), value=int(g[1]))]),
    (re.compile(rf"(?:за\s*сч[её]т|забрать\s*(?:у|из)|убав\w*\s*(?:у|в)?|сократ\w*|азайт\w*)\s*(?:тем\w*\s*)?{TOPIC}(?:\s*на\s*{NUM})?", re.I),
     lambda g: [Op(op="remove", topic=g[0].upper(), value=int(g[1]) if g[1] else None)]),
    (re.compile(rf"{TOPIC}\s*(?:не\s*(?:трогать|менять|трогай|меняй)|зафикс\w*|без\s*изменений|өзгертпе\w*)", re.I),
     lambda g: [Op(op="fix", topic=g[0].upper())]),
    (re.compile(rf"(?:не\s*(?:трогать|менять|трогай|меняй)|зафиксир\w*)\s*(?:тем\w*\s*)?{TOPIC}", re.I),
     lambda g: [Op(op="fix", topic=g[0].upper())]),
    (re.compile(rf"(?:на\s*)?{TOPIC}\s*(?:не\s*меньше|минимум|хотя\s*бы|от)\s*{NUM}", re.I),
     lambda g: [Op(op="min", topic=g[0].upper(), value=int(g[1]))]),
    (re.compile(rf"(?:не\s*меньше|минимум|хотя\s*бы)\s*{NUM}\s*(?:ч\w*)?\s*(?:на|для)\s*{TOPIC}", re.I),
     lambda g: [Op(op="min", topic=g[1].upper(), value=int(g[0]))]),
    (re.compile(rf"{TOPIC}\s*(?:не\s*больше|максимум|до)\s*{NUM}", re.I),
     lambda g: [Op(op="max", topic=g[0].upper(), value=int(g[1]))]),
    (re.compile(rf"{TOPIC}\s*(?:=|ровно)\s*{NUM}", re.I), lambda g: [Op(op="set", topic=g[0].upper(), value=int(g[1]))]),
    (re.compile(rf"(?:(?:каждую|любую)\s*тему\s*)?(?:изменени\w*|менять|изменять)\s*(?:не\s*больше|максимум|не\s*более)\s*(?:чем\s*на\s*)?{NUM}", re.I),
     lambda g: [Op(op="max_change", value=int(g[0]))]),
    (re.compile(rf"(?:бюджет|всего|итого)\s*{NUM}", re.I), lambda g: [Op(op="budget", value=int(g[0]))]),
    (re.compile(rf"(?:приоритет\w*)\s*{TOPIC}\s*{PRI}", re.I),
     lambda g: [Op(op="priority", topic=g[0].upper(), value=float(g[1].replace(",", ".")))]),
]


def parse_intent(text: str) -> tuple[list[Op], list[str]]:
    ops: list[Op] = []
    spans: list[tuple[int, int]] = []
    for pat, build in PATTERNS:
        for mt in pat.finditer(text):
            if any(a < mt.end() and mt.start() < b for a, b in spans):
                continue
            spans.append((mt.start(), mt.end()))
            ops += build(mt.groups())
    rest = text
    for a, b in sorted(spans, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    leftovers = [w for w in re.split(r"[,;.]|\bи\b|\bа\b", rest) if re.search(r"\w{3,}", w)
                 and not re.fullmatch(r"\s*(пожалуйста|давай|сделай|часа?|часов|тема|темы)\s*", w, re.I)]
    # paired "add N to X за счёт Y": the removal takes the same N unless given
    adds = [o for o in ops if o.op == "add"]
    for o in ops:
        if o.op == "remove" and o.value is None:
            o.value = adds[0].value if adds else 1
    return ops, [w.strip() for w in leftovers]


def _base(session: Session, org_id: str, dataset_id: str, f: an.Filters, user_id: str | None) -> dict:
    ctx = planning.plan_context(session, org_id, dataset_id, f, user_id)
    if not ctx["topics"]:
        raise ApiError("no_plan", "В наборе нет учебного плана для песочницы", 422)
    return ctx


def apply_ops(ctx: dict, ops: list[Op]) -> tuple[list[dict], int, list[dict]]:
    """Returns (topic inputs, budget, diff rows). Unknown topic codes are rejected (typed constraints only)."""
    topics = {t["code"]: {"topic_id": t["topic_id"], "code": t["code"], "title": t["title_ru"], "current_hours": t["current_hours"],
                          "priority": t["priority"], "min_hours": t["min_hours"], "max_hours": t["max_hours"],
                          "fixed": False, "elapsed_hours": t["elapsed_hours"], "max_change": None, "target": None}
              for t in ctx["topics"]}
    budget = ctx["budget"]
    diff: list[dict] = []

    def rec(code, field, before, after):
        diff.append({"topic": code, "field": field, "before": before, "after": after})

    for o in ops:
        if o.op not in OPS:
            raise ApiError("invalid_op", "Неизвестная операция", 422, {"op": o.op, "allowed": list(OPS)})
        if o.op in ("budget", "max_change") and o.topic is None:
            if o.value is None or o.value < 0:
                raise ApiError("invalid_op", "Нужно неотрицательное значение", 422, {"op": o.op})
            if o.op == "budget":
                rec(None, "budget", budget, int(o.value))
                budget = int(o.value)
            else:
                for t in topics.values():
                    t["max_change"] = int(o.value)
                rec(None, "max_change", None, int(o.value))
            continue
        if o.topic not in topics:
            raise ApiError("unknown_topic", "Тема не найдена в плане", 422, {"topic": o.topic, "known": sorted(topics)})
        t = topics[o.topic]
        v = None if o.value is None else o.value
        if o.op in ("add", "remove", "set", "min", "max") and (v is None or v < 0 or v > 200):
            raise ApiError("invalid_op", "Значение часов вне диапазона", 422, {"op": o.op, "topic": o.topic})
        if o.op in ("add", "remove", "set"):
            cur = t["target"] if t["target"] is not None else t["current_hours"]
            new = cur + int(v) if o.op == "add" else max(0, cur - int(v)) if o.op == "remove" else int(v)
            t["target"] = new
            rec(o.topic, "target_hours", cur, new)
        elif o.op == "min":
            rec(o.topic, "min_hours", t["min_hours"], int(v))
            t["min_hours"] = int(v)
        elif o.op == "max":
            rec(o.topic, "max_hours", t["max_hours"], int(v))
            t["max_hours"] = int(v)
        elif o.op == "fix":
            rec(o.topic, "fixed", False, True)
            t["fixed"] = True
        elif o.op == "priority":
            if v is None or not 0 <= v <= 1:
                raise ApiError("invalid_op", "Приоритет 0–1", 422, {"topic": o.topic})
            rec(o.topic, "priority", t["priority"], v)
            t["priority"] = v
    out = []
    for t in topics.values():
        tgt = t.pop("target")
        if tgt is not None:
            # the requested target becomes hard bounds, but never silently overrides the plan's own limits:
            # a target outside [min, max] stays a conflict that the solver reports and explains
            lo, hi = t["min_hours"], t["max_hours"]
            t["min_hours"] = tgt if lo is None or tgt >= lo else lo
            t["max_hours"] = tgt if hi is None or tgt <= hi else hi
            if t["min_hours"] > t["max_hours"]:
                t["min_hours"] = tgt
        out.append(t)
    return out, budget, diff


def preview(session: Session, org_id: str, req: IntentRequest, user_id: str | None) -> dict:
    if len(req.text) > 500:
        raise ApiError("too_long", "Слишком длинный запрос", 422)
    ops, leftovers = parse_intent(req.text)
    ctx = _base(session, org_id, req.dataset_id, an.Filters(), user_id)
    mode = "template"
    if leftovers:  # the rule parser did not understand everything: a live model may propose typed ops (validated)
        from ..ai.tasks import _live_or_none

        data, lm = _live_or_none("sandbox_intent", "Переведи пожелание методиста в операции планировщика часов. Используй только "
                                 "коды тем из списка topics и операции из схемы; ничего не придумывай. Ответ строго JSON.",
                                 {"text": req.text, "topics": [t["code"] for t in ctx["topics"]]}, OPS_SCHEMA,
                                 synthetic=bool(an.get_dataset(session, org_id, req.dataset_id).is_synthetic))
        if data is not None:
            ops, leftovers, mode = [Op(**o) for o in data["ops"][:12]], [], lm["mode"]
    all_ops = req.base_ops + ops
    _, _, diff = apply_ops(ctx, all_ops)  # validates topics/values; raises on unknown topic
    return {"ops": [o.model_dump() for o in ops], "all_ops": [o.model_dump() for o in all_ops], "diff": diff,
            "not_understood": leftovers, "mode": mode,
            "note_ru": "Запрос переведён в типизированные ограничения планировщика. Проверьте изменения перед расчётом."}


def run(session: Session, org_id: str, req: SandboxRequest, user_id: str | None) -> dict:
    if not 1 <= len(req.scenarios) <= 3:
        raise ApiError("invalid_parameter", "От 1 до 3 сценариев", 422)
    ds = an.get_dataset(session, org_id, req.dataset_id)
    ctx = _base(session, org_id, req.dataset_id, req.filters, user_id)
    measured = {t["code"]: t for t in ctx["topics"]}
    # prerequisites between topics (via objective relations)
    meta = an.load_meta(session, org_id, req.dataset_id)
    obj_topic = {o.id: o.topic_id for o in meta.objectives}
    code_of = {t.id: t.code for t in meta.topics}
    rels = list(session.scalars(select(m.ObjectiveRelation).where(m.ObjectiveRelation.target_objective_id.in_(list(obj_topic)))))
    prereq_of: dict[str, set[str]] = {}
    for r in rels:
        a, b = code_of.get(obj_topic.get(r.source_objective_id)), code_of.get(obj_topic.get(r.target_objective_id))
        if a and b and a != b:
            prereq_of.setdefault(a, set()).add(b)
    n_obj = {t.code: sum(1 for o in meta.objectives if o.topic_id == t.id) for t in meta.topics}

    def compute():
        cols = []
        for sc in req.scenarios:
            topics, budget, diff = apply_ops(ctx, sc.ops)
            body = planning.PlanSolveRequest(dataset_id=req.dataset_id, filters=req.filters, topics=[planning.TopicInput(**t) for t in topics],
                                             budget=budget, presets=["balanced"], source_analysis_id=ctx["source_analysis_id"])
            pr = planning.solve(session, org_id, body, user_id)
            res = pr["result"]["scenarios"][0]
            col = {"name": sc.name[:60], "ops": [o.model_dump() for o in sc.ops], "diff": diff, "status": res["status"],
                   "status_message_ru": res["status_message_ru"], "plan_analysis_id": pr["context"]["analysis_id"],
                   "budget": budget, "conflict": res.get("conflict"), "validation": res.get("validation")}
            if res["status"] in ("optimal", "feasible"):
                hours = {c["code"]: c["after"] for c in res["changes"]}
                col["hours"] = hours
                col["metrics"] = _metrics(hours, measured, prereq_of, n_obj)
            cols.append(col)
        before = {t["code"]: t["current_hours"] for t in ctx["topics"]}
        return {"before": {"hours": before, "metrics": _metrics(before, measured, prereq_of, n_obj), "budget": ctx["budget"]},
                "scenarios": cols, "topics": [{"code": t["code"], "title_ru": t["title_ru"], "title_kz": t["title_kz"],
                                               "status": t["topic_status"], "score": t["score"]} for t in ctx["topics"]],
                "is_calendar": False, "is_forecast": False,
                "note_ru": "Сравниваются распределения часов и риски. Это не прогноз роста баллов и не расписание по неделям."}

    params = {"scenarios": [s.model_dump() for s in req.scenarios]}
    return an.persist_or_reuse(session, org_id, ds, "sandbox", req.filters.model_dump(), params, METHOD_VERSION_SANDBOX, compute, user_id)


def _metrics(hours: dict[str, int], measured: dict[str, dict], prereq_of: dict[str, set[str]], n_obj: dict[str, int]) -> dict:
    weak = {c for c, t in measured.items() if t["topic_status"] == "difficult"}
    risks = []
    covered = 0
    total = 0
    for c, t in measured.items():
        h = hours.get(c, 0)
        total += n_obj.get(c, 0)
        if h > 0 and (t["min_hours"] is None or h >= t["min_hours"]):
            covered += n_obj.get(c, 0)
        if c in weak and h < t["current_hours"]:
            risks.append({"code": "weak_topic_reduced", "topic": c, "text_ru": f"Слабой теме {c} сокращены часы"})
        if t["topic_status"] in ("not_measured", "unverified_mapping", "insufficient_data") and h != t["current_hours"]:
            risks.append({"code": "change_without_evidence", "topic": c, "text_ru": f"Изменение часов темы {c} без надёжных данных"})
    prereq_risks = []
    for a, targets in prereq_of.items():
        if a in hours and a in measured and hours[a] < measured[a]["current_hours"] and targets & weak:
            prereq_risks.append({"code": "prerequisite_reduced", "topic": a, "for": sorted(targets & weak),
                                 "text_ru": f"Сокращён пререквизит {a} для слабых тем {', '.join(sorted(targets & weak))}"})
    weak_hours = sum(hours.get(c, 0) for c in weak)
    return {"objective_coverage": {"covered": covered, "total": total}, "weak_topics": sorted(weak),
            "hours_on_weak_topics": weak_hours, "total_hours": sum(hours.values()),
            "risks": risks, "prerequisite_risks": prereq_risks}
