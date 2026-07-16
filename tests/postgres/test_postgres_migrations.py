from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import pytest


pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


def _alembic_config() -> Config:
    return Config("alembic.ini")


async def test_postgres_migrations_upgrade_head(pg_session: AsyncSession) -> None:
    result = await pg_session.execute(text("SELECT version_num FROM alembic_version"))
    current_revision = result.scalar_one()

    script = ScriptDirectory.from_config(_alembic_config())
    assert current_revision == script.get_current_head()
    assert len(script.get_heads()) == 1


async def test_postgres_extension_constraint_and_indexes_exist(
    pg_session: AsyncSession,
) -> None:
    extension = await pg_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'btree_gist'")
    )
    assert extension.scalar_one() == "btree_gist"

    exclusion = await pg_session.execute(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conname = 'excl_appointments_scheduled_time_overlap'
            AND contype = 'x'
            """
        )
    )
    assert exclusion.scalar_one() == "excl_appointments_scheduled_time_overlap"

    indexes = await pg_session.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE indexname IN (
                'uq_pending_scheduling_actions_active',
                'ix_inbound_media_analysis_kind'
            )
            """
        )
    )
    assert {row[0] for row in indexes.all()} == {
        "uq_pending_scheduling_actions_active",
        "ix_inbound_media_analysis_kind",
    }

    partial_index = await pg_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE indexname = 'uq_pending_scheduling_actions_active'
            """
        )
    )
    assert "WHERE ((status)::text = 'awaiting_confirmation'::text)" in partial_index.scalar_one()


async def test_postgres_media_image_columns_exist(pg_session: AsyncSession) -> None:
    columns = await pg_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'inbound_media'
            AND column_name IN ('analysis_kind', 'analysis_data')
            """
        )
    )
    assert {row[0] for row in columns.all()} == {"analysis_kind", "analysis_data"}


def test_postgres_last_migration_downgrade_and_upgrade_is_valid(
    migrated_postgres_url: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_postgres_url)
    config = _alembic_config()
    command.downgrade(config, "-1")
    command.upgrade(config, "head")
