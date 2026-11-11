"""Organisations and users for non-demo installations (password accounts, roles)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ApiError, not_found
from .auth import Principal, hash_password
from .common import audit

ROLES = {"admin", "methodist", "approver", "teacher", "viewer"}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,60}$")


def validate_password(pw: str) -> None:
    if len(pw) < 10 or pw.isdigit() or pw.lower() == pw and pw.isalpha():
        raise ApiError("weak_password", "Пароль: не короче 10 символов, не только цифры или строчные буквы", 422)


def create_organization(session: Session, name: str, admin_username: str, admin_password: str,
                        admin_display_name: str | None = None) -> tuple[m.Organization, m.User]:
    org = m.Organization(name=name.strip()[:200], is_demo=False)
    session.add(org)
    session.flush()
    user = _new_user(session, org.id, admin_username, admin_password, admin_display_name or admin_username,
                     ["admin", "methodist", "approver"])
    audit(session, org.id, None, "org.create", "organization", org.id, admin=user.username)
    session.commit()
    return org, user


def _new_user(session, org_id, username, password, display_name, roles) -> m.User:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise ApiError("invalid_username", "Имя пользователя: 3–60 символов a-z, 0-9, . _ -", 422)
    if set(roles) - ROLES or not roles:
        raise ApiError("invalid_roles", "Недопустимые роли", 422, {"allowed": sorted(ROLES)})
    if session.scalar(select(m.User.id).where(m.User.username == username)):
        raise ApiError("username_taken", "Имя пользователя занято", 409)
    validate_password(password)
    u = m.User(org_id=org_id, username=username, display_name=display_name.strip()[:200] or username, roles=sorted(set(roles)),
               password_hash=hash_password(password), is_demo=False, is_active=True)
    session.add(u)
    session.flush()
    return u


def user_out(u: m.User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "roles": u.roles, "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}


def list_users(session: Session, p: Principal) -> list[dict]:
    p.require("admin")
    return [user_out(u) for u in session.scalars(select(m.User).where(m.User.org_id == p.org_id).order_by(m.User.username))]


def create_user(session: Session, p: Principal, username: str, password: str, display_name: str, roles: list[str]) -> dict:
    p.require("admin")
    if p.org.is_demo:
        raise ApiError("not_in_demo", "Управление пользователями недоступно в демо", 403)
    u = _new_user(session, p.org_id, username, password, display_name, roles)
    audit(session, p.org_id, p.user_id, "user.create", "user", u.id, roles=u.roles)
    session.commit()
    return user_out(u)


def update_user(session: Session, p: Principal, user_id: str, roles: list[str] | None, is_active: bool | None,
                password: str | None) -> dict:
    p.require("admin")
    u = session.scalar(select(m.User).where(m.User.id == user_id, m.User.org_id == p.org_id))
    if u is None:
        raise not_found("user", user_id)
    if roles is not None:
        if set(roles) - ROLES or not roles:
            raise ApiError("invalid_roles", "Недопустимые роли", 422, {"allowed": sorted(ROLES)})
        if u.id == p.user_id and "admin" not in roles:
            raise ApiError("cannot_drop_own_admin", "Нельзя снять у себя роль администратора", 422)
        u.roles = sorted(set(roles))
    if is_active is not None:
        if u.id == p.user_id and not is_active:
            raise ApiError("cannot_deactivate_self", "Нельзя отключить собственную учётную запись", 422)
        u.is_active = is_active
        if not is_active:
            session.query(m.ApiSession).filter(m.ApiSession.user_id == u.id).delete()
    if password:
        validate_password(password)
        u.password_hash = hash_password(password)
        session.query(m.ApiSession).filter(m.ApiSession.user_id == u.id).delete()
    audit(session, p.org_id, p.user_id, "user.update", "user", u.id, roles=u.roles, is_active=u.is_active,
          password_changed=bool(password))
    session.commit()
    return user_out(u)
