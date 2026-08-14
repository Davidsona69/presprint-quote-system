import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Quote
from app.schemas.schemas import QuoteRequest, QuoteResponse, CostLineItem
from app.services import pricing

router = APIRouter(prefix="/calculate-quote", tags=["Cost Engine"])


@router.post("", response_model=QuoteResponse)
async def calculate_quote(payload: QuoteRequest, db: AsyncSession = Depends(get_db)):
    result = pricing.calculate_quote(payload.entities)

    quote = Quote(
        id=str(uuid.uuid4()),
        raw_query=payload.raw_query,
        extracted_entities=payload.entities.model_dump(),
        confidence_score=payload.confidence_score or 0.0,
        breakdown=result["breakdown"],
        total_xaf=result["total_xaf"],
        created_at=datetime.utcnow(),
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)

    return QuoteResponse(
        id=quote.id,
        breakdown=[CostLineItem(**li) for li in result["breakdown"]],
        subtotal_xaf=result["subtotal_xaf"],
        discount_xaf=result["discount_xaf"],
        rush_fee_xaf=result["rush_fee_xaf"],
        tax_xaf=result["tax_xaf"],
        total_xaf=result["total_xaf"],
        created_at=quote.created_at,
    )
