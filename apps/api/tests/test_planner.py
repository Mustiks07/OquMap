import itertools

from oqumap.analytics.planner import PlanProblem, TopicConstraint, _feasible_with, solve, validate_plan


def fixture_problem(**over):
    topics = [
        TopicConstraint("t1", "R", 4, priority=0.2, min_hours=3),
        TopicConstraint("t2", "TARGET", 8, priority=1.0, min_hours=8, max_hours=10),
        TopicConstraint("t3", "CONS", 4, priority=0.2, min_hours=3),
        TopicConstraint("t4", "CHECK", 4, priority=0.5, min_hours=4),
    ]
    p = PlanProblem(topics=topics, budget=20, **over)
    return p


def test_brief_example_is_feasible_by_independent_validator():
    p = fixture_problem()
    assert validate_plan(p, {"t1": 3, "t2": 10, "t3": 3, "t4": 4}) == []
    assert validate_plan(p, {"t1": 4, "t2": 8, "t3": 4, "t4": 4}) == []


def test_solver_output_satisfies_all_constraints_independently():
    p = fixture_problem()
    res = solve(p)
    assert res["status"] in ("optimal", "feasible")
    assert validate_plan(p, res["hours"]) == []
    assert sum(res["hours"].values()) == 20
    assert res["objective"]["is_forecast"] is False


def test_solver_is_optimal_against_bruteforce():
    p = fixture_problem(change_penalty=0.1)
    res = solve(p)
    from oqumap.analytics.planner import objective_value

    best = None
    for combo in itertools.product(range(0, 21), repeat=4):
        h = dict(zip(["t1", "t2", "t3", "t4"], combo, strict=True))
        if validate_plan(p, h):
            continue
        v = objective_value(p, h)
        best = v if best is None or v > best else best
    assert res["status"] == "optimal"
    assert abs(res["objective_value"] - best) < 1e-2


def test_conflict_fix_all_and_add_two_without_reserve():
    p = fixture_problem()
    for t in p.topics:
        if t.code != "TARGET":
            t.fixed = True
    p.topics[1].min_hours = 10  # require +2 hours for the target topic
    res = solve(p)
    assert res["status"] == "infeasible"
    assert res["hours"] is None
    conflict = res["conflict"]
    assert conflict["verified"] is True
    keys = [c["key"] for c in conflict["constraints"]]
    assert "budget" in keys and "min:TARGET" in keys
    # independent re-check: the set is infeasible and each element is necessary
    assert _feasible_with(p, keys, 2.0) == "infeasible"
    for i in range(len(keys)):
        assert _feasible_with(p, keys[:i] + keys[i + 1 :], 2.0) == "feasible"
    assert conflict["arithmetic"]["sum_lower_bounds"] > conflict["arithmetic"]["budget"]


def test_elapsed_hours_cannot_be_removed():
    p = fixture_problem()
    p.topics[0].elapsed_hours = 4  # four hours of topic R already taught
    res = solve(p)
    assert res["hours"]["t1"] >= 4
    assert validate_plan(p, {"t1": 3, "t2": 10, "t3": 3, "t4": 4})[0].constraint == "elapsed_hours"


def test_timeout_never_reports_optimal_and_unknown_is_not_infeasible(monkeypatch):
    from ortools.sat.python import cp_model

    import oqumap.analytics.planner as planner

    class FakeSolver(cp_model.CpSolver):
        def Solve(self, model, *a, **k):  # noqa: N802
            super().Solve(model, *a, **k)
            return cp_model.UNKNOWN

    monkeypatch.setattr(planner.cp_model, "CpSolver", FakeSolver)
    res = planner.solve(fixture_problem())
    assert res["status"] == "unknown"
    assert res["hours"] is None and res["conflict"] is None


def test_feasible_status_is_kept_when_solver_stops_early(monkeypatch):
    from ortools.sat.python import cp_model

    import oqumap.analytics.planner as planner

    real = cp_model.CpSolver

    class EarlyStop(real):
        def Solve(self, model, *a, **k):  # noqa: N802
            st = super().Solve(model, *a, **k)
            return cp_model.FEASIBLE if st == cp_model.OPTIMAL else st

    monkeypatch.setattr(planner.cp_model, "CpSolver", EarlyStop)
    res = planner.solve(fixture_problem())
    assert res["status"] == "feasible"
    assert validate_plan(fixture_problem(), res["hours"]) == []


def test_invalid_input_is_reported():
    p = fixture_problem()
    p.diminishing_rate = 1.5
    assert solve(p)["status"] == "invalid"
