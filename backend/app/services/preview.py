"""
Parametric 3D preview builder.

The Three.js viewport in the frontend does not invent geometry — it renders
exactly what this module derives from the spec, so what the client sees on
screen is dimensionally the same job that was priced. That's the whole point
of the visual-verification feature: catching "I thought it would be bigger"
*before* the plates go on the press.

Book spine thickness in particular is a real calculation
(leaves x GSM x caliper), shared with the pricing engine — see
`pricing.book_spine_mm`.
"""
from __future__ import annotations

from app.schemas.schemas import BenchmarkSpec, BookSpec, MerchSpec, PreviewConfig, Spec
from app.services.pricing import book_spine_mm, load_matrix

# ISO/US sheet sizes in mm, portrait.
SHEET_SIZES_MM: dict[str, tuple[float, float]] = {
    "A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420),
    "A4": (210, 297), "A5": (148, 210), "A6": (105, 148), "B5": (176, 250),
    "LETTER": (216, 279), "LEGAL": (216, 356),
}

# Products whose "size" is fixed by the blank, not by the artwork.
MERCH_GEOMETRY_MM: dict[str, dict[str, float]] = {
    "mug":      {"diameter": 82,  "height": 95,  "handle_radius": 30},
    "shirt":    {"width": 520,    "height": 720, "sleeve": 200},
    "cap":      {"diameter": 180, "height": 120, "peak": 70},
    "bag":      {"width": 380,    "height": 420, "gusset": 100},
    "umbrella": {"diameter": 1050, "height": 900, "panels": 8},
    "lanyard":  {"width": 20,     "length": 900},
}

# Some benchmark products have a house size that isn't a plain ISO sheet.
BENCHMARK_HOUSE_SIZES_MM: dict[str, tuple[float, float]] = {
    "business card": (85, 55),
    "banner": (2000, 800),
}

NAMED_COLORS = {
    "white": "#F4F4F5", "black": "#1C1C1E", "navy": "#1E3A5F", "red": "#C0392B",
    "blue": "#2C6FB5", "green": "#2E7D52", "grey": "#8A8F98", "gray": "#8A8F98",
    "yellow": "#E8B93B",
}


def _color(name: str | None, fallback: str = "#F4F4F5") -> str:
    if not name:
        return fallback
    if name.startswith("#"):
        return name
    return NAMED_COLORS.get(name.lower(), fallback)


def _benchmark_preview(spec: BenchmarkSpec) -> PreviewConfig:
    notes: list[str] = []

    house = BENCHMARK_HOUSE_SIZES_MM.get((spec.item_type or "").lower())
    if house:
        w, h = house
        notes.append(f"{spec.item_type} rendered at Presprint's house size {w:g} x {h:g} mm.")
    else:
        size = (spec.paper_size or "A4").upper()
        w, h = SHEET_SIZES_MM.get(size, SHEET_SIZES_MM["A4"])
        if spec.paper_size is None:
            notes.append("No size stated — previewed at A4.")

    # Sheet thickness from GSM, so heavy card visibly reads as card.
    gsm = spec.paper_gsm or 100
    thickness = round(gsm * 0.00125, 3)
    notes.append(f"Sheet caliper {thickness} mm at {gsm} gsm.")
    if spec.print_side == "double":
        notes.append("Double-sided — the viewport lets you flip the sheet.")

    return PreviewConfig(
        kind="sheet",
        dimensions_mm={"width": w, "height": h, "thickness": thickness},
        finish=spec.paper_finish or "matte",
        color="#FFFFFF",
        placements=["front", "back"] if spec.print_side == "double" else ["front"],
        notes=notes,
    )


def _book_preview(spec: BookSpec) -> PreviewConfig:
    m = load_matrix()
    cfg = m["book"]
    d = cfg["defaults"]
    notes: list[str] = []

    trim = (spec.trim_size or d["trim_size"]).upper()
    dims = cfg["trim_sizes"].get(trim) or cfg["trim_sizes"][d["trim_size"]]
    if spec.trim_size is None:
        notes.append(f"No trim size stated — previewed at {d['trim_size']}.")

    spine = book_spine_mm(spec, m)
    pages = spec.page_count or d["page_count"]
    interior_gsm = spec.interior_gsm or d["interior_gsm"]
    notes.append(
        f"Spine {spine} mm = {pages // 2} leaves x {interior_gsm} gsm "
        f"x {cfg['caliper_mm_per_gsm']} mm/gsm, plus cover boards."
    )

    binding = spec.binding or d["binding"]
    notes.append(f"Rendered as {binding.replace('_', ' ')}.")

    return PreviewConfig(
        kind="book",
        dimensions_mm={
            "width": dims["width_mm"],
            "height": dims["height_mm"],
            "spine": spine,
        },
        finish=spec.cover_finish or d["cover_finish"],
        color="#2C3244",
        placements=["cover", "spine"],
        notes=notes,
    )


def _merch_preview(spec: MerchSpec) -> PreviewConfig:
    m = load_matrix()
    cfg = m["merch"]
    item = spec.item_type if spec.item_type in MERCH_GEOMETRY_MM else "shirt"
    notes: list[str] = []
    if spec.item_type is None:
        notes.append("No product stated — previewed as a shirt.")

    dims = dict(MERCH_GEOMETRY_MM[item])
    if item == "shirt" and spec.garment_size:
        scale = cfg["size_multipliers"].get(spec.garment_size.upper(), 1.0)
        dims = {k: round(v * scale, 1) for k, v in dims.items()}
        notes.append(f"Scaled to size {spec.garment_size.upper()} ({scale:g}x).")

    valid = cfg["valid_placements_by_item"].get(item, ["front"])
    placements = [p for p in spec.placements if p in valid] or [valid[0]]
    notes.append(f"Decoration shown on: {', '.join(placements)}.")

    return PreviewConfig(
        kind="mug" if item == "mug" else ("tshirt" if item == "shirt" else item),
        dimensions_mm=dims,
        finish=None,
        color=_color(spec.base_color),
        placements=placements,
        notes=notes,
    )


_BUILDERS = {
    "benchmark": _benchmark_preview,
    "book": _book_preview,
    "merch": _merch_preview,
}


def build_preview(spec: Spec) -> PreviewConfig:
    return _BUILDERS[spec.category](spec)
