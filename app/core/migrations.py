from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.db.session import engine


SPRINT1_REVISION = "202606230001"


def migrate_database() -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

    if "alembic_version" not in tables and "users" in tables:
        command.stamp(config, SPRINT1_REVISION)

    command.upgrade(config, "head")
