from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from oqumap import models  # noqa: F401  (register tables)
from oqumap.config import get_settings
from oqumap.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render custom column types as plain SQLAlchemy types in migrations."""
    from oqumap.db import TZDateTime

    if type_ == "type" and isinstance(obj, TZDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          compare_type=True, render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
