"""Hours allocation under constraints (OR-Tools CP-SAT) with an independent validator.

The objective distributes *pedagogical priority* with diminishing returns and penalises changes. It is a
planning device, not a forecast of score gains (docs/METHODOLOGY.md §6).

    maximize  sum_t p_t * U(h_t)  -  lambda * sum_t |h_t - h0_t|
    U(h) = (1 - r^h) / (1 - r)                         (concave, r in (0,1))
    default r = 0.5^(1/mean(h0)): the marginal value of an hour halves at the average topic size, so the
    objective is scale-free with respect to the size of the plan.

Constraints: integer hours, sum(h) = budget, min/max per topic, fixed topics, elapsed hours cannot be
removed (h_t >= elapsed_t), optional max change per topic. The plan is a per-topic hours plan, not a
weekly calendar.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from ortools.sat.python import cp_model

METHOD_VERSION_PLANNER = "planner-v1"
OBJECTIVE_SCALE = 1000


@dataclass
class TopicConstraint:
    topic_id: str
    code: str
    current_hours: int
    priority: float = 1.0
    min_hours: int | None = None
    max_hours: int | None = None
    fixed: bool = False
    elapsed_hours: int = 0
    max_change: int | None = None
    title: str = ""


@dataclass
class PlanProblem:
    topics: list[TopicConstraint]
    budget: int
    change_penalty: float = 0.05  # lambda, in priority-utility units per hour moved
    diminishing_rate: float | None = None  # r; None => 0.5 ** (1 / mean current hours)
    time_limit_seconds: float = 5.0
    weights_version: str = "priority-weights-v1"
    meta: dict = field(default_factory=dict)


@dataclass
class Violation:
    constraint: str
    topic_code: str | None
    detail: dict

    def as_dict(self) -> dict:
        return asdict(self)


def effective_rate(problem: PlanProblem) -> float:
    if problem.diminishing_rate is not None:
        return problem.diminishing_rate
    hs = [t.current_hours for t in problem.topics if t.current_hours > 0]
    mean_h = sum(hs) / len(hs) if hs else 1.0
    return 0.5 ** (1.0 / max(mean_h, 1.0))


def utility(h: int, r: float) -> float:
    return (1 - r**h) / (1 - r)


def validate_plan(problem: PlanProblem, hours: dict[str, int]) -> list[Violation]:
    """Independent check of every constraint; does not use the solver."""
    out: list[Violation] = []
    total = 0
    for t in problem.topics:
        if t.topic_id not in hours:
            out.append(Violation("missing_topic", t.code, {}))
            continue
        h = hours[t.topic_id]
        if not isinstance(h, int) or isinstance(h, bool):
            out.append(Violation("non_integer", t.code, {"value": h}))
            continue
        total += h
        if h < 0:
            out.append(Violation("negative", t.code, {"value": h}))
        if t.min_hours is not None and h < t.min_hours:
            out.append(Violation("min_hours", t.code, {"value": h, "min": t.min_hours}))
        if t.max_hours is not None and h > t.max_hours:
            out.append(Violation("max_hours", t.code, {"value": h, "max": t.max_hours}))
        if t.fixed and h != t.current_hours:
            out.append(Violation("fixed", t.code, {"value": h, "required": t.current_hours}))
        if h < t.elapsed_hours:
            out.append(Violation("elapsed_hours", t.code, {"value": h, "elapsed": t.elapsed_hours}))
        if t.max_change is not None and abs(h - t.current_hours) > t.max_change:
            out.append(Violation("max_change", t.code, {"value": h, "current": t.current_hours, "max_change": t.max_change}))
    extra = set(hours) - {t.topic_id for t in problem.topics}
    for e in extra:
        out.append(Violation("unknown_topic", None, {"topic_id": e}))
    if total != problem.budget:
        out.append(Violation("budget", None, {"total": total, "budget": problem.budget}))
    return out


def objective_value(problem: PlanProblem, hours: dict[str, int]) -> float:
    r = effective_rate(problem)
    v = 0.0
    for t in problem.topics:
        h = hours[t.topic_id]
        v += t.priority * utility(h, r) - problem.change_penalty * abs(h - t.current_hours)
    return v


# ---------------------------------------------------------------------------
# Model construction with one enforcement literal per constraint (for conflict explanation)
# ---------------------------------------------------------------------------


@dataclass
class _Built:
    model: cp_model.CpModel
    h: dict[str, cp_model.IntVar]
    lits: dict[str, cp_model.IntVar]
    labels: dict[str, dict]


def _build(problem: PlanProblem, with_objective: bool) -> _Built:
    m = cp_model.CpModel()
    H = max(problem.budget, 0)
    ub = max(H, max((t.current_hours for t in problem.topics), default=0))
    h = {t.topic_id: m.NewIntVar(0, ub, f"h_{t.code}") for t in problem.topics}
    lits: dict[str, cp_model.IntVar] = {}
    labels: dict[str, dict] = {}

    def lit(key: str, label: dict) -> cp_model.IntVar:
        b = m.NewBoolVar(key)
        lits[key] = b
        labels[key] = label
        return b

    b = lit("budget", {"constraint": "budget", "topic_code": None, "value": problem.budget})
    m.Add(sum(h.values()) == problem.budget).OnlyEnforceIf(b)
    for t in problem.topics:
        if t.min_hours is not None:
            m.Add(h[t.topic_id] >= t.min_hours).OnlyEnforceIf(
                lit(f"min:{t.code}", {"constraint": "min_hours", "topic_code": t.code, "value": t.min_hours})
            )
        if t.max_hours is not None:
            m.Add(h[t.topic_id] <= t.max_hours).OnlyEnforceIf(
                lit(f"max:{t.code}", {"constraint": "max_hours", "topic_code": t.code, "value": t.max_hours})
            )
        if t.fixed:
            m.Add(h[t.topic_id] == t.current_hours).OnlyEnforceIf(
                lit(f"fixed:{t.code}", {"constraint": "fixed", "topic_code": t.code, "value": t.current_hours})
            )
        if t.elapsed_hours > 0:
            m.Add(h[t.topic_id] >= t.elapsed_hours).OnlyEnforceIf(
                lit(f"elapsed:{t.code}", {"constraint": "elapsed_hours", "topic_code": t.code, "value": t.elapsed_hours})
            )
        if t.max_change is not None:
            k = lit(f"change:{t.code}", {"constraint": "max_change", "topic_code": t.code, "value": t.max_change})
            m.Add(h[t.topic_id] - t.current_hours <= t.max_change).OnlyEnforceIf(k)
            m.Add(t.current_hours - h[t.topic_id] <= t.max_change).OnlyEnforceIf(k)

    if with_objective:
        r = effective_rate(problem)
        terms = []
        for t in problem.topics:
            table = [int(round(OBJECTIVE_SCALE * t.priority * utility(k, r))) for k in range(ub + 1)]
            u = m.NewIntVar(min(table), max(table), f"u_{t.code}")
            m.AddElement(h[t.topic_id], table, u)
            d = m.NewIntVar(0, ub, f"d_{t.code}")
            m.AddAbsEquality(d, h[t.topic_id] - t.current_hours)
            terms.append(u - int(round(OBJECTIVE_SCALE * problem.change_penalty)) * d)
        m.Maximize(sum(terms))
    return _Built(m, h, lits, labels)


def _feasible_with(problem: PlanProblem, keys: list[str], time_limit: float) -> str:
    built = _build(problem, with_objective=False)
    for k, b in built.lits.items():
        if k not in keys:
            built.model.Add(b == 0)  # constraint switched off
    built.model.AddAssumptions([built.lits[k] for k in keys])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    st = solver.Solve(built.model)
    return {cp_model.OPTIMAL: "feasible", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible"}.get(st, "unknown")


def explain_infeasibility(problem: PlanProblem, time_limit: float = 2.0) -> dict:
    """Return a verified minimal set of mutually incompatible constraints.

    1) CP-SAT returns a sufficient set of assumptions; 2) deletion-based minimisation; each removal is
    re-solved, so every listed constraint is necessary for the conflict (verified, not narrated)."""
    built = _build(problem, with_objective=False)
    built.model.AddAssumptions(list(built.lits.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    st = solver.Solve(built.model)
    if st != cp_model.INFEASIBLE:
        return {"verified": False, "reason": "not_proven_infeasible", "constraints": []}
    idx_to_key = {b.Index(): k for k, b in built.lits.items()}
    core = [idx_to_key[i] for i in solver.SufficientAssumptionsForInfeasibility() if i in idx_to_key]
    if not core or _feasible_with(problem, core, time_limit) != "infeasible":
        core = list(built.lits)
    i = 0
    while i < len(core):
        trial = core[:i] + core[i + 1 :]
        if trial and _feasible_with(problem, trial, time_limit) == "infeasible":
            core = trial
        else:
            i += 1
    verified = _feasible_with(problem, core, time_limit) == "infeasible" and all(
        _feasible_with(problem, core[:j] + core[j + 1 :], time_limit) == "feasible" for j in range(len(core))
    )
    by_code = {t.code: t for t in problem.topics}
    items = []
    lower, upper = 0, 0
    for k in core:
        lab = dict(built.labels[k])
        items.append({"key": k, **lab})
    # Arithmetic summary over topics, using only constraints in the core.
    if "budget" in core:
        for t in problem.topics:
            lo, hi = 0, None
            for k in core:
                lab = built.labels[k]
                if lab["topic_code"] != t.code:
                    continue
                if lab["constraint"] in ("min_hours", "elapsed_hours"):
                    lo = max(lo, lab["value"])
                elif lab["constraint"] == "max_hours":
                    hi = lab["value"] if hi is None else min(hi, lab["value"])
                elif lab["constraint"] == "fixed":
                    lo = max(lo, lab["value"])
                    hi = lab["value"] if hi is None else min(hi, lab["value"])
                elif lab["constraint"] == "max_change":
                    cur = by_code[t.code].current_hours
                    lo = max(lo, cur - lab["value"])
                    hi = cur + lab["value"] if hi is None else min(hi, cur + lab["value"])
            lower += lo
            upper = None if (upper is None or hi is None) else upper + hi
            if hi is None:
                upper = None
    arithmetic = None
    if "budget" in core:
        arithmetic = {"budget": problem.budget, "sum_lower_bounds": lower, "sum_upper_bounds": upper}
    return {"verified": verified, "constraints": items, "arithmetic": arithmetic}


_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.UNKNOWN: "unknown",
    cp_model.MODEL_INVALID: "invalid",
}


def solve(problem: PlanProblem) -> dict:
    pre_errors = _input_errors(problem)
    if pre_errors:
        return {"status": "invalid", "input_errors": pre_errors, "hours": None, "method_version": METHOD_VERSION_PLANNER}
    built = _build(problem, with_objective=True)
    for b in built.lits.values():
        built.model.Add(b == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = problem.time_limit_seconds
    solver.parameters.num_workers = 4
    solver.parameters.random_seed = 7
    st = solver.Solve(built.model)
    status = _STATUS.get(st, "unknown")
    result: dict = {
        "status": status,
        "method_version": METHOD_VERSION_PLANNER,
        "weights_version": problem.weights_version,
        "objective": {
            "formula": "maximize Σ p_t·(1−r^h_t)/(1−r) − λ·Σ|h_t − h0_t|",
            "change_penalty": problem.change_penalty,
            "diminishing_rate": round(effective_rate(problem), 6),
            "diminishing_rate_rule": "explicit" if problem.diminishing_rate is not None else "0.5^(1/mean(h0))",
            "is_forecast": False,
        },
        "solver": {"name": "OR-Tools CP-SAT", "wall_time_seconds": round(solver.WallTime(), 4),
                   "time_limit_seconds": problem.time_limit_seconds},
        "hours": None,
        "validation": None,
        "conflict": None,
    }
    if status in ("optimal", "feasible"):
        hours = {tid: int(solver.Value(v)) for tid, v in built.h.items()}
        violations = validate_plan(problem, hours)
        if violations:
            # Should never happen; never present an invalid plan as a solution.
            result["status"] = "invalid"
            result["validation"] = {"valid": False, "violations": [v.as_dict() for v in violations]}
            return result
        result["hours"] = hours
        result["objective_value"] = round(objective_value(problem, hours), 6)
        result["validation"] = {"valid": True, "violations": []}
        result["changes"] = [
            {
                "topic_id": t.topic_id,
                "code": t.code,
                "title": t.title,
                "before": t.current_hours,
                "after": hours[t.topic_id],
                "delta": hours[t.topic_id] - t.current_hours,
                "priority": t.priority,
            }
            for t in problem.topics
        ]
        result["total_before"] = sum(t.current_hours for t in problem.topics)
        result["total_after"] = sum(hours.values())
    elif status == "infeasible":
        result["conflict"] = explain_infeasibility(problem)
    return result


def _input_errors(problem: PlanProblem) -> list[dict]:
    errs = []
    if problem.budget < 0:
        errs.append({"code": "negative_budget"})
    if problem.diminishing_rate is not None and not (0 < problem.diminishing_rate < 1):
        errs.append({"code": "bad_diminishing_rate"})
    if problem.change_penalty < 0 or not math.isfinite(problem.change_penalty):
        errs.append({"code": "bad_change_penalty"})
    seen = set()
    for t in problem.topics:
        if t.topic_id in seen:
            errs.append({"code": "duplicate_topic", "topic_code": t.code})
        seen.add(t.topic_id)
        if t.current_hours < 0 or t.elapsed_hours < 0:
            errs.append({"code": "negative_hours", "topic_code": t.code})
        if t.priority < 0 or not math.isfinite(t.priority):
            errs.append({"code": "bad_priority", "topic_code": t.code})
    return errs


def preset(problem: PlanProblem, name: str) -> PlanProblem:
    """Scenario presets shown to the methodist (weights stay visible and editable)."""
    import copy

    p = copy.deepcopy(problem)
    if name == "minimal_changes":
        p.change_penalty = max(problem.change_penalty * 3, 0.15)
    elif name == "focus_problem_topics":
        p.change_penalty = min(problem.change_penalty / 3, 0.015)
    elif name == "balanced":
        pass
    else:
        raise ValueError(name)
    p.meta = {**problem.meta, "preset": name}
    return p
