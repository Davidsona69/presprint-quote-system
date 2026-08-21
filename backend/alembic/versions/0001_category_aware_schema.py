"""Category-aware schema with JSONB parameter, breakdown and preview payloads.

Creates the full schema in one revision: materials, finishing_options,
pricing_tiers, quotes, orders. Quotes carry `category` plus three JSONB
columns so each production line can evolve its own parameter vocabulary
without a migration per field.

Revision ID: 0001
Revises:
Create Date: 2026-08-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("gsm", sa.Integer(), nullable=False),
        sa.Column("finish", sa.String(), nullable=True),
        sa.Column("cost_per_sheet_xaf", sa.Float(), nullable=False),
    )

    op.create_table(
        "finishing_options",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("cost_flat_xaf", sa.Float(), nullable=True),
        sa.Column("cost_per_unit_xaf", sa.Float(), nullable=True),
    )

    op.create_table(
        "pricing_tiers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("min_quantity", sa.Integer(), nullable=False),
        sa.Column("max_quantity", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Float(), nullable=True),
    )

    op.create_table(
        "quotes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("raw_query", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("parameters", JSONType, nullable=False),
        sa.Column("preview_config", JSONType, nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("breakdown", JSONType, nullable=False),
        sa.Column("warnings", JSONType, nullable=True),
        sa.Column("subtotal_xaf", sa.Float(), nullable=True),
        sa.Column("discount_xaf", sa.Float(), nullable=True),
        sa.Column("rush_fee_xaf", sa.Float(), nullable=True),
        sa.Column("tax_xaf", sa.Float(), nullable=True),
        sa.Column("total_xaf", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_quotes_category", "quotes", ["category"])

    op.create_table(
        "orders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("quote_id", sa.String(), sa.ForeignKey("quotes.id"), nullable=False),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("client_contact", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_index("ix_quotes_category", table_name="quotes")
    op.drop_table("quotes")
    op.drop_table("pricing_tiers")
    op.drop_table("finishing_options")
    op.drop_table("materials")
