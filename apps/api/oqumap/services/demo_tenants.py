"""Disposable public-demo tenants.

``public_demo`` mode: every one-click demo visitor gets an own organisation cloned from the seeded demo template
(recommended dataset + illustration; laboratory scenarios are cloned on request). The visitor works as a
methodist inside that tenant only; the tenant expires after ``demo_tenant_ttl_hours`` and is deleted by
``oqumap.maintenance`` (also run periodically by the worker). Live AI is never used for demo tenants.

Cloning copies rows table by table. New ids are ``uuid5(destination org, source id)``, so any later clone into
the same tenant maps references identically without keeping a mapping table. Shared demo source files (PDF/DOCX
and committed import files) are referenced, not copied; cleanup deletes only files under the tenant's own folders.
"""

from __future__ import annotations

import secrets
import shutil
import uuid
from datetime import timedelta

from sqlalchemy import Table, delete, func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import Base, utcnow
from ..errors import ApiError, not_found
from . import ratelimit
from .auth import issue_token
from .common import audit

RECOMMENDED_DATASET = "base"
INITIAL_DATASETS = ["base", "illustration"]
LAB_DATASETS = ["no_difference", "few_clusters", "unlinked_forms", "confounded", "illustration"]
CHUNK = 4000


def _template_org_id() -> str:
    from ..demo.seed import DEMO_ORG_ID

    return DEMO_ORG_ID


def _new_id(dst_org: str, old: str) -> str:
    return str(uuid.uuid5(uuid.UUID(dst_org), old))


def _t(name: str) -> Table:
    return Base.metadata.tables[name]


class _Cloner:
    def __init__(self, session: Session, src_org: str, dst_org: str):
        self.s = session
        self.src = src_org
        self.dst = dst_org
        self.ids: set[str] = set()  # source ids that are remapped
        self.inserted = 0

    def _rows(self, table: str, where) -> list[dict]:
        t = _t(table)
        return [dict(r._mapping) for r in self.s.execute(select(t).where(where))]

    def register(self, table: str, where) -> list[dict]:
        rows = self._rows(table, where)
        self.ids.update(r["id"] for r in rows if "id" in r)
        return rows

    def remap(self, row: dict) -> dict:
        out = {}
        for k, v in row.items():
            if k == "org_id" and v == self.src:
                out[k] = self.dst
            elif isinstance(v, str) and v in self.ids:
                out[k] = _new_id(self.dst, v)
            else:
                out[k] = v
        return out

    def insert(self, table: str, rows: list[dict]) -> None:
        t = _t(table)
        for i in range(0, len(rows), CHUNK):
            chunk = [self.remap(r) for r in rows[i:i + CHUNK]]
            if chunk:
                self.s.execute(t.insert(), chunk)
                self.inserted += len(chunk)


def _ids(rows: list[dict]) -> list[str]:
    return [r["id"] for r in rows]


def clone_into(session: Session, dst_org: str, dataset_codes: list[str], src_org: str | None = None) -> dict:
    """Clone the template programme/materials (once) and the given datasets into ``dst_org``."""
    src = src_org or _template_org_id()
    c = _Cloner(session, src, dst_org)
    T = lambda n: _t(n).c  # noqa: E731

    programs = c.register("program_versions", T("program_versions").org_id == src)
    pids = _ids(programs)
    topics = c.register("topics", T("topics").program_version_id.in_(pids))
    objectives = c.register("objectives", T("objectives").program_version_id.in_(pids))
    oids = _ids(objectives)
    relations = c.register("objective_relations", T("objective_relations").source_objective_id.in_(oids))
    scales = c.register("scales", T("scales").org_id == src)
    items = c.register("items", T("items").program_version_id.in_(pids))
    item_links = c.register("item_objectives", T("item_objectives").org_id == src)
    forms = c.register("assessment_forms", T("assessment_forms").program_version_id.in_(pids))
    form_items = c.register("form_items", T("form_items").form_id.in_(_ids(forms)))
    editions = c.register("editions", T("editions").org_id == src)
    docs = c.register("documents", T("documents").org_id == src)
    frags = c.register("fragments", T("fragments").org_id == src)
    gens = c.register("ai_generations", T("ai_generations").org_id == src)
    frag_links = c.register("fragment_objectives", T("fragment_objectives").org_id == src)

    base_present = session.scalar(select(func.count()).select_from(_t("program_versions"))
                                  .where(T("program_versions").org_id == dst_org)) > 0
    if not base_present:
        for name, rows in [("program_versions", programs), ("topics", topics), ("objectives", objectives),
                           ("objective_relations", relations), ("scales", scales), ("items", items),
                           ("item_objectives", item_links), ("assessment_forms", forms), ("form_items", form_items),
                           ("documents", docs), ("editions", editions), ("fragments", frags),
                           ("ai_generations", gens), ("fragment_objectives", frag_links)]:
            c.insert(name, rows)

    src_datasets = c._rows("datasets", (T("datasets").org_id == src) & T("datasets").code.in_(dataset_codes))
    existing = set(session.scalars(select(m.Dataset.code).where(m.Dataset.org_id == dst_org)))
    src_datasets = [d for d in src_datasets if d["code"] not in existing]
    cloned = []
    for ds in src_datasets:
        did = ds["id"]
        c.ids.add(did)
        per = {}
        for name in ("dataset_versions", "schools", "teachers", "cohorts", "learners", "material_exposures",
                     "assessments", "sittings", "responses", "grade_records", "import_batches", "teaching_plans"):
            per[name] = c.register(name, T(name).dataset_id == did)
        per["plan_topic_hours"] = c.register("plan_topic_hours", T("plan_topic_hours").plan_id.in_(_ids(per["teaching_plans"])))
        for b in per["import_batches"]:  # keep provenance, do not re-commit
            c.ids.add(b["id"])
        for tp in per["teaching_plans"]:
            c.ids.add(tp["plan_group_id"])
        c.insert("datasets", [ds])
        for name in ("dataset_versions", "schools", "teachers", "cohorts", "learners", "material_exposures",
                     "assessments", "sittings", "responses", "grade_records", "import_batches", "teaching_plans",
                     "plan_topic_hours"):
            c.insert(name, per[name])
        cloned.append(ds["code"])
    session.flush()
    return {"datasets": cloned, "rows": c.inserted}


def create_demo_tenant(session: Session, client_ip: str) -> tuple[str, m.User, m.Organization, str | None]:
    s = get_settings()
    ratelimit.hit(session, "demo_tenant_ip", client_ip, s.demo_tenants_per_ip_per_hour, 3600)
    active = session.scalar(select(func.count()).select_from(m.Organization).where(
        m.Organization.is_ephemeral.is_(True), m.Organization.expires_at > utcnow()))
    if active >= s.demo_max_active_tenants:
        raise ApiError("demo_capacity", "Демо временно перегружено: слишком много одновременных сессий. Попробуйте позже.", 503)
    if session.get(m.Organization, _template_org_id()) is None:
        raise ApiError("demo_not_seeded", "Демо-шаблон не загружен. Выполните seed.", 503)
    org = m.Organization(name=f"Демо-сессия {secrets.token_hex(3)}", is_demo=True, is_ephemeral=True,
                         expires_at=utcnow() + timedelta(hours=s.demo_tenant_ttl_hours),
                         storage_quota_bytes=s.demo_storage_quota_mb * 1024 * 1024)
    session.add(org)
    session.flush()
    user = m.User(org_id=org.id, username=f"demo-{org.id[:12]}", display_name="Методист (демо-сессия)",
                  roles=["methodist", "approver", "teacher"], is_demo=True)
    session.add(user)
    session.flush()
    res = clone_into(session, org.id, INITIAL_DATASETS)
    audit(session, org.id, user.id, "demo.tenant_created", "organization", org.id, rows=res["rows"])
    session.commit()
    # The measurement & learning-loop demo (interventions, pilots, fidelity, outcomes, conclusions) is built natively
    # in the tenant by its own seed — not cloned row by row, because snapshots and content hashes must stay
    # consistent. It takes a few seconds, so it runs as a background job; the visitor is not kept waiting.
    mode = s.demo_tenant_measurement
    if mode == "sync":
        from ..demo.measurement_seed import seed_measurement

        seed_measurement(session, org.id, user.id)
    elif mode == "background":
        from . import jobs

        jobs.enqueue(session, org.id, "demo_measurement", {"user_id": user.id}, idempotency_key=f"demo_measurement:{org.id}",
                     user_id=user.id)
    rec = session.scalar(select(m.Dataset.id).where(m.Dataset.org_id == org.id, m.Dataset.code == RECOMMENDED_DATASET))
    token = issue_token(session, user, expires_at=org.expires_at)
    return token, user, org, rec


def load_lab_dataset(session: Session, org: m.Organization, code: str) -> str:
    if code not in LAB_DATASETS:
        raise not_found("scenario", code)
    if not org.is_demo:
        raise ApiError("not_demo", "Лабораторные сценарии доступны только в демо", 403)
    if org.id == _template_org_id():
        ds = session.scalar(select(m.Dataset.id).where(m.Dataset.org_id == org.id, m.Dataset.code == code))
        if ds is None:
            raise not_found("scenario", code)
        return ds
    clone_into(session, org.id, [code])
    session.commit()
    return session.scalar(select(m.Dataset.id).where(m.Dataset.org_id == org.id, m.Dataset.code == code))


def measurement_readiness(session: Session, org_id: str) -> dict:
    """Observable state of the asynchronously prepared measurement demo for one tenant."""
    from ..demo.measurement_seed import DATASET_CODE

    dataset_id = session.scalar(select(m.Dataset.id).where(m.Dataset.org_id == org_id, m.Dataset.code == DATASET_CODE))
    if dataset_id is not None:
        return {"status": "ready", "dataset_id": dataset_id, "job_status": "succeeded", "error": None}
    job = session.scalar(select(m.Job).where(m.Job.org_id == org_id, m.Job.kind == "demo_measurement")
                         .order_by(m.Job.created_at.desc()))
    if job is None:
        return {"status": "unavailable", "dataset_id": None, "job_status": None, "error": None}
    status = "failed" if job.status in {"failed", "cancelled"} else "preparing"
    return {"status": status, "dataset_id": None, "job_status": job.status,
            "error": job.error if status == "failed" else None}


def retry_measurement(session: Session, org: m.Organization, user_id: str) -> dict:
    """Retry only a failed disposable-demo seed; an active or completed job stays idempotent."""
    if not org.is_demo or not org.is_ephemeral:
        raise ApiError("not_disposable_demo", "Подготовка доступна только в одноразовой демо-сессии", 403)
    current = measurement_readiness(session, org.id)
    if current["status"] == "ready":
        return current
    job = session.scalar(select(m.Job).where(m.Job.org_id == org.id, m.Job.kind == "demo_measurement")
                         .order_by(m.Job.created_at.desc()))
    if job is None:
        from . import jobs

        jobs.enqueue(session, org.id, "demo_measurement", {"user_id": user_id},
                     idempotency_key=f"demo_measurement:{org.id}", user_id=user_id)
    elif job.status in {"failed", "cancelled"}:
        job.status = "queued"
        job.error = None
        job.result = None
        job.progress = 0.0
        job.started_at = None
        job.finished_at = None
        session.commit()
    return measurement_readiness(session, org.id)


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_org_data(session: Session, org_id: str) -> int:
    """Delete every row of an organisation (children first)."""
    T = lambda n: _t(n).c  # noqa: E731
    n = 0
    pids = list(session.scalars(select(m.ProgramVersion.id).where(m.ProgramVersion.org_id == org_id)))
    dids = list(session.scalars(select(m.Dataset.id).where(m.Dataset.org_id == org_id)))
    plan_ids = list(session.scalars(select(m.TeachingPlan.id).where(m.TeachingPlan.org_id == org_id)))
    form_ids = list(session.scalars(select(m.AssessmentForm.id).where(m.AssessmentForm.program_version_id.in_(pids))))
    obj_ids = list(session.scalars(select(m.LearningObjective.id).where(m.LearningObjective.program_version_id.in_(pids))))
    user_ids = list(session.scalars(select(m.User.id).where(m.User.org_id == org_id)))

    def run(stmt):
        nonlocal n
        n += session.execute(stmt).rowcount or 0

    # measurement & learning-loop tables (Claude 2), children first; all of them carry org_id
    for name in ("pilot_session_events", "pilot_sessions", "intervention_evidence", "pilot_conclusions", "pilot_outcomes",
                 "fidelity_logs", "pilot_events", "pilot_cohorts", "pilots", "intervention_targets", "intervention_versions",
                 "interventions", "assessment_cohorts"):
        run(delete(_t(name)).where(T(name).org_id == org_id))
    quiz_ids = list(session.scalars(select(m.Quiz.id).where(m.Quiz.org_id == org_id)))
    run(delete(_t("quiz_response_sets")).where(T("quiz_response_sets").org_id == org_id))
    run(delete(_t("quiz_versions")).where(T("quiz_versions").quiz_id.in_(quiz_ids)))
    run(delete(_t("quizzes")).where(T("quizzes").org_id == org_id))
    for name in ("follow_ups", "decisions", "analysis_runs", "jobs", "fragment_objectives", "ai_generations"):
        run(delete(_t(name)).where(T(name).org_id == org_id))
    run(delete(_t("plan_topic_hours")).where(T("plan_topic_hours").plan_id.in_(plan_ids)))
    for name in ("teaching_plans", "responses", "sittings", "grade_records", "assessments", "material_exposures",
                 "learners", "cohorts", "teachers", "schools", "import_batches"):
        run(delete(_t(name)).where(T(name).org_id == org_id))
    run(delete(_t("dataset_versions")).where(T("dataset_versions").dataset_id.in_(dids)))
    run(delete(_t("datasets")).where(T("datasets").org_id == org_id))
    run(delete(_t("fragments")).where(T("fragments").org_id == org_id))
    run(delete(_t("editions")).where(T("editions").org_id == org_id))
    run(delete(_t("documents")).where(T("documents").org_id == org_id))
    run(delete(_t("item_objectives")).where(T("item_objectives").org_id == org_id))
    run(delete(_t("form_items")).where(T("form_items").form_id.in_(form_ids)))
    run(delete(_t("assessment_forms")).where(T("assessment_forms").id.in_(form_ids)))
    run(delete(_t("items")).where(T("items").program_version_id.in_(pids)))
    run(delete(_t("objective_relations")).where(T("objective_relations").source_objective_id.in_(obj_ids)))
    run(delete(_t("objectives")).where(T("objectives").program_version_id.in_(pids)))
    run(delete(_t("topics")).where(T("topics").program_version_id.in_(pids)))
    run(delete(_t("program_versions")).where(T("program_versions").org_id == org_id))
    run(delete(_t("scales")).where(T("scales").org_id == org_id))
    run(delete(_t("api_sessions")).where(T("api_sessions").user_id.in_(user_ids)))
    run(delete(_t("audit_log")).where(T("audit_log").org_id == org_id))
    run(delete(_t("users")).where(T("users").org_id == org_id))
    run(delete(_t("organizations")).where(T("organizations").id == org_id))
    root = get_settings().storage_dir
    for sub in ("imports", "documents"):
        shutil.rmtree(root / sub / org_id, ignore_errors=True)
    return n


def cleanup_expired(session: Session) -> dict:
    now = utcnow()
    expired = list(session.scalars(select(m.Organization.id).where(m.Organization.is_ephemeral.is_(True),
                                                                   m.Organization.expires_at < now)))
    rows = 0
    for org_id in expired:
        rows += delete_org_data(session, org_id)
        session.commit()
    sessions = session.execute(delete(m.ApiSession).where(m.ApiSession.expires_at < now)).rowcount or 0
    session.commit()
    counters = ratelimit.purge_expired(session)
    return {"tenants_deleted": len(expired), "rows_deleted": rows, "sessions_deleted": sessions,
            "rate_counters_deleted": counters}


def _register_jobs() -> None:
    from . import jobs

    @jobs.handler("demo_measurement")
    def _demo_measurement(session: Session, job: m.Job) -> dict:
        from ..demo.measurement_seed import seed_measurement

        org = session.get(m.Organization, job.org_id)
        if org is None or not org.is_ephemeral:  # tenant already cleaned up, or not a demo tenant
            return {"status": "skipped"}
        return seed_measurement(session, job.org_id, job.payload.get("user_id"))


_register_jobs()
