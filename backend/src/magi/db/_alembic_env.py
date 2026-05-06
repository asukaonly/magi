"""Shared Alembic env.py logic for Magi migration environments.

Each environment under ``magi/db/migrations/<name>`` has a thin
``env.py`` that delegates to ``run_migrations`` here. We avoid the
default ``logging.config.fileConfig`` setup because the magi runtime
already configures structured logging — Alembic's logs flow through
the same pipeline via ``magi.core.logger``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool


def run_migrations() -> None:
    config = context.config

    if context.is_offline_mode():
        url = config.get_main_option("sqlalchemy.url")
        context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
