from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=(settings.environment == "development"))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


async def get_db():
    """FastAPI dependency: yields a DB session per-request and closes it after."""
    async with AsyncSessionLocal() as session:
        yield session


def utcnow() -> datetime:
    """Naive UTC timestamp. `datetime.utcnow()` is deprecated; the DateTime
    columns are timezone-naive, so strip the tzinfo after converting."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
