from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from shop.infrastructure.sql.tables import metadata
from tests.postgres.conftest import alembic_config


def test_the_migration_matches_the_table_definitions(migrated_url: str) -> None:
    """If someone edits tables.py without a migration (or the reverse) this fails."""
    engine = create_engine(migrated_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)
    engine.dispose()

    assert diff == []


def test_downgrade_and_upgrade_are_symmetric(database_url: str, migrated_url: str) -> None:
    config = alembic_config(database_url)
    engine = create_engine(database_url)

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()

    command.upgrade(config, "head")
    assert {"orders", "order_lines", "outbox"} <= set(inspect(engine).get_table_names())
    engine.dispose()
