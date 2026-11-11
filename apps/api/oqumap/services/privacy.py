"""Small-cell suppression for learner-based aggregates shown to roles without access to class-level data.

Rules (docs/LEARNING_LOOP.md §Приватность):
* primary: a group with fewer than ``MIN_CELL`` learners is suppressed (value → null, reason ``small_cell``);
* complementary: if exactly one group is suppressed while a total (or a derived figure such as a difference) stays
  visible, the next smallest group is suppressed too (``complementary``) so the hidden value cannot be recovered by
  subtraction. Roles methodist/approver/teacher/admin see unsuppressed values.
"""

from __future__ import annotations

MIN_CELL = 10
DETAIL_ROLES = {"methodist", "approver", "teacher", "admin"}


def can_see_detail(roles) -> bool:
    return bool(set(roles or []) & DETAIL_ROLES)


def suppress_cells(cells: dict[str, int | None], min_n: int = MIN_CELL, total_visible: bool = True) -> dict[str, dict]:
    out = {k: {"value": v, "suppressed": False, "reason": None} for k, v in cells.items()}
    small = [k for k, v in cells.items() if v is not None and 0 < v < min_n]
    for k in small:
        out[k] = {"value": None, "suppressed": True, "reason": "small_cell"}
    if len(small) == 1 and total_visible:
        rest = sorted([k for k, v in cells.items() if k not in small and v], key=lambda k: cells[k])
        if rest:
            out[rest[0]] = {"value": None, "suppressed": True, "reason": "complementary"}
    return out


def filter_outcome_result(result: dict, min_n: int = MIN_CELL) -> dict:
    """Viewer/analyst copy of an outcome: arms with < min_n matched learners are suppressed; because the primary
    estimate (the arm change or the difference between arms) and overall attrition would reveal a suppressed arm, they
    are suppressed as well (complementary). Class rows are removed entirely."""
    r = dict(result)
    r["cohorts"] = None
    r["cohort_detail_visible"] = False
    arms = {k: dict(v) for k, v in (r.get("arms") or {}).items()}
    # totals/differences that would reveal a hidden arm are suppressed below, so other arms can stay visible
    sup = suppress_cells({k: v.get("matched") for k, v in arms.items()}, min_n, total_visible=False)
    hidden = {k: s["reason"] for k, s in sup.items() if s["suppressed"]}
    for k, reason in hidden.items():
        arms[k] = {"suppressed": True, "suppression_reason": reason, "assigned": None, "matched": None, "attrition": None,
                   "baseline_mean": None, "outcome_mean": None,
                   "change": {"mean": None, "ci_low": None, "ci_high": None, "ci_unavailable_reason": "suppressed", "n_clusters": None}}
    r["arms"] = arms
    if hidden:
        r["primary"] = {**(r.get("primary") or {}), "estimate": None, "ci_low": None, "ci_high": None,
                        "ci_unavailable_reason": "suppressed", "suppression_reason": "complementary"}
        r["raw"] = None
        r["adjusted"] = {"estimate": None, "unavailable_reason": "suppressed"}
        r["attrition"] = None
        r["n_matched"] = None
    r["suppression"] = {"min_cell": min_n, "suppressed_arms": hidden, "applied": bool(hidden)}
    return r
