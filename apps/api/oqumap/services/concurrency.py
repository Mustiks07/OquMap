"""Turning database uniqueness races into clear 409 responses (never a random 500)."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import ApiError


@contextmanager
def conflict_as(session: Session, code: str, message: str, details: dict | None = None):
    """Wrap a flush/commit: an IntegrityError (unique / FK / check race) rolls back and becomes ``409 code``."""
    try:
        yield
    except IntegrityError:
        session.rollback()
        raise ApiError(code, message, 409, details or {}) from None
