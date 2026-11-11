from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..ai import assistant as asst
from ..ai import tasks as ai
from ..ai.gate import LiveGate, use_gate
from ..ai.provider import get_provider
from ..analytics.comparison import compare_arms
from ..analytics.fixtures import fixture_learners, load_fixture
from ..config import get_settings
from ..db import get_session
from ..errors import ApiError, not_found
from ..schemas import api as S
from ..services import analysis as an
from ..services import (
    auth,
    decisions,
    demo_tenants,
    documents,
    imports,
    jobs,
    mappings,
    planning,
    ratelimit,
    reports,
    search,
)
from ..services.auth import Principal
from ..services.ratelimit import client_ip_var

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_session)]


def principal(session: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    return auth.resolve_token(session, token)


P = Annotated[Principal, Depends(principal)]


def check_storage_quota(session: Session, org: m.Organization, add_bytes: int) -> None:
    from sqlalchemy import func

    s = get_settings()
    quota = org.storage_quota_bytes or s.org_storage_quota_mb * 1024 * 1024
    used = (session.scalar(select(func.coalesce(func.sum(m.Document.size_bytes), 0)).where(m.Document.org_id == org.id)) or 0) \
        + (session.scalar(select(func.coalesce(func.sum(m.ImportBatch.size_bytes), 0)).where(m.ImportBatch.org_id == org.id)) or 0)
    if used + add_bytes > quota:
        raise ApiError("storage_quota_exceeded", "Превышена квота хранения файлов организации", 413,
                       {"quota_bytes": quota, "used_bytes": int(used)})


def parse_filters(filters: str | None) -> an.Filters:
    if not filters:
        return an.Filters()
    try:
        return an.Filters(**json.loads(filters))
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ApiError("invalid_filter", "Некорректный параметр filters", 422, {"reason": type(exc).__name__}) from None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class DemoLogin(BaseModel):
    persona: str | None = None


class PasswordLogin(BaseModel):
    username: str
    password: str


def _user_out(session: Session, user: m.User) -> S.UserOut:
    org = session.get(m.Organization, user.org_id)
    return S.UserOut(id=user.id, username=user.username, display_name=user.display_name, roles=user.roles,
                     org_id=org.id, org_name=org.name, org_is_demo=org.is_demo, org_is_ephemeral=org.is_ephemeral,
                     org_expires_at=org.expires_at.isoformat() if org.expires_at else None)


@router.get("/config", tags=["system"])
def public_config() -> dict[str, Any]:
    """Non-secret runtime flags for the web client."""
    s = get_settings()
    prov = get_provider()
    return {"deployment_mode": s.deployment_mode, "demo_login_enabled": s.deployment_mode != "production",
            "qa_personas_enabled": s.deployment_mode == "dev", "password_login_enabled": True,
            "demo_tenant_ttl_hours": s.demo_tenant_ttl_hours if s.deployment_mode == "public_demo" else None,
            "live_ai_configured": prov.available, "llm_config_error": prov.config_error,
            "lab_scenarios": demo_tenants.LAB_DATASETS, "recommended_dataset_code": demo_tenants.RECOMMENDED_DATASET}


@router.post("/auth/demo-login", response_model=S.LoginResponse, tags=["auth"])
def demo_login(body: DemoLogin, session: DB):
    token, user, recommended = auth.demo_login(session, body.persona, client_ip_var.get())
    return S.LoginResponse(token=token, user=_user_out(session, user), recommended_dataset_id=recommended)


@router.post("/auth/login", response_model=S.LoginResponse, tags=["auth"])
def login(body: PasswordLogin, session: DB):
    token, user = auth.password_login(session, body.username, body.password, client_ip_var.get())
    return S.LoginResponse(token=token, user=_user_out(session, user))


@router.post("/auth/logout", tags=["auth"])
def logout(session: DB, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    auth.logout(session, token)
    return {"status": "ok"}


@router.post("/demo/scenarios/{code}", tags=["datasets"])
def load_lab_scenario(code: str, p: P, session: DB) -> dict[str, Any]:
    """Load a laboratory scenario dataset into the visitor's demo tenant (cloned on first use)."""
    ratelimit.check(session, "lab", p.org_id, "rate_import")
    ds_id = demo_tenants.load_lab_dataset(session, p.org, code)
    return an.dataset_summary(an.get_dataset(session, p.org_id, ds_id))


@router.get("/auth/me", response_model=S.UserOut, tags=["auth"])
def me(p: P, session: DB):
    return _user_out(session, p.user)


# ---------------------------------------------------------------------------
# Datasets, curriculum, analyses
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=list[S.DatasetSummary], tags=["datasets"])
def list_datasets(p: P, session: DB):
    rows = session.scalars(select(m.Dataset).where(m.Dataset.org_id == p.org_id).order_by(m.Dataset.created_at))
    return [an.dataset_summary(d) for d in rows]


class ProjectCreate(BaseModel):
    name_ru: str
    name_kz: str | None = None
    description_ru: str = ""
    is_synthetic: bool = False


@router.post("/datasets", response_model=S.DatasetSummary, tags=["datasets"])
def create_project(body: ProjectCreate, p: P, session: DB):
    """Create an empty project (dataset) to be filled by the staged imports."""
    p.require("methodist")
    ratelimit.check(session, "import", p.org_id, "rate_import")
    name = body.name_ru.strip()
    if not name or len(name) > 300:
        raise ApiError("validation_error", "Укажите название проекта (до 300 символов)", 422)
    import uuid as _uuid

    ds = m.Dataset(org_id=p.org_id, program_version_id=None, code=f"project-{_uuid.uuid4().hex[:8]}", name_ru=name,
                   name_kz=(body.name_kz or name).strip()[:300], description_ru=body.description_ru[:2000],
                   description_kz="", is_synthetic=body.is_synthetic or p.org.is_demo, data_level="setup", version=0,
                   manifest={"source": "onboarding"})
    session.add(ds)
    from ..services.common import audit

    audit(session, p.org_id, p.user_id, "dataset.create", "dataset", ds.id, name=name)
    session.commit()
    return an.dataset_summary(ds)


@router.get("/datasets/{dataset_id}/project", tags=["datasets"])
def project_status(dataset_id: str, p: P, session: DB) -> dict[str, Any]:
    from ..services.onboarding import project_status as ps

    return ps(session, an.get_dataset(session, p.org_id, dataset_id))


@router.get("/imports/templates", tags=["imports"])
def import_templates() -> dict[str, Any]:
    from ..services import onboarding as ob

    kinds = []
    for k in ob.ORDER:
        docs = ob.docs_for(k)
        kinds.append({"kind": k, "order": ob.ORDER.index(k) + 1, "strict": k in ob.STRICT_KINDS,
                      "fields": [{"name": f, "required": r, "description": d, "example": ex} for f, (r, d, ex) in docs.items()],
                      "template_csv": f"/api/v1/imports/templates/{k}?format=csv",
                      "template_xlsx": f"/api/v1/imports/templates/{k}?format=xlsx",
                      "example_csv": f"/api/v1/imports/examples/{k}"})
    return {"order": ob.ORDER, "kinds": kinds,
            "rules": ["Коды (school_code, class_code, learner_code, item_code, objective_code …) — стабильные внешние ключи: "
                      "не меняйте их между загрузками.",
                      "Порядок: программа → издания → банк заданий → состав → ответы.",
                      "Формулы в ячейках не допускаются и не вычисляются.",
                      "Ученики — только псевдонимные коды, без ФИО и иных персональных данных."]}


@router.get("/imports/templates/{kind}", tags=["imports"],
            responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def import_template(kind: str, format: str = "xlsx"):
    from ..services import onboarding as ob

    if kind not in ob.ORDER:
        raise not_found("template", kind)
    docs = ob.docs_for(kind)
    header = list(docs.keys())
    example = [ex for _, _, ex in docs.values()]
    if format == "csv":
        import csv as _csv
        import io as _io

        buf = _io.StringIO()
        w = _csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerow(example)
        return Response(("\ufeff" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="oqumap-template-{kind}.csv"'})
    if format != "xlsx":
        raise ApiError("invalid_parameter", "format: csv | xlsx", 422)
    import io as _io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(header)
    ws.append(example)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in ws.iter_rows():
        for c in row:
            c.data_type = "s"
    info = wb.create_sheet("instructions")
    info.append(["Поле", "Обязательно", "Описание", "Пример"])
    for f, (r, d, ex) in docs.items():
        info.append([f, "да" if r else "нет", d, ex])
    info.append([])
    info.append(["Лист data: первая строка — заголовки (не переименовывать), вторая — пример (удалите перед загрузкой)."])
    info.append(["Коды — стабильные внешние ключи. Формулы не допускаются. Ученики — только псевдонимные коды."])
    info.column_dimensions["A"].width = 22
    info.column_dimensions["C"].width = 80
    buf = _io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="oqumap-template-{kind}.xlsx"'})


@router.get("/imports/examples/{kind}", tags=["imports"], responses={200: {"content": {"text/csv": {}}}})
def import_example(kind: str):
    from ..config import REPO_ROOT
    from ..services import onboarding as ob

    if kind not in ob.ORDER:
        raise not_found("example", kind)
    path = REPO_ROOT / "data" / "templates" / "example_project" / f"{ob.ORDER.index(kind) + 1}_{kind}.csv"
    return Response(path.read_bytes(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="example-{path.name}"'})


# ---------------------------------------------------------------------------
# Users (non-demo organisations)
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    roles: list[str]


class UserUpdate(BaseModel):
    roles: list[str] | None = None
    is_active: bool | None = None
    password: str | None = None


@router.get("/admin/users", tags=["admin"])
def admin_users(p: P, session: DB) -> list[dict[str, Any]]:
    from ..services import admin

    return admin.list_users(session, p)


@router.post("/admin/users", tags=["admin"])
def admin_create_user(body: UserCreate, p: P, session: DB) -> dict[str, Any]:
    from ..services import admin

    return admin.create_user(session, p, body.username, body.password, body.display_name, body.roles)


@router.post("/admin/users/{user_id}", tags=["admin"])
def admin_update_user(user_id: str, body: UserUpdate, p: P, session: DB) -> dict[str, Any]:
    from ..services import admin

    return admin.update_user(session, p, user_id, body.roles, body.is_active, body.password)


@router.get("/datasets/{dataset_id}", response_model=S.DatasetSummary, tags=["datasets"])
def get_dataset(dataset_id: str, p: P, session: DB):
    return an.dataset_summary(an.get_dataset(session, p.org_id, dataset_id))


@router.get("/datasets/{dataset_id}/quality", tags=["datasets"])
def dataset_quality(dataset_id: str, p: P, session: DB) -> dict[str, Any]:
    return an.dataset_quality(session, p.org_id, dataset_id)


@router.post("/datasets/{dataset_id}/overview", response_model=S.Envelope[S.OverviewResult], tags=["analyses"])
def overview(dataset_id: str, filters: an.Filters, p: P, session: DB):
    return an.overview(session, p.org_id, dataset_id, filters, p.user_id)


@router.get("/curriculum", tags=["curriculum"])
def curriculum(dataset_id: str, p: P, session: DB) -> dict[str, Any]:
    ds = an.get_dataset(session, p.org_id, dataset_id)
    meta = an.load_meta(session, p.org_id, ds.id)
    pv = session.get(m.ProgramVersion, ds.program_version_id)
    rels = list(session.scalars(select(m.ObjectiveRelation).where(
        m.ObjectiveRelation.target_objective_id.in_([o.id for o in meta.objectives]))))
    return {
        "program": {"id": pv.id, "title": pv.title, "subject": pv.subject, "grade": pv.grade, "version": pv.version,
                    "source": pv.source, "is_demo_codes": pv.is_demo_codes},
        "topics": [{"id": t.id, "code": t.code, "title_ru": t.title_ru, "title_kz": t.title_kz, "kz_verified": t.kz_verified,
                    "order": t.order_index} for t in meta.topics],
        "objectives": [{"id": o.id, "code": o.code, "topic_id": o.topic_id, "text_ru": o.text_ru, "text_kz": o.text_kz,
                        "kz_verified": o.kz_verified} for o in meta.objectives],
        "relations": [{"source": r.source_objective_id, "target": r.target_objective_id, "type": r.relation_type,
                       "confirmed": r.confirmed} for r in rels],
        "editions": [{"id": e.id, "code": e.code, "title": e.title, "edition_label": e.edition_label, "year": e.year,
                      "language": e.language, "is_demo": e.is_demo, "document_id": e.document_id}
                     for e in meta.editions.values()],
        "schools": sorted([{"id": s.id, "code": s.code, "name": s.name} for s in meta.schools.values()], key=lambda x: x["code"]),
        "cohorts": sorted([{"id": c.id, "code": c.code, "school_id": c.school_id, "language": c.language,
                            "academic_year": c.academic_year} for c in meta.cohorts.values()], key=lambda x: x["code"]),
        "assessments": sorted([{"id": a.id, "code": a.code, "stage": a.stage, "form": meta.forms[a.form_id].code,
                                "scale": meta.scales[meta.forms[a.form_id].scale_id].code} for a in meta.assessments.values()],
                              key=lambda x: x["code"]),
        "strata_schemes": ["pre_three_level", "pre_two_level"],
        "weight_modes": ["pooled", "equal", "arm_a", "arm_b"],
    }


@router.get("/topics/{topic_id}/evidence", response_model=S.Envelope[S.TopicEvidenceResult], tags=["analyses"])
def topic_evidence(topic_id: str, dataset_id: str, p: P, session: DB, filters: str | None = None):
    return an.topic_evidence(session, p.org_id, dataset_id, topic_id, parse_filters(filters), p.user_id)


@router.post("/comparisons", response_model=S.Envelope[S.ComparisonResult], tags=["analyses"])
def comparison(body: an.ComparisonRequest, p: P, session: DB):
    ratelimit.check(session, "compute", p.user_id, "rate_compute")
    return an.comparison(session, p.org_id, body, p.user_id)


@router.get("/analyses/{analysis_id}", tags=["analyses"])
def get_analysis(analysis_id: str, p: P, session: DB) -> dict[str, Any]:
    return an.get_run(session, p.org_id, analysis_id)


@router.get("/fixtures/composition", tags=["analyses"])
def composition_fixture(p: P) -> dict[str, Any]:
    """Arithmetic illustration of standardisation computed from data/demo/fixtures/composition_fixture.json."""
    fx = load_fixture()
    learners = fixture_learners(fx)
    res = compare_arms(learners, "A", "B", fx["strata_scheme"], "equal", replicates=200)
    return {"fixture": fx, "raw": res["raw"], "adjusted": res["adjusted"], "status": res["status"],
            "inference_level": res["inference_level"],
            "note_ru": "Учебная иллюстрация: не доказательство причинности и не основа для доверительных интервалов."}


# ---------------------------------------------------------------------------
# Imports and jobs
# ---------------------------------------------------------------------------


def _batch_out(b: m.ImportBatch, full: bool = True) -> S.ImportBatchOut:
    d = an.batch_summary(b)
    if full:
        d.update({"sheet": b.sheet, "column_mapping": b.column_mapping, "report": b.report})
    return S.ImportBatchOut(**d)


@router.post("/imports/validate", response_model=S.ImportBatchOut, tags=["imports"])
async def import_validate(
    p: P, session: DB, file: Annotated[UploadFile, File()], kind: Annotated[str, Form()] = "responses",
    dataset_id: Annotated[str | None, Form()] = None, new_dataset_name: Annotated[str | None, Form()] = None,
    is_synthetic: Annotated[bool, Form()] = False, sheet: Annotated[str | None, Form()] = None,
    column_mapping: Annotated[str | None, Form()] = None, options: Annotated[str | None, Form()] = None,
):
    p.require("methodist")
    ratelimit.check(session, "import", p.org_id, "rate_import")
    data = await file.read(get_settings().max_upload_bytes + 1)
    check_storage_quota(session, p.org, len(data))
    try:
        mapping = json.loads(column_mapping) if column_mapping else None
        opts = json.loads(options) if options else None
    except json.JSONDecodeError:
        raise ApiError("invalid_parameter", "column_mapping/options должны быть JSON", 422) from None
    new_ds = {"name": new_dataset_name, "is_synthetic": is_synthetic or p.org.is_demo} if new_dataset_name else None
    batch = imports.validate_upload(session, org=p.org, user_id=p.user_id, data=data, filename=file.filename or "upload.csv",
                                    kind=kind, dataset_id=dataset_id, new_dataset=new_ds, sheet=sheet, mapping=mapping,
                                    options=opts)
    return _batch_out(batch)


class CommitRequest(BaseModel):
    batch_id: str
    wait: bool = False


@router.post("/imports/commit", response_model=S.JobOut, tags=["imports"])
def import_commit(body: CommitRequest, p: P, session: DB):
    p.require("methodist")
    batch = session.scalar(select(m.ImportBatch).where(m.ImportBatch.id == body.batch_id, m.ImportBatch.org_id == p.org_id))
    if batch is None:
        raise not_found("import_batch", body.batch_id)
    job = jobs.enqueue(session, p.org_id, "import_commit", {"batch_id": batch.id, "user_id": p.user_id},
                       idempotency_key=f"commit:{batch.id}", user_id=p.user_id) if not body.wait else None
    if body.wait:
        job = session.scalar(select(m.Job).where(m.Job.idempotency_key == f"commit:{batch.id}"))
        if job is None:
            job = m.Job(org_id=p.org_id, kind="import_commit", payload={"batch_id": batch.id, "user_id": p.user_id},
                        idempotency_key=f"commit:{batch.id}", created_by=p.user_id, status="running", attempts=1)
            session.add(job)
            session.commit()
            jobs.execute(session, job)
            session.refresh(job)
    return job_out(job)


@jobs.handler("import_commit")
def _job_commit(session: Session, job: m.Job) -> dict:
    return imports.commit_batch(session, job.org_id, job.payload["batch_id"], job.payload.get("user_id"))


@router.get("/imports", response_model=list[S.ImportBatchOut], tags=["imports"])
def list_imports(p: P, session: DB, dataset_id: str | None = None):
    q = select(m.ImportBatch).where(m.ImportBatch.org_id == p.org_id)
    if dataset_id:
        q = q.where(m.ImportBatch.dataset_id == dataset_id)
    return [_batch_out(b, full=False) for b in session.scalars(q.order_by(m.ImportBatch.created_at.desc()))]


@router.get("/imports/{batch_id}", response_model=S.ImportBatchOut, tags=["imports"])
def get_import(batch_id: str, p: P, session: DB):
    b = session.scalar(select(m.ImportBatch).where(m.ImportBatch.id == batch_id, m.ImportBatch.org_id == p.org_id))
    if b is None:
        raise not_found("import_batch", batch_id)
    return _batch_out(b)


def job_out(job: m.Job) -> S.JobOut:
    return S.JobOut(id=job.id, kind=job.kind, status=job.status, progress=job.progress, result=job.result, error=job.error,
                    attempts=job.attempts, created_at=job.created_at.isoformat(),
                    started_at=job.started_at.isoformat() if job.started_at else None,
                    finished_at=job.finished_at.isoformat() if job.finished_at else None)


@router.get("/jobs/{job_id}", response_model=S.JobOut, tags=["jobs"])
def get_job(job_id: str, p: P, session: DB):
    job = jobs.get_job(session, p.org_id, job_id)
    session.refresh(job)
    return job_out(job)


# ---------------------------------------------------------------------------
# Documents, sources, mappings
# ---------------------------------------------------------------------------


def _doc_out(d: m.Document) -> dict:
    return {"id": d.id, "filename": d.filename, "media_type": d.media_type, "sha256": d.sha256, "version": d.version,
            "status": d.status, "page_count": d.page_count, "ocr_status": d.ocr_status, "edition_id": d.edition_id,
            "is_demo": d.is_demo, "extraction_report": d.extraction_report, "created_at": d.created_at.isoformat()}


@router.get("/documents", tags=["documents"])
def list_documents(p: P, session: DB) -> list[dict[str, Any]]:
    return [_doc_out(d) for d in session.scalars(select(m.Document).where(m.Document.org_id == p.org_id)
                                                  .order_by(m.Document.created_at))]


@router.post("/documents", tags=["documents"])
async def upload_document(p: P, session: DB, file: Annotated[UploadFile, File()],
                          edition_id: Annotated[str | None, Form()] = None) -> dict[str, Any]:
    p.require("methodist")
    ratelimit.check(session, "document", p.org_id, "rate_document")
    data = await file.read(get_settings().max_upload_bytes + 1)
    check_storage_quota(session, p.org, len(data))
    doc, created = documents.store_document(session, p.org_id, p.user_id, data, file.filename or "document",
                                            edition_id=edition_id, is_demo=p.org.is_demo)
    job = documents.enqueue_extraction(session, doc, p.user_id)
    return {"document": _doc_out(doc), "created": created, "job": job_out(job).model_dump()}


@router.get("/documents/{document_id}", tags=["documents"])
def get_document(document_id: str, p: P, session: DB) -> dict[str, Any]:
    d = session.scalar(select(m.Document).where(m.Document.id == document_id, m.Document.org_id == p.org_id))
    if d is None:
        raise not_found("document", document_id)
    frags = session.scalars(select(m.ContentFragment).where(m.ContentFragment.document_id == d.id,
                                                            m.ContentFragment.document_version == d.version)
                            .order_by(m.ContentFragment.order_index))
    links = mappings.list_links(session, p.org_id, document_id=d.id)["fragment_links"]
    return {"document": _doc_out(d),
            "fragments": [{"id": f.id, "anchor": f.anchor, "page_physical": f.page_physical, "page_printed": f.page_printed,
                           "heading": f.heading, "text": f.text} for f in frags],
            "links": links}


@router.get("/documents/{document_id}/file", tags=["documents"])
def document_file(document_id: str, p: P, session: DB):
    d = session.scalar(select(m.Document).where(m.Document.id == document_id, m.Document.org_id == p.org_id))
    if d is None:
        raise not_found("document", document_id)
    from pathlib import Path

    return Response(Path(d.storage_path).read_bytes(), media_type=d.media_type,
                    headers={"Content-Disposition": f'attachment; filename="document-{d.id[:8]}{".pdf" if d.media_type == documents.PDF_MEDIA else ".docx"}"',
                             "X-Content-Type-Options": "nosniff"})


@router.post("/documents/{document_id}/propose-links", tags=["documents", "ai"])
def propose_links(document_id: str, p: P, session: DB) -> dict[str, Any]:
    p.require("methodist")
    ratelimit.check(session, "ai", p.user_id, "rate_ai")
    with use_gate(LiveGate.for_principal(session, p)):
        return ai.propose_fragment_links_for_document(session, p.org_id, p.user_id, document_id)


@router.get("/sources/search", tags=["sources"])
def search_sources(q: str, p: P, session: DB, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> dict[str, Any]:
    return search.search(session, p.org_id, q, limit)


@router.get("/sources/{source_id}", response_model=S.SourceOut, tags=["sources"])
def get_source(source_id: str, p: P, session: DB):
    return documents.source_payload(session, p.org_id, source_id)


@router.get("/mappings", tags=["mappings"])
def list_mappings(p: P, session: DB, document_id: str | None = None, status: str | None = None) -> dict[str, Any]:
    return mappings.list_links(session, p.org_id, document_id, status)


@router.post("/mappings/{link_id}/review", tags=["mappings"])
def review_mapping(link_id: str, body: mappings.ReviewRequest, p: P, session: DB) -> dict[str, Any]:
    return mappings.review(session, p, link_id, body)


@router.post("/items/{item_id}/suggest-links", tags=["mappings", "ai"])
def suggest_item_links(item_id: str, p: P, session: DB) -> dict[str, Any]:
    p.require("methodist", "teacher")
    ratelimit.check(session, "ai", p.user_id, "rate_ai")
    with use_gate(LiveGate.for_principal(session, p)):
        return ai.propose_item_links(session, p.org_id, item_id)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@router.get("/plans/context", tags=["plans"])
def plan_context(dataset_id: str, p: P, session: DB, filters: str | None = None) -> dict[str, Any]:
    return planning.plan_context(session, p.org_id, dataset_id, parse_filters(filters), p.user_id)


@router.post("/plans/solve", response_model=S.Envelope[S.PlanResult], tags=["plans"])
def solve_plan(body: planning.PlanSolveRequest, p: P, session: DB):
    ratelimit.check(session, "compute", p.user_id, "rate_compute")
    return planning.solve(session, p.org_id, body, p.user_id)


# ---------------------------------------------------------------------------
# Decisions and reports
# ---------------------------------------------------------------------------


@router.post("/decisions", response_model=S.DecisionOut, tags=["decisions"])
def create_decision(body: decisions.DecisionCreate, p: P, session: DB):
    return decisions.create(session, p, body)


@router.get("/decisions", tags=["decisions"])
def list_decisions(p: P, session: DB, dataset_id: str | None = None) -> list[dict[str, Any]]:
    return decisions.list_decisions(session, p.org_id, dataset_id)


@router.get("/decisions/{decision_id}", response_model=S.DecisionOut, tags=["decisions"])
def get_decision(decision_id: str, p: P, session: DB):
    return decisions.decision_payload(session, decisions.get(session, p.org_id, decision_id))


class ApproveRequest(BaseModel):
    note: str | None = None


@router.post("/decisions/{decision_id}/approve", response_model=S.DecisionOut, tags=["decisions"])
def approve_decision(decision_id: str, body: ApproveRequest, p: P, session: DB):
    return decisions.approve(session, p, decision_id, body.note)


@router.post("/decisions/{decision_id}/follow-up", response_model=S.FollowUpResponse, tags=["decisions"])
def follow_up(decision_id: str, body: decisions.FollowUpRequest, p: P, session: DB):
    return decisions.follow_up(session, p, decision_id, body)


@router.get("/decisions/{decision_id}/report", tags=["decisions"],
            responses={200: {"content": {"application/pdf": {}, "text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def decision_report(decision_id: str, p: P, session: DB, format: str = "pdf"):
    d = decisions.decision_payload(session, decisions.get(session, p.org_id, decision_id))
    name = f"oqumap-decision-{d['id'][:8]}-v{d['version']}"
    if format == "pdf":
        body, media = reports.to_pdf(d), "application/pdf"
    elif format == "csv":
        body, media = reports.to_csv(d), "text/csv; charset=utf-8"
    elif format == "xlsx":
        body, media = reports.to_xlsx(d), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise ApiError("invalid_parameter", "format: pdf | csv | xlsx", 422)
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


@router.get("/ai/status", tags=["ai"])
def ai_status(p: P, session: DB) -> dict[str, Any]:
    prov = get_provider()
    s = get_settings()
    from ..services.documents import OcrAdapter

    ocr = OcrAdapter()
    gate_reason = LiveGate.for_principal(session, p).acquire_dry_run() if prov.available else None
    return {"provider": prov.name, "model": prov.model, "live_available": prov.available and gate_reason is None,
            "config_error": prov.config_error, "live_blocked_reason": gate_reason,
            "fallback_modes": ["recorded_demo", "template"], "ocr_engine": s.ocr_engine, "ocr_available": ocr.available,
            "note_ru": None if (prov.available and gate_reason is None) else
            "Живая модель недоступна для этой сессии: используются шаблоны и записанные демо-примеры."}


class AnalysisLang(BaseModel):
    analysis_id: str
    lang: str = "ru"


class MisconceptionReq(AnalysisLang):
    code: str


class RecommendReq(BaseModel):
    topic_analysis_id: str
    comparison_analysis_id: str | None = None
    lang: str = "ru"


@router.post("/ai/explain-comparison", response_model=S.GenerationOut, tags=["ai"])
def explain_comparison(body: AnalysisLang, p: P, session: DB):
    ratelimit.check(session, "ai", p.user_id, "rate_ai")
    with use_gate(LiveGate.for_principal(session, p)):
        return ai.explain_comparison(session, p.org_id, body.analysis_id, body.lang)


@router.post("/ai/interpret-misconception", response_model=S.GenerationOut, tags=["ai"])
def interpret_misconception(body: MisconceptionReq, p: P, session: DB):
    ratelimit.check(session, "ai", p.user_id, "rate_ai")
    with use_gate(LiveGate.for_principal(session, p)):
        return ai.interpret_misconception(session, p.org_id, body.analysis_id, body.code, body.lang)


@router.post("/ai/recommend", response_model=S.GenerationOut, tags=["ai"])
def recommend(body: RecommendReq, p: P, session: DB):
    ratelimit.check(session, "ai", p.user_id, "rate_ai")
    with use_gate(LiveGate.for_principal(session, p)):
        return ai.recommend(session, p.org_id, body.topic_analysis_id, body.comparison_analysis_id, body.lang)


@router.post("/assistant/query", response_model=S.AssistantAnswer, tags=["ai"])
def assistant_query(body: asst.AssistantQuery, p: P, session: DB):
    ratelimit.check(session, "assistant", p.user_id, "rate_assistant")
    with use_gate(LiveGate.for_principal(session, p)):
        return asst.answer(session, p, body)
