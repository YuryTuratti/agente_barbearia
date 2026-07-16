import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


pytestmark = pytest.mark.postgres


def _postgres_url() -> str:
    url = os.getenv("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_DATABASE_URL is not configured.")
    if os.getenv("DATABASE_URL") == url:
        pytest.fail("TEST_POSTGRES_DATABASE_URL must not match DATABASE_URL.")
    return url


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    return _postgres_url()


@pytest.fixture()
def migrated_postgres_url(postgres_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", postgres_database_url)
    get_settings.cache_clear()
    _reset_public_schema(postgres_database_url)
    command.upgrade(_alembic_config(), "head")
    yield postgres_database_url
    _reset_public_schema(postgres_database_url)
    get_settings.cache_clear()


@pytest.fixture()
async def pg_engine(migrated_postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_postgres_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
def pg_session_maker(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def pg_session(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with pg_session_maker() as session:
        yield session
        await session.rollback()


def _alembic_config() -> Config:
    return Config("alembic.ini")


def _reset_public_schema(database_url: str) -> None:
    import asyncio

    async def reset() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())


async def seed_customer_and_service(session: AsyncSession) -> tuple[str, str]:
    customer_id = str(uuid4())
    service_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (id, instance, phone, name)
            VALUES (:id, 'test-instance', '5500000000000', 'Test Customer')
            """
        ),
        {"id": customer_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO services (id, slug, name, duration_minutes, price_cents)
            VALUES (:id, :slug, 'Corte teste', 30, 5000)
            """
        ),
        {"id": service_id, "slug": f"service-{uuid4()}"},
    )
    await session.commit()
    return customer_id, service_id


async def seed_inbound_message(session: AsyncSession, *, message_id: str | None = None) -> str:
    record_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO inbound_messages (
                id, instance, message_id, message_type, status, attempts
            )
            VALUES (
                :id, 'test-instance', :message_id, 'text', 'pending', 0
            )
            """
        ),
        {"id": record_id, "message_id": message_id or str(uuid4())},
    )
    await session.commit()
    return record_id


def utc_now() -> datetime:
    return datetime.now(UTC)
