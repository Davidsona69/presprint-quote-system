"""
Deterministic multi-matrix pricing engine.

This is the REAL production cost calculator — not a placeholder waiting for
ML. Each production line gets its own cost matrix because their economics are
genuinely different:

    benchmark   paper (size x finish x gsm) + ink (sides) + finishing
    book        interior sheets + interior ink/page + cover + binding + lamination
    merch       blank goods + decoration (method x colours x placements) + setup

All three then share one tail: volume discount -> rush fee -> tax.

Rates live in pricing_matrix.json so non-engineers (the Presprint sales team)
can update them without touching code. If/when real historical job data
exists, a regression model can plug in here as an *adjustment multiplier* on
top of these formulas (see ml/README.md) rather than replacing them —
deterministic pricing is auditable, which matters far more to a print shop's
finance team than an ML black box.

Every line item carries a `detail` string explaining how it was derived, so a
quote can be defended line by line during UAT.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.schemas.schemas import BenchmarkSpec, BookSpec, CostLineItem, MerchSpec, Spec
from app.services import ml_pricing

# PRICING_MATRIX_PATH lets a deployment mount the matrix as a config volume, so
# staff can change rates without rebuilding the image. Defaults to the copy
# shipped alongside the app.
MATRIX_PATH = (
    Path(settings.pricing_matrix_path)
    if settings.pricing_matrix_path
    else Path(__file__).parent.parent.parent / "pricing_matrix.json"
)


@lru_cache(maxsize=1)
def _cached_matrix(mtime: float) -> dict:
    # Explicit encoding — the matrix contains typographic dashes, and Windows
    # would otherwise decode it with the locale codepage and mangle them.
    with open(MATRIX_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_matrix() -> dict:
    """
    Reload whenever the file changes on disk, so staff can edit rates during
    UAT without restarting the API — but don't re-parse JSON on every request.
    """
    return _cached_matrix(MATRIX_PATH.stat().st_mtime)


def _nearest_key(table: dict, value: float) -> str:
    """Pick the closest numeric key in a rate table (e.g. GSM buckets)."""
    return min(table, key=lambda k: abs(float(k) - value))


# ------------------------------------------------------------- benchmark ---

def _price_benchmark(spec: BenchmarkSpec, m: dict) -> tuple[list[CostLineItem], list[str]]:
    cfg = m["benchmark"]
    items: list[CostLineItem] = []
    warnings: list[str] = []
    qty = spec.quantity or 1

    size = (spec.paper_size or "A4").upper()
    if size not in cfg["paper_rates"]:
        warnings.append(f"No rate for size {size}; priced as A4.")
        size = "A4"
    finish = spec.paper_finish or "matte"
    if finish not in cfg["paper_rates"][size]:
        finish = "matte"

    base_rate = cfg["paper_rates"][size][finish]
    gsm_mult = 1.0
    if spec.paper_gsm:
        gsm_mult = cfg["gsm_multipliers"][_nearest_key(cfg["gsm_multipliers"], spec.paper_gsm)]

    paper_cost = base_rate * gsm_mult * qty
    items.append(CostLineItem(
        label=f"Paper — {size} {finish}" + (f", {spec.paper_gsm}gsm" if spec.paper_gsm else ""),
        amount_xaf=round(paper_cost, 2),
        detail=f"{base_rate} XAF/sheet x {gsm_mult:g} gsm factor x {qty}",
    ))

    color_mode = spec.color_mode or "full_color"
    ink_rate = cfg["ink_rates"][color_mode]
    sides_mult = cfg["double_sided_multiplier"] if spec.print_side == "double" else 1.0
    ink_cost = ink_rate * sides_mult * qty
    items.append(CostLineItem(
        label=f"Ink — {color_mode.replace('_', ' ')}, {spec.print_side or 'single'}-sided",
        amount_xaf=round(ink_cost, 2),
        detail=f"{ink_rate} XAF/side x {sides_mult:g} sides factor x {qty}",
    ))

    for op in spec.finishing:
        rate = cfg["finishing_rates"].get(op)
        if not rate:
            warnings.append(f"No rate for finishing option '{op}'; excluded from this quote.")
            continue
        cost = rate["flat"] + rate["per_unit"] * qty
        items.append(CostLineItem(
            label=f"Finishing — {op}",
            amount_xaf=round(cost, 2),
            detail=f"{rate['flat']} setup + {rate['per_unit']} x {qty}",
        ))

    return items, warnings


# ------------------------------------------------------------------ book ---

def book_spine_mm(spec: BookSpec, m: dict) -> float:
    """
    Spine thickness = leaves x sheet caliper. Shared with the 3D preview so
    the model on screen is the model that was quoted.
    """
    cfg = m["book"]
    d = cfg["defaults"]
    pages = normalized_book_page_count(spec, m)
    interior_gsm = spec.interior_gsm or d["interior_gsm"]
    cover_gsm = spec.cover_gsm or d["cover_gsm"]

    leaves = math.ceil(pages / 2)
    caliper = cfg["caliper_mm_per_gsm"]
    return round(leaves * interior_gsm * caliper + 2 * cover_gsm * caliper, 2)


def normalized_book_page_count(spec: BookSpec, m: dict) -> int:
    """Return the press-ready page count shared by pricing and preview."""
    pages = spec.page_count or m["book"]["defaults"]["page_count"]
    return math.ceil(pages / 4) * 4


def _price_book(spec: BookSpec, m: dict) -> tuple[list[CostLineItem], list[str]]:
    cfg = m["book"]
    d = cfg["defaults"]
    items: list[CostLineItem] = []
    warnings: list[str] = []
    qty = spec.quantity or 1

    pages = normalized_book_page_count(spec, m)
    if spec.page_count is None:
        warnings.append(f"Page count not stated; priced at the {d['page_count']}-page default.")
    elif pages != spec.page_count:
        warnings.append(f"Presses impose in 4-page signatures — {spec.page_count}pp rounded up to {pages}pp.")

    trim = (spec.trim_size or d["trim_size"]).upper()
    if trim not in cfg["trim_sizes"]:
        warnings.append(f"No trim size {trim}; priced as {d['trim_size']}.")
        trim = d["trim_size"]
    up = cfg["trim_sizes"][trim]["up"]

    # 1. Interior paper — leaves imposed 'up' to a press sheet.
    interior_gsm = spec.interior_gsm or d["interior_gsm"]
    sheet_rate = cfg["interior_paper_rates_per_sheet"][
        _nearest_key(cfg["interior_paper_rates_per_sheet"], interior_gsm)
    ]
    leaves = math.ceil(pages / 2)
    sheets_per_copy = math.ceil(leaves / up)
    interior_paper = sheet_rate * sheets_per_copy * qty
    items.append(CostLineItem(
        label=f"Interior paper — {interior_gsm}gsm, {pages}pp {trim}",
        amount_xaf=round(interior_paper, 2),
        detail=f"{sheets_per_copy} sheets/copy ({leaves} leaves, {up}-up) x {sheet_rate} XAF x {qty}",
    ))

    # 2. Interior ink — per printed page.
    color_mode = spec.color_mode or d["color_mode"]
    page_ink = cfg["interior_ink_rates_per_page"][color_mode]
    interior_ink = page_ink * pages * qty
    items.append(CostLineItem(
        label=f"Interior printing — {color_mode.replace('_', ' ')}",
        amount_xaf=round(interior_ink, 2),
        detail=f"{page_ink} XAF/page x {pages}pp x {qty}",
    ))

    # 3. Cover — board + full-colour cover printing.
    cover_gsm = spec.cover_gsm or d["cover_gsm"]
    cover_rate = cfg["cover_paper_rates_per_sheet"][
        _nearest_key(cfg["cover_paper_rates_per_sheet"], cover_gsm)
    ]
    cover_ink = cfg["cover_ink_rates_per_copy"]["full_color"]
    cover_cost = (cover_rate + cover_ink) * qty
    items.append(CostLineItem(
        label=f"Cover — {cover_gsm}gsm board, full colour",
        amount_xaf=round(cover_cost, 2),
        detail=f"({cover_rate} board + {cover_ink} print) x {qty}",
    ))

    # 4. Binding — validated against the page count it can physically take.
    binding = spec.binding or d["binding"]
    rate = cfg["binding_rates"].get(binding)
    if rate is None:
        warnings.append(f"Unknown binding '{binding}'; priced as {d['binding']}.")
        binding = d["binding"]
        rate = cfg["binding_rates"][binding]
    if rate.get("max_pages") and pages > rate["max_pages"]:
        warnings.append(
            f"{binding.replace('_', ' ')} binding tops out at {rate['max_pages']}pp — "
            f"{pages}pp will need a different binding. Confirm with production."
        )
    if rate.get("min_pages") and pages < rate["min_pages"]:
        warnings.append(
            f"{binding.replace('_', ' ')} binding needs at least {rate['min_pages']}pp "
            f"to hold a spine; {pages}pp may not bind cleanly."
        )
    binding_cost = rate["flat"] + rate["per_unit"] * qty
    items.append(CostLineItem(
        label=f"Binding — {binding.replace('_', ' ')}",
        amount_xaf=round(binding_cost, 2),
        detail=f"{rate['flat']} setup + {rate['per_unit']} x {qty}",
    ))

    # 5. Cover finish (lamination).
    cover_finish = spec.cover_finish or d["cover_finish"]
    fin = cfg["cover_finish_rates"].get(cover_finish)
    if fin and (fin["flat"] or fin["per_unit"]):
        cost = fin["flat"] + fin["per_unit"] * qty
        items.append(CostLineItem(
            label=f"Cover finish — {cover_finish} lamination",
            amount_xaf=round(cost, 2),
            detail=f"{fin['flat']} setup + {fin['per_unit']} x {qty}",
        ))

    # 6. Extra finishing.
    for op in spec.finishing:
        r = cfg["finishing_rates"].get(op)
        if not r:
            warnings.append(f"No rate for finishing option '{op}'; excluded from this quote.")
            continue
        cost = r["flat"] + r["per_unit"] * qty
        items.append(CostLineItem(
            label=f"Finishing — {op}",
            amount_xaf=round(cost, 2),
            detail=f"{r['flat']} setup + {r['per_unit']} x {qty}",
        ))

    return items, warnings


# ----------------------------------------------------------------- merch ---

def _price_merch(spec: MerchSpec, m: dict) -> tuple[list[CostLineItem], list[str]]:
    cfg = m["merch"]
    d = cfg["defaults"]
    items: list[CostLineItem] = []
    warnings: list[str] = []
    qty = spec.quantity or 1

    item = spec.item_type or "shirt"
    if item not in cfg["blank_rates"]:
        warnings.append(f"No blank rate for '{item}'; priced as a shirt.")
        item = "shirt"

    # 1. Blank goods.
    blank_rate = cfg["blank_rates"][item]
    size_mult = 1.0
    if spec.garment_size and item == "shirt":
        size_mult = cfg["size_multipliers"].get(spec.garment_size.upper(), 1.0)
    blank_cost = blank_rate * size_mult * qty
    items.append(CostLineItem(
        label=f"Blank {item}" + (f" — size {spec.garment_size}" if spec.garment_size and item == "shirt" else ""),
        amount_xaf=round(blank_cost, 2),
        detail=f"{blank_rate} XAF x {size_mult:g} size factor x {qty}",
    ))

    # 2. Decoration.
    method = spec.print_method or cfg["default_method_by_item"].get(item, "screen")
    if spec.print_method is None:
        warnings.append(f"Print method not stated; priced as {method} (standard for {item}).")
    mcfg = cfg["print_methods"].get(method)
    if mcfg is None:
        warnings.append(f"Unknown print method '{method}'; priced as screen printing.")
        method, mcfg = "screen", cfg["print_methods"]["screen"]

    colors = spec.color_count or d["color_count"]
    if colors > mcfg["max_colors"]:
        warnings.append(
            f"{method} supports up to {mcfg['max_colors']} colours; "
            f"{colors} requested — confirm artwork with production."
        )

    valid = cfg["valid_placements_by_item"].get(item, ["front"])
    placements = [p for p in spec.placements if p in valid] or [valid[0]]
    dropped = [p for p in spec.placements if p not in valid]
    if dropped:
        warnings.append(f"Placement(s) {', '.join(dropped)} aren't available on a {item}; ignored.")

    setup = mcfg["setup_per_color_per_placement"] * colors * len(placements)
    if setup:
        items.append(CostLineItem(
            label=f"{method.title()} setup — {colors} colour(s) x {len(placements)} placement(s)",
            amount_xaf=round(setup, 2),
            detail=f"{mcfg['setup_per_color_per_placement']} XAF/screen x {colors} x {len(placements)}",
        ))

    per_unit = (
        mcfg["per_unit_per_color_per_placement"] * colors * len(placements)
        + mcfg["per_unit_per_placement"] * len(placements)
    )
    decoration = per_unit * qty
    items.append(CostLineItem(
        label=f"Decoration — {method}, {', '.join(placements)}",
        amount_xaf=round(decoration, 2),
        detail=f"{round(per_unit, 2)} XAF/unit x {qty}",
    ))

    return items, warnings


# ------------------------------------------------------------ public API ---

_ENGINES = {
    "benchmark": _price_benchmark,
    "book": _price_book,
    "merch": _price_merch,
}


def calculate_quote(spec: Spec) -> dict:
    """Route to the category's cost engine, then apply the shared tail."""
    m = load_matrix()
    common = m["common"]

    line_items, warnings = _ENGINES[spec.category](spec, m)
    deterministic_subtotal = sum(li.amount_xaf for li in line_items)
    subtotal = deterministic_subtotal
    qty = spec.quantity or 1

    # Optional learned adjustment. The deterministic line items stay exactly as
    # they are — the model corrects the *total* to match what Presprint has
    # historically charged, and that correction is shown as its own line so the
    # quote is still explainable. Returns None whenever no trustworthy model is
    # loaded, which is the default.
    pricing_method = "deterministic"
    ml_multiplier = None
    adjustment = ml_pricing.adjust(spec, deterministic_subtotal)
    if adjustment:
        warnings.extend(adjustment["warnings"])
        if adjustment["applied"]:
            subtotal = adjustment["subtotal_xaf"]
            ml_multiplier = adjustment["multiplier"]
            pricing_method = "ml_adjusted"
            delta = round(subtotal - deterministic_subtotal, 2)
            line_items.append(CostLineItem(
                label=f"Market adjustment ({ml_multiplier:.2f}x)",
                amount_xaf=delta,
                detail=(f"learned from historical invoices; rate-card subtotal "
                        f"{deterministic_subtotal:,.0f} XAF"),
            ))

    # Volume discount — highest matching tier wins.
    discount_percent = 0.0
    for tier in sorted(common["volume_discount_tiers"], key=lambda t: t["min_quantity"]):
        max_q = tier.get("max_quantity")
        if qty >= tier["min_quantity"] and (max_q is None or qty <= max_q):
            discount_percent = tier["discount_percent"]
    discount_xaf = subtotal * discount_percent / 100

    rush_fee_xaf = subtotal * common["rush_fee_percent"] / 100 if spec.urgency == "high" else 0.0

    taxable_base = subtotal - discount_xaf + rush_fee_xaf
    tax_xaf = taxable_base * common["tax_percent"] / 100
    total = taxable_base + tax_xaf

    return {
        "category": spec.category,
        "breakdown": [li.model_dump() for li in line_items],
        "pricing_method": pricing_method,
        "deterministic_subtotal_xaf": round(deterministic_subtotal, 2),
        "ml_multiplier": ml_multiplier,
        "subtotal_xaf": round(subtotal, 2),
        "discount_xaf": round(discount_xaf, 2),
        "rush_fee_xaf": round(rush_fee_xaf, 2),
        "tax_xaf": round(tax_xaf, 2),
        "total_xaf": round(total, 2),
        "warnings": warnings,
    }
