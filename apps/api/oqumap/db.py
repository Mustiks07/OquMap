from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


OQUMAP_NS = uuid.UUID("7f1d3f0e-8d2a-4a51-9a0c-3b8f5f2c9e11")


def stable_id(*parts: str) -> str:
    """Deterministic UUID for demo/seed objects (documented stable IDs)."""
    return str(uuid.uuid5(OQUMAP_NS, "/".join(parts)))


class TZDateTime(TypeDecorator):
    """Timezone-aware datetime on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, nullable=False)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - sqlite only
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def configure(url: str | None = None) -> None:
    global _engine, _SessionLocal
    _engine = _make_engine(url or get_settings().database_url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
