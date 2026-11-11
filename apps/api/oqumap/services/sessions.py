"""Planned session calendar of a pilot (only this pilot's sessions; not a school timetable).

* Before activation (draft/ready): generate a draft schedule from the cadence (weekdays, blackout dates/ranges),
  add, edit, delete sessions freely (every change is still logged).
* After activation: sessions are never deleted or silently moved. A session is marked completed / cancelled, or
  rescheduled — the original keeps status ``rescheduled`` and links to a new planned session (a rescheduled session
  is not a missed one).
* A fidelity log for the class and date completes (or cancels) the matching planned session automatically.
* Fidelity compares the logs with the sessions planned up to ``as_of`` (see fidelity.py, expected_source=calendar).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..errors import ApiError, forbidden, not_found
from ..schemas import interventions as S
from . import interventions as ivs
from .auth import Principal
from .common import audit
from .concurrency import conflict_as
from .pilots import get_pilot, pilot_cohorts
from .privacy import can_see_detail

DEFAULT_WEEKDAYS = {1: [0], 2: [1, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4]}
EDITABLE = ("draft", "ready")


def default_weekdays(sessions_per_week: int) -> list[int]:
    return DEFAULT_WEEKDAYS.get(sessions_per_week, [0, 1, 2, 3, 4])


def draft_schedule(start: date, end: date, weekdays: list[int], blackout: set[date]) -> list[date]:
    """Pure: dates between start and end on the given weekdays (0 = Monday), excluding blackout dates."""
    out, d = [], start
    while d <= end:
        if d.weekday() in weekdays and d not in blackout:
            out.append(d)
        d += timedelta(days=1)
    return out


def _event(session: Session, pl: mm.Pilot, s: mm.PilotSession | None, action: str, user_id: str | None, *, from_status=None,
           to_status=None, from_date=None, to_date=None, source: str = "user") -> None:
    session.add(mm.PilotSessionEvent(org_id=pl.org_id, pilot_id=pl.id, session_id=s.id if s else None, action=action,
                                     from_status=from_status, to_status=to_status, from_date=from_date, to_date=to_date,
                                     user_id=user_id, source=source))


def _intervention_cohorts(session: Session, pl: mm.Pilot) -> set[str]:
    return {c.cohort_id for c in pilot_cohorts(session, pl) if c.arm == "intervention"}


def calendar_rows(session: Session, pl: mm.Pilot) -> list[mm.PilotSession]:
    return list(session.scalars(select(mm.PilotSession).where(mm.PilotSession.pilot_id == pl.id, mm.PilotSession.org_id == pl.org_id)
                                .order_by(mm.PilotSession.planned_date, mm.PilotSession.cohort_id)))


def generate(session: Session, p: Principal, pilot_id: str, body: S.SessionGenerate) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status not in EDITABLE:
        raise ApiError("calendar_locked", "Черновое расписание можно строить только до запуска пилота", 409, {"status": pl.status})
    if not pl.start_date or not pl.end_date or pl.end_date < pl.start_date:
        raise ApiError("dates_required", "Для расписания нужны корректные даты начала и окончания", 422)
    blackout = set(body.blackout_dates)
    for r in body.blackout_ranges:
        if r.to < r.from_:
            raise ApiError("validation_error", "Диапазон каникул задан неверно", 422)
        d = r.from_
        while d <= r.to:
            blackout.add(d)
            d += timedelta(days=1)
    weekdays = body.weekdays or default_weekdays(pl.sessions_per_week)
    dates = draft_schedule(pl.start_date, pl.end_date, weekdays, blackout)
    for old in calendar_rows(session, pl):
        _event(session, pl, old, "deleted", p.user_id, from_status=old.status, from_date=old.planned_date)
        session.delete(old)
    session.flush()
    duration = body.duration_minutes or pl.minutes_per_session
    for cid in sorted(_intervention_cohorts(session, pl)):
        for d in dates:
            s = mm.PilotSession(org_id=p.org_id, pilot_id=pl.id, cohort_id=cid, planned_date=d, duration_minutes=duration,
                                status="planned", source="generated", created_by=p.user_id)
            session.add(s)
            session.flush()
            _event(session, pl, s, "generated", p.user_id, to_status="planned", to_date=d)
    audit(session, p.org_id, p.user_id, "pilot.calendar_generate", "pilot", pl.id, n_dates=len(dates), weekdays=weekdays,
          n_blackout=len(blackout))
    session.commit()
    return payload(session, p, pl)


def add(session: Session, p: Principal, pilot_id: str, body: S.SessionCreate) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status in ("completed", "stopped"):
        raise ApiError("calendar_locked", "Пилот завершён: расписание только для чтения", 409)
    _check_cohort_and_date(session, pl, body.cohort_id, body.planned_date)
    s = mm.PilotSession(org_id=p.org_id, pilot_id=pl.id, cohort_id=body.cohort_id, planned_date=body.planned_date,
                        duration_minutes=body.duration_minutes or pl.minutes_per_session, status="planned", source="manual",
                        note=ivs.clean_text(body.note, 300), created_by=p.user_id)
    session.add(s)
    with conflict_as(session, "session_exists", "На эту дату у класса уже есть занятие"):
        session.flush()
    _event(session, pl, s, "added", p.user_id, to_status="planned", to_date=s.planned_date)
    session.commit()
    return payload(session, p, pl)


def _check_cohort_and_date(session: Session, pl: mm.Pilot, cohort_id: str, d: date) -> None:
    if cohort_id not in _intervention_cohorts(session, pl):
        raise ApiError("cohort_not_in_pilot", "Класс не получает интервенцию в этом пилоте", 422)
    if (pl.start_date and d < pl.start_date) or (pl.end_date and d > pl.end_date):
        raise ApiError("date_outside_pilot", "Дата вне периода пилота", 422)


def _get(session: Session, pl: mm.Pilot, session_id: str) -> mm.PilotSession:
    s = session.scalar(select(mm.PilotSession).where(mm.PilotSession.id == session_id, mm.PilotSession.pilot_id == pl.id))
    if s is None:
        raise not_found("pilot_session", session_id)
    return s


def update(session: Session, p: Principal, pilot_id: str, session_id: str, body: S.SessionPatch) -> dict:
    p.require("methodist", "teacher")
    pl = get_pilot(session, p.org_id, pilot_id)
    s = _get(session, pl, session_id)
    if pl.status in EDITABLE:
        # free editing of the draft calendar (logged)
        if body.planned_date is not None and body.planned_date != s.planned_date:
            _check_cohort_and_date(session, pl, s.cohort_id, body.planned_date)
            _event(session, pl, s, "edited", p.user_id, from_date=s.planned_date, to_date=body.planned_date)
            s.planned_date = body.planned_date
        if body.duration_minutes is not None:
            s.duration_minutes = body.duration_minutes
        if body.status is not None and body.status != s.status:
            if body.status == "rescheduled":
                raise ApiError("validation_error", "До запуска дату меняют напрямую, перенос не нужен", 422)
            _event(session, pl, s, "status", p.user_id, from_status=s.status, to_status=body.status)
            s.status = body.status
        with conflict_as(session, "session_exists", "На эту дату у класса уже есть занятие"):
            session.commit()
        return payload(session, p, pl)
    if pl.status == "stopped":
        raise ApiError("calendar_locked", "Пилот остановлен: расписание только для чтения", 409)
    if body.duration_minutes is not None and body.duration_minutes != s.duration_minutes:
        raise ApiError("calendar_locked", "После запуска плановая длительность не меняется", 409)
    if s.status in ("rescheduled",):
        raise ApiError("invalid_state", "Занятие уже перенесено; работайте с новым занятием", 409)
    if body.planned_date is not None and body.planned_date != s.planned_date:
        if pl.status == "completed":
            raise ApiError("calendar_locked", "Пилот завершён: перенос невозможен", 409)
        if s.status != "planned":
            raise ApiError("invalid_state", "Переносить можно только запланированное занятие", 409)
        _check_cohort_and_date(session, pl, s.cohort_id, body.planned_date)
        new = mm.PilotSession(org_id=p.org_id, pilot_id=pl.id, cohort_id=s.cohort_id, planned_date=body.planned_date,
                              duration_minutes=s.duration_minutes, status="planned", source="reschedule",
                              note=ivs.clean_text(body.note or "", 300), created_by=p.user_id)
        session.add(new)
        with conflict_as(session, "session_exists", "На эту дату у класса уже есть занятие"):
            session.flush()
        s.rescheduled_to_id, s.status = new.id, "rescheduled"
        _event(session, pl, s, "rescheduled", p.user_id, from_status="planned", to_status="rescheduled",
               from_date=s.planned_date, to_date=new.planned_date)
        _event(session, pl, new, "added", p.user_id, to_status="planned", to_date=new.planned_date)
    elif body.status is not None and body.status != s.status:
        if body.status not in ("completed", "cancelled", "planned"):
            raise ApiError("validation_error", "Для переноса укажите новую дату", 422)
        _event(session, pl, s, "status", p.user_id, from_status=s.status, to_status=body.status)
        s.status = body.status
    audit(session, p.org_id, p.user_id, "pilot.calendar_update", "pilot", pl.id, session_id=s.id)
    session.commit()
    return payload(session, p, pl)


def delete(session: Session, p: Principal, pilot_id: str, session_id: str) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status not in EDITABLE:
        raise ApiError("calendar_locked", "После запуска занятия не удаляются: отмените или перенесите", 409)
    s = _get(session, pl, session_id)
    _event(session, pl, s, "deleted", p.user_id, from_status=s.status, from_date=s.planned_date)
    session.delete(s)
    session.commit()
    return payload(session, p, pl)


def on_fidelity_log(session: Session, pl: mm.Pilot, cohort_id: str, d: date, cancelled: bool, user_id: str | None) -> None:
    """Called when a fidelity log is added: the matching planned session becomes completed/cancelled."""
    s = session.scalar(select(mm.PilotSession).where(mm.PilotSession.pilot_id == pl.id, mm.PilotSession.cohort_id == cohort_id,
                                                     mm.PilotSession.planned_date == d, mm.PilotSession.status == "planned"))
    if s is not None:
        new = "cancelled" if cancelled else "completed"
        _event(session, pl, s, "status", user_id, from_status=s.status, to_status=new, source="fidelity_log")
        s.status = new


def planned_by_cohort(session: Session, pl: mm.Pilot) -> dict[str, list[tuple[date, int, str]]] | None:
    rows = calendar_rows(session, pl)
    if not rows:
        return None
    out: dict[str, list[tuple[date, int, str]]] = {}
    for r in rows:
        out.setdefault(r.cohort_id, []).append((r.planned_date, r.duration_minutes, r.status))
    return out


def payload(session: Session, p: Principal, pl: mm.Pilot) -> dict:
    if not can_see_detail(p.user.roles):
        raise forbidden(details={"required_roles": ["methodist", "approver", "teacher"]})
    rows = calendar_rows(session, pl)
    codes = {c.id: c.code for c in session.scalars(select(m.Cohort).where(m.Cohort.id.in_([r.cohort_id for r in rows] or [""])))}
    events = list(session.scalars(select(mm.PilotSessionEvent).where(mm.PilotSessionEvent.pilot_id == pl.id)
                                  .order_by(mm.PilotSessionEvent.created_at.desc()).limit(200)))
    users = ivs._users(session, [e.user_id for e in events])
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "pilot_id": pl.id, "pilot_status": pl.status, "editable": pl.status in EDITABLE,
        "default_weekdays": default_weekdays(pl.sessions_per_week), "counts": counts,
        "sessions": [{"id": r.id, "cohort_id": r.cohort_id, "cohort_code": codes.get(r.cohort_id), "planned_date": r.planned_date.isoformat(),
                      "duration_minutes": r.duration_minutes, "status": r.status, "rescheduled_to_id": r.rescheduled_to_id,
                      "source": r.source, "note": r.note} for r in rows],
        "events": [{"action": e.action, "session_id": e.session_id, "from_status": e.from_status, "to_status": e.to_status,
                    "from_date": e.from_date.isoformat() if e.from_date else None, "to_date": e.to_date.isoformat() if e.to_date else None,
                    "by": users.get(e.user_id), "source": e.source, "at": e.created_at.isoformat()} for e in events],
    }


def get_calendar(session: Session, p: Principal, pilot_id: str) -> dict:
    return payload(session, p, get_pilot(session, p.org_id, pilot_id))
