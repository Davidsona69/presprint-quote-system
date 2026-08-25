"""
Request/response contracts.

The system is *category-aware*: Presprint's production floor runs three
distinct lines, and each has its own spec vocabulary, its own cost matrix,
and its own 3D preview geometry.

    book       textbooks, exercise books, novels, catalogue bindings
    merch      shirts, mugs, caps, bags, umbrellas, lanyards
    benchmark  flyers, business cards, posters, booklets, banners

A Pydantic discriminated union on `category` keeps each line strictly typed
while still serialising to a single JSONB payload for storage.

Unstated parameters stay `None` on purpose — never guessed. `missing_fields`
tells the frontend exactly what to ask the user for.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["book", "merch", "benchmark"]


# ---------------------------------------------------------------- specs ----

class _SpecBase(BaseModel):
    item_type: str | None = None
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    urgency: Literal["standard", "high"] | None = None
    finishing: list[str] = Field(default_factory=list)


class BenchmarkSpec(_SpecBase):
    """Flat-sheet work: flyers, cards, posters, booklets, banners."""
    category: Literal["benchmark"] = "benchmark"

    paper_size: str | None = None       # A3 | A4 | A5 | ...
    paper_gsm: int | None = Field(default=None, ge=1, le=1000)
    paper_finish: Literal["matte", "glossy", "uncoated"] | None = None
    print_side: Literal["single", "double"] | None = None
    color_mode: Literal["full_color", "black_white"] | None = None


class BookSpec(_SpecBase):
    """Bound work. Spine thickness is derived from page count x interior GSM."""
    category: Literal["book"] = "book"

    page_count: int | None = Field(default=None, ge=1, le=10_000)
    trim_size: str | None = None        # A4 | A5 | B5
    interior_gsm: int | None = Field(default=None, ge=1, le=1000)
    cover_gsm: int | None = Field(default=None, ge=1, le=1000)
    binding: Literal["saddle_stitch", "perfect", "spiral", "case"] | None = None
    cover_finish: Literal["matte", "glossy", "uncoated"] | None = None
    color_mode: Literal["full_color", "black_white"] | None = None


class MerchSpec(_SpecBase):
    """Decorated goods. Cost = blank + decoration, not paper + ink."""
    category: Literal["merch"] = "merch"

    garment_size: str | None = None     # S | M | L | XL | XXL (garments only)
    print_method: str | None = None     # screen | dtf | sublimation | embroidery
    placements: list[str] = Field(default_factory=list)  # front | back | sleeve | wrap
    color_count: int | None = Field(default=None, ge=1, le=99)
    base_color: str | None = None


Spec = Annotated[
    Union[BenchmarkSpec, BookSpec, MerchSpec],
    Field(discriminator="category"),
]


# ------------------------------------------------------------- preview ----

class PreviewConfig(BaseModel):
    """
    Parametric description of the 3D viewport, computed server-side so the
    geometry the client renders is the same geometry the price was built
    from. Stored on the quote as JSONB for audit.
    """
    kind: str                                   # book | mug | tshirt | cap | bag | umbrella | lanyard | sheet
    dimensions_mm: dict[str, float] = Field(default_factory=dict)
    finish: str | None = None                   # matte | glossy | uncoated
    color: str | None = None                    # hex or named base colour
    placements: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)       # derivation notes, e.g. spine maths


# ------------------------------------------------------- NLP extraction ----

class ExtractRequest(BaseModel):
    query: str = Field(
        ...,
        examples=["500 A4 glossy flyers, double-sided full colour, needed by Friday"],
    )
    category: Category | None = Field(
        default=None,
        description="Pin the extraction to one production line. Omit to auto-detect.",
    )


class ExclusionNotice(BaseModel):
    """
    Guardrail for products Presprint does not quote automatically —
    writing instruments and ID cards are sourced/priced by hand.
    """
    excluded: bool = False
    matched_terms: list[str] = Field(default_factory=list)
    reason: str | None = None


class ExtractResponse(BaseModel):
    raw_query: str
    category: Category | None
    category_confidence: float
    spec: Spec | None
    confidence_score: float
    needs_confirmation: bool
    missing_fields: list[str] = Field(default_factory=list)
    exclusion: ExclusionNotice = Field(default_factory=ExclusionNotice)
    preview: PreviewConfig | None = None


# ---------------------------------------------------- cost calculation ----

class QuoteRequest(BaseModel):
    spec: Spec
    raw_query: str | None = None
    confidence_score: float | None = None


class CostLineItem(BaseModel):
    label: str
    amount_xaf: float
    detail: str | None = None       # how this line was derived, for the audit trail


class QuoteResponse(BaseModel):
    id: str
    category: Category
    breakdown: list[CostLineItem]
    subtotal_xaf: float
    discount_xaf: float
    rush_fee_xaf: float
    tax_xaf: float
    total_xaf: float
    warnings: list[str] = Field(default_factory=list)
    preview: PreviewConfig | None = None
    created_at: datetime


# -------------------------------------------------------------- orders ----

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


class OrderReceiptResponse(BaseModel):
    """Order + its underlying quote, flattened — everything a printable receipt needs."""
    order_id: str
    status: str
    created_at: datetime

    client_name: str | None
    client_contact: str | None

    quote_id: str
    raw_query: str | None
    category: Category | None
    parameters: dict[str, Any] = {}
    breakdown: list[CostLineItem]
    subtotal_xaf: float
    discount_xaf: float
    rush_fee_xaf: float
    tax_xaf: float
    total_xaf: float
