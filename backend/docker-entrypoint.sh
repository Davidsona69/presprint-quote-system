#!/usr/bin/env bash
# Container start-up: bring the schema up to date, then serve.
#
# Alembic owns the schema (app.main only calls create_all in development), so
# migrations must run before the app accepts traffic. compose already gates
# this container on the database's healthcheck, but a container can still win
# the race on a cold start, so retry briefly.
set -euo pipefail

echo "[entrypoint] waiting for the database…"
for attempt in $(seq 1 30); do
  if python -c "
import asyncio, sys
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings

async def ping():
    engine = create_async_engine(settings.database_url)
    async with engine.connect():
        pass
    await engine.dispose()

try:
    asyncio.run(ping())
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "[entrypoint] database is up (attempt ${attempt})"
    break
  fi
  if [ "${attempt}" -eq 30 ]; then
    echo "[entrypoint] database never became reachable — giving up" >&2
    exit 1
  fi
  sleep 2
done

echo "[entrypoint] applying migrations…"
alembic upgrade head

echo "[entrypoint] starting API"
exec "$@"
