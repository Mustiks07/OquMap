"""Test fixtures. By default tests run on a temporary SQLite file; set OQUMAP_TEST_DATABASE_URL to a PostgreSQL
URL (an empty database) to run the same suite on PostgreSQL."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

TMP = Path(tempfile.mkdtemp(prefix="oqumap-tests-"))
os.environ.setdefault("OQUMAP_STORAGE_DIR", str(TMP / "storage"))
os.environ["OQUMAP_JOB_MODE"] = "inline"
os.environ["OQUMAP_LLM_PROVIDER"] = "none"
os.environ["OQUMAP_DEPLOYMENT_MODE"] = "dev"
# generous limits for the suite; dedicated tests lower them explicitly
for _k in ("LOGIN", "IMPORT", "DOCUMENT", "AI", "ASSISTANT", "COMPUTE"):
    os.environ[f"OQUMAP_RATE_{_k}"] = "100000/60"
os.environ["OQUMAP_DEMO_TENANTS_PER_IP_PER_HOUR"] = "100000"

from oqumap import db  # noqa: E402
from oqumap.config import get_settings  # noqa: E402

get_settings.cache_clear()


def _fresh_url(name: str) -> str:
    pg = os.environ.get("OQUMAP_TEST_DATABASE_URL")
    if pg:
        admin = create_engine(pg.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "oqu_{name}"'))
            c.execute(text(f'CREATE DATABASE "oqu_{name}"'))
        admin.dispose()
        return pg.rsplit("/", 1)[0] + f"/oqu_{name}"
    return f"sqlite:///{TMP / (name + '.db')}"


def build_seeded(name: str):
    from fastapi.testclient import TestClient

    from oqumap.db import Base
    from oqumap.demo.seed import seed
    from oqumap.main import create_app

    url = _fresh_url(name)
    db.configure(url)
    if url.startswith("postgresql"):
        from alembic.config import Config

        from alembic import command

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
    else:
        from alembic.config import Config

        from alembic import command

        Base.metadata.create_all(db.engine())
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(cfg, "head")
    with db.session_factory()() as s:
        seed(s)
    return TestClient(create_app(url))


_SHARED: dict = {}


@pytest.fixture(scope="session")
def client():
    c = build_seeded("shared")
    _SHARED["engine_url"] = str(db.engine().url.render_as_string(hide_password=False))
    return c


@pytest.fixture(scope="module")
def fresh_client(request):
    """A separately seeded database for tests that mutate shared state (restores the shared DB afterwards)."""
    c = build_seeded(request.module.__name__.split(".")[-1])
    yield c
    if _SHARED.get("engine_url"):
        db.configure(_SHARED["engine_url"])


def login(client, persona="methodist"):
    r = client.post("/api/v1/auth/demo-login", json={"persona": persona})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def H(client):
    return login(client)


@pytest.fixture(scope="session")
def datasets(client, H):
    return {d["code"]: d for d in client.get("/api/v1/datasets", headers=H).json()}


@pytest.fixture(scope="session")
def curriculum(client, H, datasets):
    return client.get("/api/v1/curriculum", params={"dataset_id": datasets["base"]["id"]}, headers=H).json()
