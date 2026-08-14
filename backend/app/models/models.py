"""
Core tables, matching the schema sketched in the proposal:
materials, pricing_tiers, quotes, orders (+ a finishing_options table
since lamination/binding etc. need their own cost rows).

Kept intentionally simple for an 8-week internship build — no need for
a migrations-heavy schema on day one. Use Alembic once this stabilizes.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Material(Base):
    """A paper stock, e.g. 80gsm plain, 300gsm gloss cover."""
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)          # "300gsm Gloss Cover"
    gsm: Mapped[int] = mapped_column(Integer, nullable=False)
    finish: Mapped[str] = mapped_column(String, default="matte")        # matte | glossy | uncoated
    cost_per_sheet_xaf: Mapped[float] = mapped_column(Float, nullable=False)


class FinishingOption(Base):
    """Lamination, binding, cutting, folding, etc."""
    __tablename__ = "finishing_options"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)           # "Spiral Binding"
    cost_flat_xaf: Mapped[float] = mapped_column(Float, default=0.0)    # fixed cost per job
    cost_per_unit_xaf: Mapped[float] = mapped_column(Float, default=0.0)  # cost per copy


class PricingTier(Base):
    """Volume discount tiers, e.g. 500+ copies = 10% off."""
    __tablename__ = "pricing_tiers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    min_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)


class Quote(Base):
    """A generated price quote, tied to the raw NLP query that produced it."""
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    raw_query: Mapped[str] = mapped_column(String, nullable=True)
    extracted_entities: Mapped[dict] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)   # itemized cost breakdown
    subtotal_xaf: Mapped[float] = mapped_column(Float, default=0.0)
    discount_xaf: Mapped[float] = mapped_column(Float, default=0.0)
    rush_fee_xaf: Mapped[float] = mapped_column(Float, default=0.0)
    tax_xaf: Mapped[float] = mapped_column(Float, default=0.0)
    total_xaf: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="quote")


class Order(Base):
    """A confirmed order derived from a quote (audit trail)."""
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False)
    client_name: Mapped[str] = mapped_column(String, nullable=True)
    client_contact: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | confirmed | in_production | done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    quote: Mapped["Quote"] = relationship(back_populates="orders")
