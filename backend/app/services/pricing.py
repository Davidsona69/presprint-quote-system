"""
Deterministic pricing engine.

This is the REAL production cost calculator — not a placeholder waiting
for ML. Base costs live in pricing_matrix.json so non-engineers (e.g. the
Presprint sales team) can update rates without touching code.

If/when real historical job data exists, a regression model can plug in
here as an *adjustment multiplier* on top of this formula (see ml/README.md)
rather than replacing it — deterministic pricing is auditable, which
matters a lot more to a print shop's finance team than an ML black box.
"""
import json
from pathlib import Path

from app.schemas.schemas import CostLineItem, ExtractedEntities

MATRIX_PATH = Path(__file__).parent.parent.parent / "pricing_matrix.json"


def _load_matrix() -> dict:
    with open(MATRIX_PATH) as f:
        return json.load(f)


def calculate_quote(entities: ExtractedEntities) -> dict:
    matrix = _load_matrix()
    line_items: list[CostLineItem] = []

    quantity = entities.quantity or 1

    # 1. Base paper cost (by size + finish)
    size_key = (entities.paper_size or "A4").upper()
    finish_key = entities.paper_finish or "matte"
    paper_rate = matrix["paper_rates"].get(size_key, {}).get(finish_key, matrix["paper_rates"]["A4"]["matte"])
    paper_cost = paper_rate * quantity
    line_items.append(CostLineItem(label=f"Paper ({size_key}, {finish_key}) x{quantity}", amount_xaf=paper_cost))

    # 2. Ink / color cost
    color_rate = matrix["ink_rates"]["full_color" if entities.color_mode == "full_color" else "black_white"]
    if entities.print_side == "double":
        color_rate *= 1.8  # double-sided isn't quite 2x — shared setup cost
    ink_cost = color_rate * quantity
    line_items.append(CostLineItem(label=f"Ink/Color ({entities.color_mode or 'full_color'})", amount_xaf=ink_cost))

    # 3. Finishing options (flat + per-unit)
    finishing_cost = 0.0
    for op in entities.finishing:
        rate = matrix["finishing_rates"].get(op)
        if rate:
            cost = rate["flat"] + rate["per_unit"] * quantity
            finishing_cost += cost
            line_items.append(CostLineItem(label=f"Finishing: {op}", amount_xaf=cost))

    subtotal = paper_cost + ink_cost + finishing_cost

    # 4. Volume discount tiers
    discount_percent = 0.0
    for tier in sorted(matrix["volume_discount_tiers"], key=lambda t: t["min_quantity"]):
        max_q = tier.get("max_quantity")
        if quantity >= tier["min_quantity"] and (max_q is None or quantity <= max_q):
            discount_percent = tier["discount_percent"]
    discount_xaf = subtotal * (discount_percent / 100)

    # 5. Rush fee
    rush_fee_xaf = subtotal * matrix["rush_fee_percent"] / 100 if entities.urgency == "high" else 0.0

    # 6. Tax
    taxable_base = subtotal - discount_xaf + rush_fee_xaf
    tax_xaf = taxable_base * matrix["tax_percent"] / 100

    total = taxable_base + tax_xaf

    return {
        "breakdown": [li.model_dump() for li in line_items],
        "subtotal_xaf": round(subtotal, 2),
        "discount_xaf": round(discount_xaf, 2),
        "rush_fee_xaf": round(rush_fee_xaf, 2),
        "tax_xaf": round(tax_xaf, 2),
        "total_xaf": round(total, 2),
    }
