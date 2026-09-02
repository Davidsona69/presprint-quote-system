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
from app.services.pricing import book_spine_mm, load_matrix, normalized_book_page_count, resolve_book_interior, normalized_book_page_count

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
    pages = normalized_book_page_count(spec, m)
    interior_gsm = spec.interior_gsm or d["interior_gsm"]
    notes.append(
        f"Spine {spine} mm = {pages // 2} leaves x {interior_gsm} gsm "
        f"x {cfg['caliper_mm_per_gsm']} mm/gsm, plus cover boards."
    )

    binding = spec.binding or d["binding"]
    notes.append(f"Rendered as {binding.replace('_', ' ')}.")

    # --- interior: work out how the text actually falls on the page --------
    interior = resolve_book_interior(spec, m)
    page_w, page_h = dims["width_mm"], dims["height_mm"]
    margin = interior["margin_mm"]
    text_w = max(page_w - 2 * margin, 10.0)
    text_h = max(page_h - 2 * margin, 10.0)

    # 1pt = 1/72 inch = 0.352778 mm.
    pt_mm = 0.352778
    line_h_mm = interior["font_size_pt"] * interior["line_spacing"] * pt_mm
    lines_per_page = max(int(text_h // line_h_mm), 1)

    # Average character advance for body text runs about 0.5 em; letter
    # spacing adds to every advance.
    char_mm = interior["font_size_pt"] * pt_mm * (0.5 + interior["letter_spacing_em"])
    chars_per_line = max(int(text_w // char_mm), 1) if char_mm > 0 else 60

    interior.update({
        "page_width_mm": page_w,
        "page_height_mm": page_h,
        "text_width_mm": round(text_w, 1),
        "text_height_mm": round(text_h, 1),
        "line_height_mm": round(line_h_mm, 2),
        "lines_per_page": lines_per_page,
        "chars_per_line": chars_per_line,
        "page_count": pages,
    })

    notes.append(
        f"Interior: {interior['typeface_label']} {interior['font_size_pt']:g}pt / "
        f"{interior['line_spacing']:g} leading, {interior['text_align']}, "
        f"{margin:g} mm margins on {interior['paper_tone_label'].lower()} stock — "
        f"about {lines_per_page} lines of ~{chars_per_line} characters per page."
    )
    if not interior["specified"]:
        notes.append("Typesetting is the shop's house style; nothing has been charged for layout.")

    # Typographers call 45-75 characters a comfortable measure.
    if chars_per_line > 90:
        notes.append(
            f"~{chars_per_line} characters per line is a wide measure — the eye loses "
            "its place returning to the next line. Wider margins or a larger size would help."
        )
    elif chars_per_line < 35:
        notes.append(
            f"~{chars_per_line} characters per line is narrow, which forces frequent "
            "hyphenation and ragged word spacing."
        )

    return PreviewConfig(
        kind="book",
        dimensions_mm={
            "width": page_w,
            "height": page_h,
            "spine": spine,
        },
        finish=spec.cover_finish or d["cover_finish"],
        color="#2C3244",
        placements=["cover", "spine", "interior"],
        notes=notes,
        interior=interior,
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
