"""Implementation fidelity: append-only session logs and transparent aggregation (rule set ``fidelity-v1``).

Aggregates per intervention cohort and overall:
* expected sessions = planned sessions (sessions/week × weeks) × elapsed share of the pilot period at ``as_of``;
* dosage completion = Σ delivered minutes / (expected sessions × planned minutes per session) — a missing log
  counts as 0 delivered (conservative), which is why low log coverage yields ``unknown`` rather than ``low``;
* session completion = delivered (non-cancelled) sessions / expected sessions;
* reach = Σ present / Σ assigned over delivered sessions that report both;
* adherence = (checklist items done + activities completed) / (checklist items + activities planned);
* classification: unknown (nothing expected yet or log coverage < 50%) → low (dosage, sessions or adherence
  < 50%) → high (all available metrics ≥ 80%) → otherwise moderate.

Low or unknown fidelity never turns a follow-up into "the intervention does not work" (see learning_loop.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..errors import ApiError, not_found
from ..schemas import interventions as S
from . import clock
from . import interventions as ivs
from .auth import Principal
from .common import audit
from .concurrency import conflict_as
from .measurement_messages import FIDELITY_LABELS, label, render
from .pilots import get_pilot, pilot_cohorts

METHOD_VERSION_FIDELITY = "fidelity-v1"
RULES = {"min_log_coverage": 0.5, "low_below": 0.5, "high_at_least": 0.8, "overall_downgrade_share": 1 / 3}
DETAIL_ROLES = {"methodist", "approver", "teacher", "admin"}


@dataclass
class LogRow:
    cohort_id: str
    session_date: date
    planned_minutes: int
    delivered_minutes: int
    activities_planned: int
    activities_completed: int
    learners_present: int | None
    learners_assigned: int | None
    adherence: list
    disruption: str


def expected_sessions(total_sessions: int, start: date | None, end: date | None, as_of: date) -> int:
    if not start or not end or as_of < start:
        return 0
    span = (end - start).days + 1
    elapsed = min((as_of - start).days + 1, span)
    return int(round(total_sessions * elapsed / span))


def _ratio(num: float, den: float) -> float | None:
    return min(1.0, num / den) if den else None


def classify(metrics: dict) -> tuple[str, list[str]]:
    reasons = []
    if not metrics["expected_sessions"]:
        return "unknown", ["no_sessions_expected_yet"]
    cov = metrics["log_coverage"] or 0
    if cov < RULES["min_log_coverage"]:
        return "unknown", ["log_coverage_below_50pct"]
    core = {"dosage_completion": metrics["dosage_completion"], "session_completion": metrics["session_completion"],
            "adherence": metrics["adherence"]}
    lows = [k for k, v in core.items() if v is not None and v < RULES["low_below"]]
    if lows:
        return "low", [f"{k}_below_50pct" for k in lows]
    checks = {**core, "reach": metrics["reach"], "log_coverage": metrics["log_coverage"]}
    below_high = [k for k, v in checks.items() if v is not None and v < RULES["high_at_least"]]
    if not below_high:
        return "high", ["all_metrics_at_least_80pct"]
    reasons += [f"{k}_below_80pct" for k in below_high]
    return "moderate", reasons


def aggregate_logs(logs: list[LogRow], expected: int, minutes_per_session: int) -> dict:
    delivered = [x for x in logs if x.disruption != "cancelled" and x.delivered_minutes > 0]
    cancelled = len(logs) - len(delivered)
    pres = [(x.learners_present, x.learners_assigned) for x in delivered
            if x.learners_present is not None and x.learners_assigned]
    adh_done = sum(sum(1 for a in x.adherence if a.get("done")) + x.activities_completed for x in delivered)
    adh_total = sum(len(x.adherence) + x.activities_planned for x in delivered)
    metrics = {
        "expected_sessions": expected,
        "logged_sessions": len(logs),
        "delivered_sessions": len(delivered),
        "cancelled_sessions": cancelled,
        "missing_logs": max(0, expected - len(logs)),
        "log_coverage": _ratio(len(logs), expected),
        "dosage_completion": _ratio(sum(x.delivered_minutes for x in logs), expected * minutes_per_session),
        "session_completion": _ratio(len(delivered), expected),
        "reach": (sum(p for p, _ in pres) / sum(a for _, a in pres)) if pres else None,
        "adherence": (adh_done / adh_total) if adh_total else None,
    }
    cls, reasons = classify(metrics)
    metrics["classification"] = label(FIDELITY_LABELS, cls)
    metrics["reasons"] = reasons
    return metrics


def compute(cohort_ids: list[str], logs: list[LogRow], total_sessions: int, minutes_per_session: int,
            start: date | None, end: date | None, as_of: date) -> dict:
    """Pure aggregation over intervention cohorts. Returns per-cohort metrics, pooled overall metrics and the
    distribution of cohort classifications."""
    exp = expected_sessions(total_sessions, start, end, as_of)
    eff = [x for x in logs if x.session_date <= as_of]
    per = {c: aggregate_logs([x for x in eff if x.cohort_id == c], exp, minutes_per_session) for c in cohort_ids}
    overall = aggregate_logs([x for x in eff if x.cohort_id in set(cohort_ids)], exp * len(cohort_ids), minutes_per_session)
    dist = {k: 0 for k in FIDELITY_LABELS}
    for v in per.values():
        dist[v["classification"]["code"]] += 1
    weak = dist["low"] + dist["unknown"]
    if cohort_ids and overall["classification"]["code"] == "high" and weak / len(cohort_ids) >= RULES["overall_downgrade_share"]:
        overall["classification"] = label(FIDELITY_LABELS, "moderate")
        overall["reasons"] = overall["reasons"] + ["third_of_cohorts_low_or_unknown"]
    return {"per_cohort": per, "overall": overall, "distribution": dist, "expected_per_cohort": exp}


def effective_logs(session: Session, pl: mm.Pilot) -> list[mm.FidelityLog]:
    rows = list(session.scalars(select(mm.FidelityLog).where(mm.FidelityLog.pilot_id == pl.id, mm.FidelityLog.org_id == pl.org_id)
                                .order_by(mm.FidelityLog.session_date, mm.FidelityLog.created_at)))
    superseded = {r.corrects_log_id for r in rows if r.corrects_log_id}
    return [r for r in rows if r.id not in superseded]


def default_as_of(pl: mm.Pilot) -> date:
    t = clock.today()
    if pl.end_date and (pl.status in ("completed",) or t > pl.end_date):
        return pl.end_date
    return t


def resolve_as_of(pl: mm.Pilot | None, as_of: date | None) -> date:
    """Effective analysis date: explicit ``as_of`` (never in the future — a future date would present unobserved
    sessions/measurements as if they had happened) or the pilot default (end of a completed pilot, else today)."""
    if as_of is not None and as_of > clock.today():
        raise ApiError("as_of_in_future", "Дата расчёта не может быть в будущем", 422,
                       {"as_of": as_of.isoformat(), "today": clock.today().isoformat()})
    if as_of is not None:
        return as_of
    return default_as_of(pl) if pl is not None else clock.today()


def fidelity_for(session: Session, pl: mm.Pilot, as_of: date | None = None) -> dict:
    as_of = as_of or default_as_of(pl)
    inter = [c.cohort_id for c in pilot_cohorts(session, pl) if c.arm == "intervention"]
    logs = [LogRow(r.cohort_id, r.session_date, r.planned_minutes, r.delivered_minutes, r.activities_planned,
                   r.activities_completed, r.learners_present, r.learners_assigned, r.adherence or [], r.disruption)
            for r in effective_logs(session, pl)]
    res = compute(inter, logs, pl.sessions_per_week * pl.duration_weeks, pl.minutes_per_session, pl.start_date, pl.end_date, as_of)
    res["as_of"] = as_of
    return res


def logs_fingerprint(session: Session, pl: mm.Pilot) -> list[str]:
    return [r.id for r in effective_logs(session, pl)]


def correction_exists(session: Session, log_id: str) -> bool:
    return session.scalar(select(mm.FidelityLog.id).where(mm.FidelityLog.corrects_log_id == log_id)) is not None


def add_log(session: Session, p: Principal, pilot_id: str, body: S.FidelityLogCreate) -> dict:
    p.require("methodist", "teacher")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status not in ("active", "completed"):
        raise ApiError("pilot_not_running", "Журнал ведётся только для активного или завершённого пилота", 409, {"status": pl.status})
    inter = {c.cohort_id for c in pilot_cohorts(session, pl) if c.arm == "intervention"}
    if body.cohort_id not in inter:
        raise ApiError("cohort_not_in_pilot", "Класс не получает интервенцию в этом пилоте", 422, {"cohort_id": body.cohort_id})
    if (pl.start_date and body.session_date < pl.start_date) or (pl.end_date and body.session_date > pl.end_date):
        raise ApiError("date_outside_pilot", "Дата вне периода пилота", 422)
    if body.session_date > clock.today():
        raise ApiError("date_in_future", "Нельзя записать занятие, которое ещё не прошло", 422)
    if body.learners_present is not None and body.learners_assigned is not None and body.learners_present > body.learners_assigned:
        raise ApiError("validation_error", "Присутствовало больше, чем назначено", 422, {"field": "learners_present"})
    if body.activities_completed > body.activities_planned and body.activities_planned:
        raise ApiError("validation_error", "Выполнено больше активностей, чем запланировано", 422, {"field": "activities_completed"})
    if body.disruption == "cancelled" and body.delivered_minutes:
        raise ApiError("validation_error", "Отменённое занятие не может иметь проведённых минут", 422, {"field": "delivered_minutes"})
    if body.corrects_log_id:
        old = session.scalar(select(mm.FidelityLog).where(mm.FidelityLog.id == body.corrects_log_id, mm.FidelityLog.pilot_id == pl.id))
        if old is None:
            raise not_found("fidelity_log", body.corrects_log_id)
        if correction_exists(session, old.id):
            raise ApiError("already_corrected", "Эта запись уже исправлена; исправляйте последнюю версию", 409)
    log = mm.FidelityLog(
        org_id=p.org_id, pilot_id=pl.id, cohort_id=body.cohort_id, session_date=body.session_date,
        planned_minutes=body.planned_minutes, delivered_minutes=body.delivered_minutes,
        activities_planned=body.activities_planned, activities_completed=body.activities_completed,
        completed_tasks=[ivs.clean_text(t, 200) for t in body.completed_tasks if ivs.clean_text(t, 200)],
        learners_present=body.learners_present, learners_assigned=body.learners_assigned,
        adherence=[{"key": ivs.clean_text(a.key, 60), "label": ivs.clean_text(a.label, 300), "done": a.done} for a in body.adherence],
        adaptation_note=ivs.clean_text(body.adaptation_note, 2000), disruption=body.disruption,
        disruption_note=ivs.clean_text(body.disruption_note, 1000), source=body.source, recorder_id=p.user_id,
        corrects_log_id=body.corrects_log_id)
    session.add(log)
    with conflict_as(session, "already_corrected", "Эта запись уже исправлена; исправляйте последнюю версию"):
        session.flush()  # unique(corrects_log_id) closes the race between two simultaneous corrections
    # audit without free-text notes (may contain personal data)
    audit(session, p.org_id, p.user_id, "fidelity.log", "pilot", pl.id, log_id=log.id, corrects=body.corrects_log_id,
          disruption=body.disruption)
    session.commit()
    return log_payload(session, log)


def log_payload(session: Session, r: mm.FidelityLog, users: dict | None = None, superseded_by: str | None = None) -> dict:
    users = users if users is not None else ivs._users(session, [r.recorder_id])
    co = session.get(m.Cohort, r.cohort_id)
    return {"id": r.id, "pilot_id": r.pilot_id, "cohort_id": r.cohort_id, "cohort_code": co.code if co else None,
            "session_date": r.session_date.isoformat(), "planned_minutes": r.planned_minutes,
            "delivered_minutes": r.delivered_minutes, "activities_planned": r.activities_planned,
            "activities_completed": r.activities_completed, "completed_tasks": r.completed_tasks or [],
            "learners_present": r.learners_present, "learners_assigned": r.learners_assigned, "adherence": r.adherence or [],
            "adaptation_note": r.adaptation_note, "disruption": r.disruption, "disruption_note": r.disruption_note,
            "source": r.source, "recorder": users.get(r.recorder_id), "corrects_log_id": r.corrects_log_id,
            "superseded_by": superseded_by, "created_at": r.created_at.isoformat()}


def fidelity_payload(session: Session, p: Principal, pilot_id: str, as_of: date | None = None) -> dict:
    pl = get_pilot(session, p.org_id, pilot_id)
    res = fidelity_for(session, pl, resolve_as_of(pl, as_of))
    detail = bool(set(p.user.roles or []) & DETAIL_ROLES)
    cohorts = None
    logs = None
    if detail:
        codes = {c.cohort_id: session.get(m.Cohort, c.cohort_id).code for c in pilot_cohorts(session, pl)}
        cohorts = [{"cohort_id": c, "code": codes.get(c), "metrics": mtr} for c, mtr in res["per_cohort"].items()]
        cohorts.sort(key=lambda r: r["code"] or "")
        rows = list(session.scalars(select(mm.FidelityLog).where(mm.FidelityLog.pilot_id == pl.id)
                                    .order_by(mm.FidelityLog.session_date.desc(), mm.FidelityLog.created_at.desc())))
        users = ivs._users(session, [r.recorder_id for r in rows])
        sup = {r.corrects_log_id: r.id for r in rows if r.corrects_log_id}
        logs = [log_payload(session, r, users, sup.get(r.id)) for r in rows]
    limitations = [render("fidelity_unknown", {}, "warn")] if res["overall"]["classification"]["code"] == "unknown" else []
    if not detail:
        limitations.append({"code": "cohort_detail_hidden", "severity": "info", "params": {},
                            "message_ru": "Данные по отдельным классам и журналы доступны методисту/утверждающему.",
                            "message_kz": "Жеке сыныптар бойынша деректер әдіскерге/бекітушіге қолжетімді."})
    return {"pilot_id": pl.id, "method_version": METHOD_VERSION_FIDELITY, "as_of": res["as_of"].isoformat(),
            "rule_set": RULES | {"expected_per_cohort": res["expected_per_cohort"],
                                 "planned_minutes_per_session": pl.minutes_per_session,
                                 "planned_total_sessions": pl.sessions_per_week * pl.duration_weeks},
            "overall": res["overall"], "distribution": res["distribution"], "cohorts": cohorts,
            "cohort_detail_visible": detail, "logs": logs, "limitations": limitations}
