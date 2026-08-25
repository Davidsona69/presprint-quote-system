import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, utcnow
from app.core.config import settings
from app.models.models import Order, Quote
from app.schemas.schemas import OrderCreate, OrderResponse, OrderReceiptResponse, CostLineItem

router = APIRouter(prefix="/orders", tags=["Orders"])


async def require_staff(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    if settings.environment == "development":
        return
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Staff authorization required")


def _to_receipt(order: Order, quote: Quote) -> OrderReceiptResponse:
    return OrderReceiptResponse(
        order_id=order.id,
        status=order.status,
        created_at=order.created_at,
        client_name=order.client_name,
        client_contact=order.client_contact,
        quote_id=quote.id,
        raw_query=quote.raw_query,
        category=quote.category,
        parameters=quote.parameters or {},
        breakdown=[CostLineItem(**li) for li in quote.breakdown],
        subtotal_xaf=quote.subtotal_xaf,
        discount_xaf=quote.discount_xaf,
        rush_fee_xaf=quote.rush_fee_xaf,
        tax_xaf=quote.tax_xaf,
        total_xaf=quote.total_xaf,
    )


@router.post("", response_model=OrderReceiptResponse)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    quote = await db.get(Quote, payload.quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found — calculate a quote before placing an order")

    order = Order(
        id=str(uuid.uuid4()),
        quote_id=payload.quote_id,
        client_name=payload.client_name,
        client_contact=payload.client_contact,
        status="pending",
        created_at=utcnow(),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _to_receipt(order, quote)


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_staff),
):
    result = await db.execute(select(Order).order_by(Order.created_at.desc()))
    return result.scalars().all()


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_staff),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/{order_id}/receipt", response_model=OrderReceiptResponse)
async def get_order_receipt(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_staff),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    quote = await db.get(Quote, order.quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Underlying quote not found")
    return _to_receipt(order, quote)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_status(
    order_id: str,
    status: Literal["pending", "confirmed", "in_production", "done"],
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_staff),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = status
    await db.commit()
    await db.refresh(order)
    return order
