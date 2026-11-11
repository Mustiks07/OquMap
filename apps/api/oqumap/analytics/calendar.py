"""Weekly calendar: topics → weeks under weekly load, sequence/prerequisites, fixed windows and holidays.

Model (OR-Tools CP-SAT), topics t with planned hours H_t, weeks w with capacity c_w; unavailable weeks
(holidays) get x = 0 through a separate constraint, so a conflict can name the holidays explicitly:

    x[t,w] ∈ {0..c_w}  hours of topic t in week w,   y[t,w] = (x[t,w] > 0)
    Σ_w x[t,w] = H_t                                (topic gets exactly its planned hours)
    Σ_t x[t,w] ≤ c_w                                (weekly load)
    s_t ≤ w ≤ e_t for every active week; every *available* week in [s_t, e_t] is active (contiguous block,
    holidays may interrupt it)
    e_A ≤ s_B for each prerequisite A → B           (A is finished before B starts; they may share a week)
    e_i ≤ s_{i+1} in program order (option)          fixed windows: from_t ≤ s_t, e_t ≤ to_t

Objective: stay close to the current calendar (Σ|x − x_current|) and keep topics compact (Σ (e_t − s_t)).
Every solution is re-checked by ``validate`` (independent of the solver). Infeasible problems get a verified
minimal conflict (deletion filter over enforcement literals, each element re-solved) plus arithmetic
(hours needed vs hours available). Not a forecast; dates are planning weeks, not a timetable of lessons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

METHOD_VERSION_CALENDAR = "calendar-v1"


@dataclass
class CalTopic:
    code: str
    hours: int
    title: str = ""
    topic_id: str | None = None
    fixed_from: int | None = None  # week index (0-based), inclusive
    fixed_to: int | None = None


@dataclass
class CalProblem:
    topics: list[CalTopic]  # in program order
    capacity: list[int]  # normal weekly hours per week; unavailable weeks are excluded by the holidays constraint
    unavailable: set[int] = field(default_factory=set)
    prerequisites: list[tuple[str, str]] = field(default_factory=list)  # (A, B): A before B
    keep_order: bool = True
    current: dict[str, dict[int, int]] = field(default_factory=dict)  # topic → week → hours
    time_limit_seconds: float = 5.0


def sequential_fill(topics: list[CalTopic], capacity: list[int], unavailable: set[int]) -> dict[str, dict[int, int]]:
    """The 'current calendar': topics in program order fill available weeks one after another."""
    out: dict[str, dict[int, int]] = {t.code: {} for t in topics}
    w, left = 0, None
    n = len(capacity)
    for t in topics:
        need = t.hours
        while need > 0 and w < n:
            if left is None:
                left = 0 if w in unavailable else capacity[w]
            take = min(need, left)
            if take:
                out[t.code][w] = out[t.code].get(w, 0) + take
                need -= take
                left -= take
            if left == 0:
                w, left = w + 1, None
        if need > 0:
            out[t.code]["unplaced"] = need  # type: ignore[index]
    return out


class _Built:
    def __init__(self):
        self.m = cp_model.CpModel()
        self.x: dict[tuple[str, int], cp_model.IntVar] = {}
        self.y: dict[tuple[str, int], cp_model.IntVar] = {}
        self.s: dict[str, cp_model.IntVar] = {}
        self.e: dict[str, cp_model.IntVar] = {}
        self.lits: dict[str, cp_model.IntVar] = {}
        self.labels: dict[str, dict] = {}

    def lit(self, key: str, label: dict) -> cp_model.IntVar:
        b = self.m.NewBoolVar(key)
        self.lits[key] = b
        self.labels[key] = label
        return b


def _build(p: CalProblem, with_objective: bool) -> _Built:
    b = _Built()
    m = b.m
    n = len(p.capacity)
    cap_max = max(p.capacity + [0])
    hol = b.lit("holidays", {"constraint": "holidays", "weeks": sorted(p.unavailable)}) if p.unavailable else None
    load = b.lit("weekly_load", {"constraint": "weekly_load", "capacity": p.capacity})
    for t in p.topics:
        b.s[t.code] = m.NewIntVar(0, max(n - 1, 0), f"s_{t.code}")
        b.e[t.code] = m.NewIntVar(0, max(n - 1, 0), f"e_{t.code}")
        m.Add(b.s[t.code] <= b.e[t.code])
        for w in range(n):
            x = m.NewIntVar(0, cap_max, f"x_{t.code}_{w}")
            y = m.NewBoolVar(f"y_{t.code}_{w}")
            m.Add(x >= 1).OnlyEnforceIf(y)
            m.Add(x == 0).OnlyEnforceIf(y.Not())
            m.Add(b.s[t.code] <= w).OnlyEnforceIf(y)
            m.Add(b.e[t.code] >= w).OnlyEnforceIf(y)
            if hol is not None and w in p.unavailable:
                m.Add(x == 0).OnlyEnforceIf(hol)
            else:
                # contiguity: an available week inside [s, e] is used
                after_s = m.NewBoolVar("")
                before_e = m.NewBoolVar("")
                m.Add(b.s[t.code] <= w).OnlyEnforceIf(after_s)
                m.Add(b.s[t.code] > w).OnlyEnforceIf(after_s.Not())
                m.Add(b.e[t.code] >= w).OnlyEnforceIf(before_e)
                m.Add(b.e[t.code] < w).OnlyEnforceIf(before_e.Not())
                m.AddBoolOr([after_s.Not(), before_e.Not(), y])
            b.x[t.code, w], b.y[t.code, w] = x, y
        k = b.lit(f"hours:{t.code}", {"constraint": "topic_hours", "topic_code": t.code, "value": t.hours})
        m.Add(sum(b.x[t.code, w] for w in range(n)) == t.hours).OnlyEnforceIf(k)
        if t.fixed_from is not None or t.fixed_to is not None:
            k = b.lit(f"fixed:{t.code}", {"constraint": "fixed_window", "topic_code": t.code, "from_week": t.fixed_from,
                                         "to_week": t.fixed_to})
            if t.fixed_from is not None:
                m.Add(b.s[t.code] >= t.fixed_from).OnlyEnforceIf(k)
            if t.fixed_to is not None:
                m.Add(b.e[t.code] <= t.fixed_to).OnlyEnforceIf(k)
    for w in range(n):
        m.Add(sum(b.x[t.code, w] for t in p.topics) <= p.capacity[w]).OnlyEnforceIf(load)
    codes = {t.code for t in p.topics}
    for a, c in p.prerequisites:
        if a in codes and c in codes:
            k = b.lit(f"prereq:{a}>{c}", {"constraint": "prerequisite", "topic_code": c, "before": a})
            m.Add(b.e[a] <= b.s[c]).OnlyEnforceIf(k)
    if p.keep_order:
        for t1, t2 in zip(p.topics, p.topics[1:], strict=False):
            k = b.lit(f"order:{t1.code}>{t2.code}", {"constraint": "program_order", "topic_code": t2.code, "before": t1.code})
            m.Add(b.e[t1.code] <= b.s[t2.code]).OnlyEnforceIf(k)
    if with_objective:
        terms = []
        for t in p.topics:
            cur = p.current.get(t.code, {})
            for w in range(n):
                d = m.NewIntVar(0, cap_max + max(cur.values(), default=0), "")
                m.AddAbsEquality(d, b.x[t.code, w] - int(cur.get(w, 0)))
                terms.append(10 * d)
            terms.append(b.e[t.code] - b.s[t.code])
        m.Minimize(sum(terms))
    return b


def _status(st) -> str:
    return {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible",
            cp_model.MODEL_INVALID: "invalid"}.get(st, "unknown")


def _feasible_with(p: CalProblem, keys: list[str], tl: float) -> str:
    b = _build(p, with_objective=False)
    for k, v in b.lits.items():
        if k not in keys:
            b.m.Add(v == 0)
    b.m.AddAssumptions([b.lits[k] for k in keys])
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = tl
    s.parameters.num_workers = 1
    st = s.Solve(b.m)
    return "feasible" if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else ("infeasible" if st == cp_model.INFEASIBLE else "unknown")


def explain_infeasibility(p: CalProblem, tl: float = 2.0) -> dict:
    b = _build(p, with_objective=False)
    b.m.AddAssumptions(list(b.lits.values()))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = tl
    s.parameters.num_workers = 1
    if s.Solve(b.m) != cp_model.INFEASIBLE:
        return {"verified": False, "reason": "not_proven_infeasible", "constraints": []}
    idx = {v.Index(): k for k, v in b.lits.items()}
    core = [idx[i] for i in s.SufficientAssumptionsForInfeasibility() if i in idx]
    if not core or _feasible_with(p, core, tl) != "infeasible":
        core = list(b.lits)
    i = 0
    while i < len(core):
        trial = core[:i] + core[i + 1:]
        if trial and _feasible_with(p, trial, tl) == "infeasible":
            core = trial
        else:
            i += 1
    verified = _feasible_with(p, core, tl) == "infeasible" and all(
        _feasible_with(p, core[:j] + core[j + 1:], tl) == "feasible" for j in range(len(core)))
    items = [{"key": k, **b.labels[k]} for k in core]
    # arithmetic: hours that must fit vs capacity of the weeks they may use
    by = {t.code: t for t in p.topics}
    involved = [by[x["topic_code"]] for x in items if x.get("topic_code") in by and x["constraint"] == "topic_hours"]
    lo = min((t.fixed_from for t in involved if t.fixed_from is not None and f"fixed:{t.code}" in core), default=0)
    hi = max((t.fixed_to for t in involved if t.fixed_to is not None and f"fixed:{t.code}" in core), default=len(p.capacity) - 1)
    if not any(f"fixed:{t.code}" in core for t in involved):
        lo, hi = 0, len(p.capacity) - 1
    avail = sum(c for w, c in enumerate(p.capacity) if lo <= w <= hi and not ("holidays" in core and w in p.unavailable))
    arithmetic = {"hours_needed": sum(t.hours for t in involved), "hours_available": avail, "from_week": lo, "to_week": hi} \
        if involved else None
    return {"verified": verified, "constraints": items, "arithmetic": arithmetic}


def validate(p: CalProblem, sched: dict[str, dict[int, int]]) -> list[dict]:
    """Independent check of a calendar (no solver involved)."""
    v = []
    n = len(p.capacity)
    weeks = {t.code: sorted(w for w, h in sched.get(t.code, {}).items() if h > 0) for t in p.topics}
    for t in p.topics:
        tot = sum(sched.get(t.code, {}).values())
        if tot != t.hours:
            v.append({"constraint": "topic_hours", "topic_code": t.code, "detail": {"planned": t.hours, "scheduled": tot}})
        ws = weeks[t.code]
        if ws:
            gap = [w for w in range(ws[0], ws[-1] + 1) if w not in ws and w not in p.unavailable]
            if gap:
                v.append({"constraint": "contiguity", "topic_code": t.code, "detail": {"missing_weeks": gap}})
            if t.fixed_from is not None and ws[0] < t.fixed_from or t.fixed_to is not None and ws[-1] > t.fixed_to:
                v.append({"constraint": "fixed_window", "topic_code": t.code, "detail": {"weeks": [ws[0], ws[-1]]}})
            if any(w in p.unavailable for w in ws):
                v.append({"constraint": "holidays", "topic_code": t.code, "detail": {}})
    for w in range(n):
        load = sum(sched.get(t.code, {}).get(w, 0) for t in p.topics)
        if load > p.capacity[w]:
            v.append({"constraint": "weekly_load", "topic_code": None, "detail": {"week": w, "load": load, "capacity": p.capacity[w]}})
    pairs = list(p.prerequisites) + ([(a.code, b.code) for a, b in zip(p.topics, p.topics[1:], strict=False)] if p.keep_order else [])
    for a, c in pairs:
        if weeks.get(a) and weeks.get(c) and weeks[a][-1] > weeks[c][0]:
            v.append({"constraint": "prerequisite", "topic_code": c, "detail": {"before": a}})
    return v


def solve(p: CalProblem) -> dict:
    n = len(p.capacity)
    b = _build(p, with_objective=True)
    for v in b.lits.values():
        b.m.Add(v == 1)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = p.time_limit_seconds
    s.parameters.num_workers = 4
    s.parameters.random_seed = 7
    st = _status(s.Solve(b.m))
    res: dict = {"status": st, "method_version": METHOD_VERSION_CALENDAR, "schedule": None, "validation": None, "conflict": None,
                 "solver": {"name": "OR-Tools CP-SAT", "wall_time_seconds": round(s.WallTime(), 4)}}
    if st in ("optimal", "feasible"):
        sched = {t.code: {w: int(s.Value(b.x[t.code, w])) for w in range(n) if s.Value(b.x[t.code, w]) > 0} for t in p.topics}
        viol = validate(p, sched)
        if viol:  # never present an invalid calendar
            res.update(status="invalid", validation={"valid": False, "violations": viol})
            return res
        res.update(schedule=sched, validation={"valid": True, "violations": []})
    elif st == "infeasible":
        res["conflict"] = explain_infeasibility(p)
    return res
