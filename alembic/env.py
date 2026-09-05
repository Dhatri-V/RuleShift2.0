"""Alembic environment for RuleShift.

Reads the database URL from the central config layer (core/config.py) so
that Alembic, the app, and tests all resolve the same DATABASE_URL.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from core.config import get_database_url
from database.db import Base
from database import models  # noqa: F401  (registers models on Base.metadata)

# Alembic Config object (provides access to alembic.ini values).
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at the configured database URL, overriding whatever is in
# alembic.ini so the URL is only ever managed by core/config.py.
config.set_main_option("sqlalchemy.url", get_database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()