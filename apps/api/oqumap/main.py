from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .api.intervention_routes import router as intervention_router
from .api.quality_routes import router as quality_router
from .api.routes import router
from .config import CODE_VERSION, get_settings
from .errors import ApiError
from .schemas.api import ErrorResponse
from .services.common import request_id_var

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
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID", "Content-Disposition"])

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        if len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    def err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
        rid = request_id_var.get()
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}},
                                                         "request_id": rid}, headers={"X-Request-ID": rid or ""})

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return err(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return err(422, "validation_error", "Некорректные параметры запроса", {"errors": details})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return err(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", request_id_var.get())
        return err(500, "internal_error", "Внутренняя ошибка сервера", {"type": type(exc).__name__})

    @app.get("/health", tags=["system"])
    def health() -> dict:
        status = "ok"
        try:
            bind = app.state.sessionmaker.kw["bind"] if app.state.sessionmaker else db.engine()
            with bind.connect() as conn:
                conn.execute(text("select 1"))
        except Exception:  # pragma: no cover
            status = "degraded"
        return {"status": status, "version": CODE_VERSION, "job_mode": settings.job_mode, "llm_provider": settings.llm_provider}

    app.include_router(router)
    app.include_router(quality_router)
    app.include_router(intervention_router)
    return app


app = create_app()
