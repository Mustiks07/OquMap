"""Alembic: the measurement revision upgrades a clean database and a database with the previous schema + data,
and the migrated schema matches the SQLAlchemy models (no drift)."""

import os
import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from oqumap.db import Base

API = Path(__file__).resolve().parents[1]
PREVIOUS = "d964e255551f"
MEASUREMENT = "c2a7e5f1b3d9"
HEAD = "f3c5d8e2a7b1"
NEW_TABLES = {"interventions", "intervention_versions", "intervention_targets", "pilots", "pilot_cohorts", "pilot_events",
              "fidelity_logs", "pilot_outcomes", "pilot_conclusions", "intervention_evidence", "assessment_cohorts"}


def _url(name: str) -> str:
    pg = os.environ.get("OQUMAP_TEST_DATABASE_URL")
    if pg:
        admin = create_engine(pg.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "oqu_{name}"'))
            c.execute(text(f'CREATE DATABASE "oqu_{name}"'))
        admin.dispose()
        return pg.rsplit("/", 1)[0] + f"/oqu_{name}"
    return f"sqlite:///{Path(tempfile.mkdtemp(prefix='oqumap-mig-')) / (name + '.db')}"


def _cfg(url: str) -> Config:
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_head_is_the_measurement_revision():
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(_cfg("sqlite://")).get_heads()
    assert heads == [HEAD]


def test_upgrade_clean_database_and_no_model_drift():
    url = _url("mig_clean")
    command.upgrade(_cfg(url), "head")
    eng = create_engine(url)
    assert NEW_TABLES <= set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
    assert diffs == [], diffs
    eng.dispose()


def test_upgrade_from_previous_schema_keeps_existing_rows():
    url = _url("mig_prev")
    cfg = _cfg(url)
    command.upgrade(cfg, PREVIOUS)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, name, is_demo, created_at) VALUES ('o1', 'Existing org', false, CURRENT_TIMESTAMP)"))
    assert not NEW_TABLES & set(inspect(eng).get_table_names())
    command.upgrade(cfg, "head")
    assert NEW_TABLES <= set(inspect(create_engine(url)).get_table_names())
    with eng.connect() as conn:
        assert conn.execute(text("SELECT name FROM organizations WHERE id = 'o1'")).scalar() == "Existing org"
    command.downgrade(cfg, PREVIOUS)
    assert not NEW_TABLES & set(inspect(create_engine(url)).get_table_names())
    eng.dispose()


def test_upgrade_from_round1_head_keeps_measurement_rows():
    """Round 2: migrate a database at the round-1 head (c2a7e5f1b3d9) with measurement data to the current head."""
    url = _url("mig_round1")
    cfg = _cfg(url)
    command.upgrade(cfg, MEASUREMENT)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, name, is_demo, created_at) VALUES ('o1', 'Org', false, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO interventions (id, org_id, code, status, is_synthetic, created_at) "
                          "VALUES ('i1', 'o1', 'IV-1', 'active', false, CURRENT_TIMESTAMP)"))
    command.upgrade(cfg, "head")
    with eng.connect() as conn:
        assert conn.execute(text("SELECT code FROM interventions WHERE id = 'i1'")).scalar() == "IV-1"
    assert "assessment_cohorts" in set(inspect(create_engine(url)).get_table_names())
    eng.dispose()
