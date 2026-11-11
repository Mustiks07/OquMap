"""Helpers for the measurement & learning-loop tests (kept out of conftest.py to avoid shared-file conflicts)."""

from __future__ import annotations

import uuid

from oqumap import db
from oqumap import models as m
from oqumap.db import stable_id
from oqumap.services.auth import issue_token

DEMO_ORG = stable_id("org", "demo")
OTHER_ORG = stable_id("org", "other")


def user_headers(roles: list[str], org_id: str = DEMO_ORG) -> dict:
    """Create a user with exactly these roles in the currently configured test database and return auth headers."""
    with db.session_factory()() as s:
        u = m.User(org_id=org_id, username=f"t.{uuid.uuid4().hex[:10]}", display_name="Тестовый пользователь", roles=roles)
        s.add(u)
        s.commit()
        token = issue_token(s, u)
    return {"Authorization": f"Bearer {token}"}


def dataset(client, H, code: str) -> dict:
    return next(d for d in client.get("/api/v1/datasets", headers=H).json() if d["code"] == code)


def curriculum(client, H, dataset_id: str) -> dict:
    return client.get("/api/v1/curriculum", params={"dataset_id": dataset_id}, headers=H).json()


def topic(cur: dict, code: str) -> str:
    return next(t["id"] for t in cur["topics"] if t["code"] == code)


def objective(cur: dict, code: str) -> str:
    return next(o["id"] for o in cur["objectives"] if o["code"] == code)


def assessment(cur: dict, code: str) -> str:
    return next(a["id"] for a in cur["assessments"] if a["code"] == code)


def cohorts(cur: dict, letter: str) -> list[str]:
    return [c["id"] for c in cur["cohorts"] if c["code"].endswith(f"-6{letter}")]


def pilot_by_code(client, H, code: str) -> dict:
    row = next(p for p in client.get("/api/v1/pilots", headers=H).json() if p["code"] == code)
    return client.get(f"/api/v1/pilots/{row['id']}", headers=H).json()


def intervention_body(code: str, cur: dict, **kw) -> dict:
    body = {"code": code, "title_ru": f"Тестовая интервенция {code}", "title_kz": "Тест", "description_ru": "Описание",
            "grades": [6], "languages": ["ru"], "minutes_per_session": 20, "sessions_per_week": 2, "duration_weeks": 4,
            "instructions_ru": "Шаги занятия", "evidence_level": "practice_based",
            "targets": [{"target_type": "topic", "target_id": topic(cur, "T3")},
                        {"target_type": "misconception", "misconception_code": "add_across"}]}
    body.update(kw)
    return body


def items(payload) -> list:
    """List endpoints return either a list (legacy) or a page {items, total, limit, offset}."""
    return payload if isinstance(payload, list) else payload["items"]
