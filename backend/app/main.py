from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import engine, Base
from app.routers import extract, meta, orders, preview, quote

# import models so Base.metadata knows about them before create_all
from app.models import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only. In production the schema is owned by Alembic
    # (`alembic upgrade head`) — auto-creating tables there would silently
    # diverge from the migration history.
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Category-aware print cost estimation & order extraction API for Presprint PLC.\n\n"
        "Three production lines — **book**, **merch**, **benchmark** — each with its own "
        "extraction vocabulary, cost matrix and parametric 3D preview geometry."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(extract.router)
app.include_router(preview.router)
app.include_router(quote.router)
app.include_router(orders.router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "app": settings.app_name}
