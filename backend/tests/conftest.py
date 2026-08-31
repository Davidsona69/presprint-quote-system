"""
Test bootstrap.

Runs against whatever DATABASE_URL is set (CI uses the Postgres service, which
is what exercises the real JSONB columns). With nothing set, it falls back to a
throwaway SQLite file so `pytest` works on a laptop with no containers running
— the JSONB columns carry a `.with_variant(JSON, "sqlite")` for exactly this.

The env var must be set before anything imports app.core.config, which is why
it happens at the top of this file.
"""
import os
import tempfile
from pathlib import Path

if not os.environ.get("DATABASE_URL"):
    _db_file = Path(tempfile.gettempdir()) / "presprint_test.sqlite3"
    _db_file.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_file.as_posix()}"

import pytest_asyncio  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.models import models  # noqa: F401,E402 — register models on Base


@pytest_asyncio.fixture(autouse=True)
async def _create_tables():
    """
    httpx's ASGITransport doesn't trigger FastAPI's lifespan (startup) events,
    so table creation in app.main's lifespan never runs under test. Do it here
    instead, once per test.

    The dispose() on teardown matters: `engine` is a module-level singleton, but
    pytest-asyncio gives each test a fresh event loop. Pooled asyncpg
    connections stay bound to the loop that opened them, so without this every
    test after the first fails with "attached to a different loop" against
    Postgres. SQLite happens to tolerate it; CI does not.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
