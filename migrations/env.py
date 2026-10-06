"""Alembic environment. The database path comes from DATABASE_PATH (not alembic.ini)."""

import os
from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

import jobhunter.models  # noqa: F401  (registers tables on SQLModel.metadata)
from jobhunter.db import make_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _url() -> str:
    return config.attributes.get("database_url") or (
        "sqlite:///" + (os.environ.get("DATABASE_PATH") or "/data/jobhunter.db")
    )


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
