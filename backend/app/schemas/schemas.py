from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ---------- NLP extraction ----------

class ExtractRequest(BaseModel):
    query: str = Field(..., examples=["I need 500 copies of A4 glossy flyers, double-sided color, by Friday"])


class ExtractedEntities(BaseModel):
    item_type: str | None = None
    quantity: int | None = None
    paper_size: str | None = None
    paper_finish: str | None = None
    print_side: str | None = None       # "single" | "double"
    color_mode: str | None = None       # "full_color" | "black_white"
    finishing: list[str] = []
    urgency: str | None = None          # "standard" | "high"


class ExtractResponse(BaseModel):
    raw_query: str
    extracted_entities: ExtractedEntities
    confidence_score: float
    needs_confirmation: bool  # True if confidence < threshold; frontend should show editable form


# ---------- Cost calculation ----------

class QuoteRequest(BaseModel):
    entities: ExtractedEntities
    raw_query: str | None = None
    confidence_score: float | None = None


class CostLineItem(BaseModel):
    label: str
    amount_xaf: float


class QuoteResponse(BaseModel):
    id: str
    breakdown: list[CostLineItem]
    subtotal_xaf: float
    discount_xaf: float
    rush_fee_xaf: float
    tax_xaf: float
    total_xaf: float
    created_at: datetime


# ---------- Orders ----------

class OrderCreate(BaseModel):
    quote_id: str
    client_name: str | None = None
    client_contact: str | None = None


class OrderResponse(BaseModel):
    id: str
    quote_id: str
    client_name: str | None
    client_contact: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
