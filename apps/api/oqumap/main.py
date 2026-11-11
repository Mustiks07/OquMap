from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db
from .api.intervention_routes import router as intervention_router
from .api.quality_routes import router as quality_router
from .api.routes import router
from .config import CODE_VERSION, get_settings
from .errors import ApiError
from .schemas.api import ErrorResponse
from .services.common import request_id_var
from .services.ratelimit import client_ip_var, resolve_client_ip

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}

log = logging.getLogger("oqumap")


def create_app(database_url: str | None = None) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title="OquMap API", version=CODE_VERSION,
                  description="Аналитика результатов по темам, сравнение материалов на сопоставимых группах, "
                              "планирование часов и карточки решений для методистов.",
                  responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
                             404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
    app.state.sessionmaker = db.make_sessionmaker(database_url) if database_url else None
    app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins if o != "*"],
                       allow_credentials=False, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"])
    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    from .ai.provider import llm_config_problem

    problem = llm_config_problem()
    if problem:
        log.error("LLM provider %s misconfigured: %s (AI falls back to template/recorded modes)",
                  settings.llm_provider, problem)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        if len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        ip_token = client_ip_var.set(resolve_client_ip(request.client.host if request.client else None,
                                                       request.headers.get("x-forwarded-for")))
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
            client_ip_var.reset(ip_token)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    def err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
        rid = request_id_var.get()
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}},
                                                         "request_id": rid}, headers={"X-Request-ID": rid or ""})

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        resp = err(exc.status, exc.code, exc.message, exc.details)
        if exc.status == 429 and "retry_after" in exc.details:
            resp.headers["Retry-After"] = str(exc.details["retry_after"])
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return err(422, "validation_error", "Некорректные параметры запроса", {"errors": details})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return err(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError):
        # a uniqueness/foreign-key race that no service mapped explicitly: a conflict, not an internal error
        return err(409, "integrity_conflict", "Данные одновременно изменены другим запросом; повторите действие")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", request_id_var.get())
        return err(500, "internal_error", "Внутренняя ошибка сервера", {"type": type(exc).__name__})

    def _bind():
        return app.state.sessionmaker.kw["bind"] if app.state.sessionmaker else db.engine()

    @app.get("/health/live", tags=["system"])
    def live() -> dict:
        """Process is up (no dependency checks)."""
        return {"status": "ok", "version": CODE_VERSION}

    def readiness() -> tuple[bool, dict]:
        checks: dict = {}
        try:
            with _bind().connect() as conn:
                conn.execute(text("select 1"))
                checks["database"] = "ok"
                try:
                    current = conn.execute(text("select version_num from alembic_version")).scalar()
                except Exception:
                    current = None
                    conn.rollback()
                head = _alembic_head()
                checks["migrations"] = "ok" if (current == head or (current is None and head is None)) else \
                    f"pending:{current}->{head}"
                if settings.deployment_mode != "production" and checks["migrations"] == "ok":
                    from .demo.seed import DEMO_ORG_ID

                    present = conn.execute(text("select count(*) from organizations where id = :i"), {"i": DEMO_ORG_ID}).scalar()
                    checks["demo_template"] = "ok" if present else "missing"
        except Exception as exc:  # pragma: no cover - depends on infrastructure
            checks["database"] = f"error:{type(exc).__name__}"
        problem = llm_config_problem()
        checks["llm"] = "disabled" if settings.llm_provider == "none" else (f"misconfigured:{problem}" if problem else "configured")
        ok = checks.get("database") == "ok" and checks.get("migrations") == "ok" and checks.get("demo_template", "ok") == "ok"
        return ok, checks

    @app.get("/health/ready", tags=["system"])
    def ready():
        ok, checks = readiness()
        body = {"status": "ok" if ok else "not_ready", "version": CODE_VERSION, "deployment_mode": settings.deployment_mode,
                "job_mode": settings.job_mode, "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/health", tags=["system"])
    def health():
        return ready()

    app.include_router(router)
    app.include_router(quality_router)
    app.include_router(intervention_router)
    return app


_HEAD_CACHE: dict = {}


def _alembic_head() -> str | None:
    if "head" not in _HEAD_CACHE:
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[1]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "alembic"))
        _HEAD_CACHE["head"] = ScriptDirectory.from_config(cfg).get_current_head()
    return _HEAD_CACHE["head"]


app = create_app()
