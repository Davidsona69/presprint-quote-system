from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import engine, Base
from app.routers import admin, extract, meta, orders, preview, quote
from app.services import ml_pricing

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
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this, a cross-origin browser can only read the handful of "simple"
    # response headers — so the back office could not see the filename the
    # server chose for an export, nor how many rows it contained.
    expose_headers=["Content-Disposition", "X-Row-Count"],
)

app.include_router(meta.router)
app.include_router(extract.router)
app.include_router(preview.router)
app.include_router(quote.router)
app.include_router(orders.router)
app.include_router(admin.router)


@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        # Which engine is pricing right now, and why. `active: false` with a
        # reason is the normal state until a model has been trained on real
        # invoices and has beaten the rate matrices.
        "pricing_model": ml_pricing.status(),
    }
