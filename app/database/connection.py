from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings

settings = get_settings()

engine_options = {
    "echo": settings.database_echo,
}
database_url = make_url(settings.database_url)
if database_url.drivername.startswith("postgresql"):
    engine_options.update(
        {
            "pool_pre_ping": settings.database_pool_pre_ping,
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout_seconds,
            "pool_recycle": settings.database_pool_recycle_seconds,
        }
    )

engine = create_async_engine(
    settings.database_url,
    **engine_options,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_database_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
