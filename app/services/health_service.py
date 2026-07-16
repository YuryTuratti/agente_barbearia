import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ESSENTIAL_TABLES = {
    "inbound_messages",
    "outbound_messages",
    "customers",
    "services",
    "business_hours",
    "appointments",
    "appointment_services",
    "pending_scheduling_actions",
    "inbound_media",
}


async def check_database_ready(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))
    current_revision = await get_database_revision(session)
    head_revision = get_alembic_head_revision()
    if current_revision != head_revision:
        raise RuntimeError("Database migrations are not up to date.")
    missing_tables = await get_missing_essential_tables(session)
    if missing_tables:
        raise RuntimeError("Database essential tables are missing.")


async def get_database_revision(session: AsyncSession) -> str | None:
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    return result.scalar_one_or_none()


def get_alembic_head_revision() -> str:
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


async def get_missing_essential_tables(session: AsyncSession) -> set[str]:
    connection = await session.connection()

    def inspect_tables(sync_connection) -> set[str]:
        table_names = set(inspect(sync_connection).get_table_names())
        return ESSENTIAL_TABLES - table_names

    return await connection.run_sync(inspect_tables)
