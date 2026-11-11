"""Alembic after integrating the platform branch (Claude 1) and the measurement branch (Claude 2): one head (merge
revision), clean upgrade without model drift, and upgrades of existing databases at either branch head with data."""

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
MEASUREMENT_HEAD = "b5e7f0a2d4c6"  # last revision of the measurement branch (Claude 2, round 2)
PLATFORM_HEAD = "d5085df1f375"  # last revision of the platform branch (Claude 1: demo tenants, quizzes)
HEAD = "6e837767b573"  # merge revision of both branches
NEW_TABLES = {"interventions", "intervention_versions", "intervention_targets", "pilots", "pilot_cohorts", "pilot_events",
              "fidelity_logs", "pilot_outcomes", "pilot_conclusions", "intervention_evidence", "assessment_cohorts", "pilot_sessions", "pilot_session_events"}


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


def test_single_head_is_the_merge_revision():
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


def test_upgrade_from_platform_head_keeps_quizzes_and_rate_limits():
    """A database created by the platform branch (Claude 1) with its data upgrades to the merged head."""
    url = _url("mig_platform")
    cfg = _cfg(url)
    command.upgrade(cfg, PLATFORM_HEAD)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, name, is_demo, is_ephemeral, created_at) "
                          "VALUES ('o1', 'Org', false, false, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO rate_limits (key, count, expires_at) VALUES ('login:ip:1', 3, CURRENT_TIMESTAMP)"))
    assert not NEW_TABLES & set(inspect(eng).get_table_names())
    command.upgrade(cfg, "head")
    names = set(inspect(create_engine(url)).get_table_names())
    assert NEW_TABLES <= names and {"quizzes", "quiz_versions", "rate_limits"} <= names
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count FROM rate_limits WHERE key = 'login:ip:1'")).scalar() == 3
    # the merge revision is reversible: one step down leaves both branch heads applied, upgrade returns to one head
    command.downgrade(cfg, MEASUREMENT_HEAD)  # removes only the merge revision
    with eng.connect() as conn:
        assert {r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))} == {PLATFORM_HEAD, MEASUREMENT_HEAD}
    command.upgrade(cfg, "head")
    with eng.connect() as conn:
        assert [r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))] == [HEAD]
    eng.dispose()


def test_upgrade_from_measurement_head_keeps_measurement_rows():
    """A database created by the measurement branch (Claude 2, round 2) upgrades to the merged head."""
    url = _url("mig_measure")
    cfg = _cfg(url)
    command.upgrade(cfg, MEASUREMENT_HEAD)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO organizations (id, name, is_demo, created_at) VALUES ('o1', 'Org', false, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO interventions (id, org_id, code, status, is_synthetic, created_at) "
                          "VALUES ('i1', 'o1', 'IV-1', 'active', false, CURRENT_TIMESTAMP)"))
    command.upgrade(cfg, "head")
    names = set(inspect(create_engine(url)).get_table_names())
    assert {"quizzes", "rate_limits"} <= names
    with eng.connect() as conn:
        assert conn.execute(text("SELECT code FROM interventions WHERE id = 'i1'")).scalar() == "IV-1"
        assert conn.execute(text("SELECT is_ephemeral FROM organizations WHERE id = 'o1'")).scalar() in (False, 0)
    eng.dispose()
