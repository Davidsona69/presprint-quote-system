"""
Feature extraction for the ML pricing model.

This module is the single definition of what a "job" looks like to the model.
Training (ml/train_pricing.py) and inference (services/ml_pricing.py) both
import it, so a model can never be trained on one feature layout and served
another — the classic way ML pipelines silently rot.

Two design choices worth knowing:

1. **The deterministic subtotal is itself a feature.** The rate matrices already
   encode the physics of the job — sheets, imposition, binding setup. Handing
   that number to the model means it only has to learn where Presprint's real
   invoices *deviate* from the rate card (negotiation, client segment, press
   scheduling), which is a far easier thing to learn from a few hundred rows
   than pricing from scratch.

2. **Missing values stay missing.** They are NaN, not zero — a book with no
   stated page count is not a 0-page book. HistGradientBoostingRegressor
   handles NaN natively, so nothing has to be imputed and no information is
   invented.

Only numpy is needed at inference time; nothing here imports pandas.
"""
from __future__ import annotations

import math
from typing import Any

# Order matters — it is baked into every saved model artifact.
NUMERIC_FEATURES: list[str] = [
    "quantity",
    "log_quantity",
    "page_count",
    "interior_gsm",
    "cover_gsm",
    "paper_gsm",
    "color_count",
    "n_placements",
    "n_finishing",
    "is_rush",
    "deterministic_subtotal",
    "log_deterministic_subtotal",
]

CATEGORICAL_FEATURES: list[str] = [
    "category",
    "item_type",
    "binding",
    "trim_size",
    "cover_finish",
    "color_mode",
    "paper_size",
    "paper_finish",
    "print_side",
    "print_method",
    "garment_size",
]

FEATURE_NAMES: list[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Index positions of the categorical columns, for the encoder.
CATEGORICAL_INDICES: list[int] = list(
    range(len(NUMERIC_FEATURES), len(FEATURE_NAMES))
)

MISSING_CATEGORY = "__missing__"


def _as_dict(spec: Any) -> dict:
    """Accept a Pydantic spec, a plain dict, or a CSV row."""
    if hasattr(spec, "model_dump"):
        return spec.model_dump()
    return dict(spec)


def _num(value: Any) -> float:
    """Numeric or NaN. Empty strings from CSV count as missing."""
    if value is None or value == "":
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _cat(value: Any) -> str:
    if value is None or value == "":
        return MISSING_CATEGORY
    return str(value).strip().lower()


def _count(value: Any) -> float:
    """Length of a list-valued field; NaN when the field is absent entirely."""
    if value is None:
        return math.nan
    if isinstance(value, str):
        # CSV round-trip: "front|back" or "front,back"
        value = [v for v in value.replace("|", ",").split(",") if v.strip()]
    try:
        return float(len(value))
    except TypeError:
        return math.nan


def feature_row(spec: Any, deterministic_subtotal: float | None) -> list:
    """
    One row of model input, in FEATURE_NAMES order.

    `deterministic_subtotal` is what the rate-matrix engine produced for this
    job. Pass None only if you genuinely have no baseline — the model will
    then have to price from scratch and will be materially worse at it.
    """
    s = _as_dict(spec)

    subtotal = _num(deterministic_subtotal)
    quantity = _num(s.get("quantity"))

    numeric = [
        quantity,
        math.log1p(quantity) if not math.isnan(quantity) else math.nan,
        _num(s.get("page_count")),
        _num(s.get("interior_gsm")),
        _num(s.get("cover_gsm")),
        _num(s.get("paper_gsm")),
        _num(s.get("color_count")),
        _count(s.get("placements")),
        _count(s.get("finishing")),
        1.0 if s.get("urgency") == "high" else 0.0,
        subtotal,
        math.log1p(subtotal) if not math.isnan(subtotal) and subtotal >= 0 else math.nan,
    ]

    categorical = [
        _cat(s.get("category")),
        _cat(s.get("item_type")),
        _cat(s.get("binding")),
        _cat(s.get("trim_size")),
        _cat(s.get("cover_finish")),
        _cat(s.get("color_mode")),
        _cat(s.get("paper_size")),
        _cat(s.get("paper_finish")),
        _cat(s.get("print_side")),
        _cat(s.get("print_method")),
        _cat(s.get("garment_size")),
    ]

    return numeric + categorical
