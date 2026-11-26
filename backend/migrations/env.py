"""Alembic environment. Uses DATABASE_URL, or local SQLite by default."""

from alembic import context
from sqlalchemy import create_engine, pool

from core import config as app_config
from core import models  # noqa: F401  (registers tables on Base.metadata)
from core.database import Base

target_metadata = Base.metadata


def _url() -> str:
    url = app_config.database_url()
    if url is None:
        raise RuntimeError("Set DATABASE_URL to run migrations on a serverless deployment.")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
