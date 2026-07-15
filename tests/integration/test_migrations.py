from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.db.base import Base
from app.db.migrations import upgrade_database
from app.db.models import core as _models  # noqa: F401


def test_initial_migration_matches_current_sqlalchemy_metadata(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"

    upgrade_database(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    migrated_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert migrated_tables == set(Base.metadata.tables)
    for table_name, table in Base.metadata.tables.items():
        migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert migrated_columns == set(table.columns.keys())
        migrated_indexes = {
            tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
        }
        metadata_indexes = {
            tuple(column.name for column in index.columns)
            for index in table.indexes
        }
        assert migrated_indexes == metadata_indexes
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "20260715_0002"
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()
