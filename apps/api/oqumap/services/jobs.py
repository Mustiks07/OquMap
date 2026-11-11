"""Persistent background jobs.

States: queued → running → succeeded | failed | cancelled. A job with an idempotency key is created at most
once; retrying a request returns the existing job. In ``inline`` mode the API process runs jobs in a
background thread; in ``worker`` mode ``python -m oqumap.worker`` claims queued jobs from the database.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import session_factory, utcnow
from ..errors import ApiError

log = logging.getLogger("oqumap.jobs")

HANDLERS: dict[str, Callable[[Session, m.Job], dict]] = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(session: Session, org_id: str, kind: str, payload: dict, idempotency_key: str | None = None,
            user_id: str | None = None) -> m.Job:
    if idempotency_key:
        existing = session.scalar(select(m.Job).where(m.Job.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.org_id != org_id:
                raise ApiError("idempotency_conflict", "Ключ идемпотентности уже использован", 409)
            return existing
    job = m.Job(org_id=org_id, kind=kind, payload=payload, idempotency_key=idempotency_key, created_by=user_id)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(m.Job).where(m.Job.idempotency_key == idempotency_key))
        if existing is None:
            raise
        return existing
    if get_settings().job_mode == "inline":
        threading.Thread(target=run_job, args=(job.id, session.get_bind()), daemon=True).start()
    return job


def claim_next(session: Session) -> m.Job | None:
    q = select(m.Job).where(m.Job.status == "queued").order_by(m.Job.created_at).limit(1)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = session.scalar(q)
    if job is None:
        session.rollback()
        return None
    res = session.execute(update(m.Job).where(m.Job.id == job.id, m.Job.status == "queued")
                          .values(status="running", started_at=utcnow(), attempts=m.Job.attempts + 1))
    session.commit()
    if res.rowcount != 1:
        return None
    session.refresh(job)
    return job


def run_job(job_id: str, bind=None) -> None:
    from sqlalchemy.orm import Session as _S

    session = _S(bind=bind, expire_on_commit=False) if bind is not None else session_factory()()
    try:
        res = session.execute(update(m.Job).where(m.Job.id == job_id, m.Job.status == "queued")
                              .values(status="running", started_at=utcnow(), attempts=m.Job.attempts + 1))
        session.commit()
        if res.rowcount != 1:
            return  # already claimed by someone else
        job = session.get(m.Job, job_id)
        execute(session, job)
    finally:
        session.close()


def execute(session: Session, job: m.Job) -> None:
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise ApiError("unknown_job_kind", f"Нет обработчика {job.kind}", 500)
        result = fn(session, job)
        session.refresh(job)
        job.status = "succeeded"
        job.result = result
        job.progress = 1.0
        job.finished_at = utcnow()
        session.commit()
    except Exception as exc:  # noqa: BLE001 - recorded on the job
        session.rollback()
        job = session.get(m.Job, job.id)
        job.status = "failed"
        if isinstance(exc, ApiError):
            job.error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            log.error("job %s failed: %s", job.id, traceback.format_exc(limit=3))
            job.error = {"code": "internal_error", "message": "Внутренняя ошибка обработки", "details": {"type": type(exc).__name__}}
        job.finished_at = utcnow()
        session.commit()


def get_job(session: Session, org_id: str, job_id: str) -> m.Job:
    job = session.scalar(select(m.Job).where(m.Job.id == job_id, m.Job.org_id == org_id))
    if job is None:
        from ..errors import not_found

        raise not_found("job", job_id)
    return job
