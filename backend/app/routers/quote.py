import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, utcnow
from app.models.models import Quote
from app.schemas.schemas import CostLineItem, QuoteRequest, QuoteResponse
from app.services import preview, pricing

router = APIRouter(prefix="/calculate-quote", tags=["Cost Engine"])


@router.post("", response_model=QuoteResponse)
async def calculate_quote(payload: QuoteRequest, db: AsyncSession = Depends(get_db)):
    """
    Price a spec against its category's cost matrix and persist the result.

    The spec, the itemised breakdown and the 3D viewport state are all stored
    as JSONB so a quote can be reconstructed — and defended — months later.
    """
    result = pricing.calculate_quote(payload.spec)
    preview_config = preview.build_preview(payload.spec)

    quote = Quote(
        id=str(uuid.uuid4()),
        raw_query=payload.raw_query,
        category=payload.spec.category,
        parameters=payload.spec.model_dump(),
        preview_config=preview_config.model_dump(),
        confidence_score=payload.confidence_score or 0.0,
        breakdown=result["breakdown"],
        warnings=result["warnings"],
        subtotal_xaf=result["subtotal_xaf"],
        discount_xaf=result["discount_xaf"],
        rush_fee_xaf=result["rush_fee_xaf"],
        tax_xaf=result["tax_xaf"],
        total_xaf=result["total_xaf"],
        created_at=utcnow(),
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)

    return QuoteResponse(
        id=quote.id,
        category=result["category"],
        breakdown=[CostLineItem(**li) for li in result["breakdown"]],
        pricing_method=result["pricing_method"],
        deterministic_subtotal_xaf=result["deterministic_subtotal_xaf"],
        ml_multiplier=result["ml_multiplier"],
        subtotal_xaf=result["subtotal_xaf"],
        discount_xaf=result["discount_xaf"],
        rush_fee_xaf=result["rush_fee_xaf"],
        tax_xaf=result["tax_xaf"],
        total_xaf=result["total_xaf"],
        warnings=result["warnings"],
        preview=preview_config,
        created_at=quote.created_at,
    )
