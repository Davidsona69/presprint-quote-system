"""
Back-office: quote and order history, and export.

Every route here is behind `AdminOnly`, which fails closed — see
app/core/security.py. Nothing in this module is reachable without the key,
including the empty-result case, so a stranger cannot even confirm whether
Presprint has any orders.

Export exists because a print shop's records should not be trapped in this
application. CSV opens in Excel for the day-to-day; JSON carries the full
JSONB payloads (extracted spec, itemised breakdown, 3D config) for anything
that needs the detail — including, eventually, training data for the pricing
model, which is why the quote export keeps raw_query next to the final price.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, utcnow
from app.core.security import AdminOnly
from app.models.models import Order, Quote

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[AdminOnly])


# ------------------------------------------------------------- responses ---

class QuoteRow(BaseModel):
    id: str
    created_at: datetime
    category: str | None
    raw_query: str | None
    confidence_score: float | None
    pricing_method: str | None = None
    subtotal_xaf: float
    discount_xaf: float
    rush_fee_xaf: float
    tax_xaf: float
    total_xaf: float
    order_count: int
    parameters: dict | None = None


class OrderRow(BaseModel):
    id: str
    created_at: datetime
    status: str
    client_name: str | None
    client_contact: str | None
    quote_id: str
    category: str | None
    raw_query: str | None
    total_xaf: float


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class QuotePage(Page):
    items: list[QuoteRow]


class OrderPage(Page):
    items: list[OrderRow]


# --------------------------------------------------------------- filters ---

def _parse_day(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    d = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    return d + timedelta(days=1) if end else d


def _quote_filters(stmt: Select, category, date_from, date_to, q) -> Select:
    if category:
        stmt = stmt.where(Quote.category == category)
    if (d := _parse_day(date_from)) is not None:
        stmt = stmt.where(Quote.created_at >= d)
    if (d := _parse_day(date_to, end=True)) is not None:
        stmt = stmt.where(Quote.created_at < d)
    if q:
        stmt = stmt.where(Quote.raw_query.ilike(f"%{q.strip()}%"))
    return stmt


def _order_filters(stmt: Select, status, category, date_from, date_to, q) -> Select:
    if status:
        stmt = stmt.where(Order.status == status)
    if category:
        stmt = stmt.where(Quote.category == category)
    if (d := _parse_day(date_from)) is not None:
        stmt = stmt.where(Order.created_at >= d)
    if (d := _parse_day(date_to, end=True)) is not None:
        stmt = stmt.where(Order.created_at < d)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Order.client_name.ilike(term),
                              Order.client_contact.ilike(term),
                              Quote.raw_query.ilike(term)))
    return stmt


# ----------------------------------------------------------------- routes ---

@router.get("/session")
async def session_check():
    """Cheap endpoint the admin page calls to validate a key before storing it."""
    return {"ok": True, "checked_at": utcnow()}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    """Headline numbers for the dashboard tiles."""
    since = utcnow() - timedelta(days=30)

    quotes_total = await db.scalar(select(func.count()).select_from(Quote)) or 0
    orders_total = await db.scalar(select(func.count()).select_from(Order)) or 0
    quotes_30d = await db.scalar(
        select(func.count()).select_from(Quote).where(Quote.created_at >= since)) or 0

    # Revenue counts confirmed work only — a quote nobody accepted is not money.
    ordered_value = await db.scalar(
        select(func.coalesce(func.sum(Quote.total_xaf), 0.0))
        .select_from(Order).join(Quote, Order.quote_id == Quote.id)) or 0.0

    by_category = (await db.execute(
        select(Quote.category, func.count(), func.coalesce(func.sum(Quote.total_xaf), 0.0))
        .group_by(Quote.category))).all()

    by_status = (await db.execute(
        select(Order.status, func.count()).group_by(Order.status))).all()

    return {
        "quotes_total": quotes_total,
        "quotes_last_30_days": quotes_30d,
        "orders_total": orders_total,
        "conversion_percent": round(orders_total / quotes_total * 100, 1) if quotes_total else 0.0,
        "ordered_value_xaf": round(float(ordered_value), 2),
        "by_category": [
            {"category": c, "quotes": n, "value_xaf": round(float(v), 2)} for c, n, v in by_category
        ],
        "by_status": [{"status": s, "orders": n} for s, n in by_status],
    }


@router.get("/quotes", response_model=QuotePage)
async def list_quotes(
    db: AsyncSession = Depends(get_db),
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Quote history, newest first."""
    orders_sub = (select(Order.quote_id, func.count().label("n"))
                  .group_by(Order.quote_id).subquery())

    base = select(Quote, func.coalesce(orders_sub.c.n, 0)).join(
        orders_sub, Quote.id == orders_sub.c.quote_id, isouter=True)
    base = _quote_filters(base, category, date_from, date_to, q)

    count_stmt = _quote_filters(select(func.count()).select_from(Quote),
                                category, date_from, date_to, q)
    total = await db.scalar(count_stmt) or 0

    rows = (await db.execute(
        base.order_by(Quote.created_at.desc()).limit(limit).offset(offset))).all()

    return QuotePage(
        total=total, limit=limit, offset=offset,
        items=[QuoteRow(
            id=qt.id, created_at=qt.created_at, category=qt.category,
            raw_query=qt.raw_query, confidence_score=qt.confidence_score,
            pricing_method=(qt.parameters or {}).get("_pricing_method"),
            subtotal_xaf=qt.subtotal_xaf, discount_xaf=qt.discount_xaf,
            rush_fee_xaf=qt.rush_fee_xaf, tax_xaf=qt.tax_xaf, total_xaf=qt.total_xaf,
            order_count=n, parameters=qt.parameters,
        ) for qt, n in rows],
    )


@router.get("/orders", response_model=OrderPage)
async def list_orders(
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Order history joined to the quote that produced it."""
    base = select(Order, Quote).join(Quote, Order.quote_id == Quote.id)
    base = _order_filters(base, status, category, date_from, date_to, q)

    count_stmt = _order_filters(
        select(func.count()).select_from(Order).join(Quote, Order.quote_id == Quote.id),
        status, category, date_from, date_to, q)
    total = await db.scalar(count_stmt) or 0

    rows = (await db.execute(
        base.order_by(Order.created_at.desc()).limit(limit).offset(offset))).all()

    return OrderPage(
        total=total, limit=limit, offset=offset,
        items=[OrderRow(
            id=o.id, created_at=o.created_at, status=o.status,
            client_name=o.client_name, client_contact=o.client_contact,
            quote_id=qt.id, category=qt.category, raw_query=qt.raw_query,
            total_xaf=qt.total_xaf,
        ) for o, qt in rows],
    )



class DocumentOrder(BaseModel):
    order_id: str
    client_name: str | None
    client_contact: str | None
    status: str
    created_at: datetime


class QuoteDocument(BaseModel):
    """
    Everything needed to print one quote.

    `kind` is the whole point. A quote nobody has accepted is a *quotation* —
    an offer. Once an order exists against it, the same figures become a
    *receipt* for work that was actually bought. Printing an unaccepted quote
    on a document headed "Receipt" would tell a customer they had paid for
    something they had not ordered, so the server decides which it is rather
    than leaving it to the page.
    """
    kind: Literal["quotation", "receipt"]
    quote_id: str
    created_at: datetime
    category: str | None
    raw_query: str | None
    confidence_score: float | None
    parameters: dict | None
    breakdown: list[dict]
    warnings: list[str] | None
    subtotal_xaf: float
    discount_xaf: float
    rush_fee_xaf: float
    tax_xaf: float
    total_xaf: float
    order: DocumentOrder | None


@router.get("/quotes/{quote_id}/document", response_model=QuoteDocument)
async def quote_document(quote_id: str, db: AsyncSession = Depends(get_db)):
    """
    The printable document for any quote, ordered or not.

    Staff regularly need to hand a customer a written quotation before
    anything is confirmed, which is most quotes — so this is not restricted to
    those that became orders.
    """
    quote = await db.get(Quote, quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    order = (await db.execute(
        select(Order).where(Order.quote_id == quote_id).order_by(Order.created_at.asc())
    )).scalars().first()

    return QuoteDocument(
        kind="receipt" if order else "quotation",
        quote_id=quote.id,
        created_at=quote.created_at,
        category=quote.category,
        raw_query=quote.raw_query,
        confidence_score=quote.confidence_score,
        parameters=quote.parameters,
        breakdown=quote.breakdown or [],
        warnings=quote.warnings,
        subtotal_xaf=quote.subtotal_xaf,
        discount_xaf=quote.discount_xaf,
        rush_fee_xaf=quote.rush_fee_xaf,
        tax_xaf=quote.tax_xaf,
        total_xaf=quote.total_xaf,
        order=DocumentOrder(
            order_id=order.id, client_name=order.client_name,
            client_contact=order.client_contact, status=order.status,
            created_at=order.created_at,
        ) if order else None,
    )


# ----------------------------------------------------------------- export ---

QUOTE_COLUMNS = [
    "quote_id", "created_at", "category", "raw_query", "confidence_score",
    "subtotal_xaf", "discount_xaf", "rush_fee_xaf", "tax_xaf", "total_xaf",
    "order_count", "parameters_json", "breakdown_json", "warnings_json",
]
ORDER_COLUMNS = [
    "order_id", "created_at", "status", "client_name", "client_contact",
    "quote_id", "category", "raw_query", "subtotal_xaf", "discount_xaf",
    "rush_fee_xaf", "tax_xaf", "total_xaf", "parameters_json", "breakdown_json",
]


def _j(value) -> str:
    """JSONB column -> a single CSV-safe cell."""
    return "" if value in (None, "") else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _quote_records(db, category, date_from, date_to, q) -> list[dict]:
    orders_sub = (select(Order.quote_id, func.count().label("n"))
                  .group_by(Order.quote_id).subquery())
    stmt = select(Quote, func.coalesce(orders_sub.c.n, 0)).join(
        orders_sub, Quote.id == orders_sub.c.quote_id, isouter=True)
    stmt = _quote_filters(stmt, category, date_from, date_to, q)
    rows = (await db.execute(stmt.order_by(Quote.created_at.desc()))).all()
    return [{
        "quote_id": qt.id,
        "created_at": qt.created_at.isoformat(),
        "category": qt.category,
        "raw_query": qt.raw_query or "",
        "confidence_score": qt.confidence_score,
        "subtotal_xaf": qt.subtotal_xaf, "discount_xaf": qt.discount_xaf,
        "rush_fee_xaf": qt.rush_fee_xaf, "tax_xaf": qt.tax_xaf, "total_xaf": qt.total_xaf,
        "order_count": n,
        "parameters_json": _j(qt.parameters),
        "breakdown_json": _j(qt.breakdown),
        "warnings_json": _j(qt.warnings),
    } for qt, n in rows]


async def _order_records(db, status, category, date_from, date_to, q) -> list[dict]:
    stmt = select(Order, Quote).join(Quote, Order.quote_id == Quote.id)
    stmt = _order_filters(stmt, status, category, date_from, date_to, q)
    rows = (await db.execute(stmt.order_by(Order.created_at.desc()))).all()
    return [{
        "order_id": o.id,
        "created_at": o.created_at.isoformat(),
        "status": o.status,
        "client_name": o.client_name or "",
        "client_contact": o.client_contact or "",
        "quote_id": qt.id, "category": qt.category, "raw_query": qt.raw_query or "",
        "subtotal_xaf": qt.subtotal_xaf, "discount_xaf": qt.discount_xaf,
        "rush_fee_xaf": qt.rush_fee_xaf, "tax_xaf": qt.tax_xaf, "total_xaf": qt.total_xaf,
        "parameters_json": _j(qt.parameters),
        "breakdown_json": _j(qt.breakdown),
    } for o, qt in rows]


@router.get("/export")
async def export(
    db: AsyncSession = Depends(get_db),
    dataset: Literal["quotes", "orders"] = "quotes",
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
    status: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
):
    """
    Download the history as a file.

    Honours the same filters as the list views, so what you see on screen is
    what you get in the file. CSV for spreadsheets; JSON when the nested spec
    and cost breakdown matter.
    """
    if dataset == "quotes":
        records = await _quote_records(db, category, date_from, date_to, q)
        columns = QUOTE_COLUMNS
    else:
        records = await _order_records(db, status, category, date_from, date_to, q)
        columns = ORDER_COLUMNS

    stamp = utcnow().strftime("%Y%m%d-%H%M")
    filename = f"presprint-{dataset}-{stamp}.{fmt}"

    if fmt == "json":
        body = json.dumps(
            {"dataset": dataset, "exported_at": utcnow().isoformat(),
             "row_count": len(records), "rows": records},
            ensure_ascii=False, indent=2)
        media = "application/json"
    else:
        buf = io.StringIO()
        # utf-8-sig: Excel on Windows assumes the local codepage without a BOM
        # and mangles the XAF/accented characters in client names.
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        body = buf.getvalue()
        media = "text/csv"

    data = body.encode("utf-8-sig" if fmt == "csv" else "utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
            "X-Row-Count": str(len(records)),
        },
    )
