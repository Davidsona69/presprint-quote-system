import pytest_asyncio

from app.core.database import engine, Base
from app.models import models  # noqa: F401 — ensure models are registered on Base


@pytest_asyncio.fixture(autouse=True)
async def _create_tables():
    """
    httpx's ASGITransport doesn't trigger FastAPI's lifespan (startup) events,
    so table creation in app.main's lifespan never runs under test. Do it
    here instead, once per test, against whatever DATABASE_URL is set.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
