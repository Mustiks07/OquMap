"""Server-side authentication and authorisation.

Bearer tokens are random 32-byte values; only their SHA-256 is stored. Every request resolves to a user and
an organisation; all queries are scoped by that organisation id on the server.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import utcnow
from ..errors import ApiError, forbidden

PBKDF2_ROUNDS = 240_000


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(raw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, rounds, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(dk.hex(), digest)
    except ValueError:
        return False


@dataclass
class Principal:
    user: m.User
    org: m.Organization

    @property
    def org_id(self) -> str:
        return self.org.id

    @property
    def user_id(self) -> str:
        return self.user.id

    def require(self, *roles: str) -> None:
        if not set(roles) & set(self.user.roles or []) and "admin" not in (self.user.roles or []):
            raise forbidden(details={"required_roles": list(roles)})


def issue_token(session: Session, user: m.User) -> str:
    token = secrets.token_urlsafe(32)
    session.add(m.ApiSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours)))
    session.commit()
    return token


def resolve_token(session: Session, token: str | None) -> Principal:
    if not token:
        raise ApiError("unauthenticated", "Требуется вход", 401)
    h = hashlib.sha256(token.encode()).hexdigest()
    sess = session.scalar(select(m.ApiSession).where(m.ApiSession.token_hash == h))
    if sess is None or sess.expires_at < utcnow():
        raise ApiError("unauthenticated", "Сессия недействительна или истекла", 401)
    user = session.get(m.User, sess.user_id)
    org = session.get(m.Organization, user.org_id) if user else None
    if user is None or org is None:
        raise ApiError("unauthenticated", "Пользователь не найден", 401)
    return Principal(user, org)


DEMO_PERSONAS = {"methodist": "demo.methodist", "viewer": "demo.viewer", "other_org": "other.methodist"}


def demo_login(session: Session, persona: str) -> tuple[str, m.User]:
    username = DEMO_PERSONAS.get(persona)
    if username is None:
        raise ApiError("unknown_persona", "Неизвестная демо-роль", 422, {"allowed": list(DEMO_PERSONAS)})
    user = session.scalar(select(m.User).where(m.User.username == username, m.User.is_demo.is_(True)))
    if user is None:
        raise ApiError("demo_not_seeded", "Демо-данные не загружены. Выполните seed.", 503)
    return issue_token(session, user), user


def password_login(session: Session, username: str, password: str) -> tuple[str, m.User]:
    user = session.scalar(select(m.User).where(m.User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise ApiError("invalid_credentials", "Неверное имя пользователя или пароль", 401)
    return issue_token(session, user), user
