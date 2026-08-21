"""
Category metadata.

The review-step form is generated from this endpoint rather than hardcoded in
the frontend, so adding a binding style or a merch blank means editing
pricing_matrix.json — the dropdown, the price and the 3D preview all follow.
One source of truth, which is the whole reason the matrices are decoupled.
"""
from fastapi import APIRouter

from app.services import nlp_extractor
from app.services.pricing import load_matrix

router = APIRouter(prefix="/categories", tags=["System"])


@router.get("")
async def list_categories():
    m = load_matrix()
    book, merch, bench = m["book"], m["merch"], m["benchmark"]

    return {
        "benchmark": {
            "label": "Benchmark",
            "blurb": "Flyers, business cards, posters, booklets, banners.",
            "examples": ["flyer", "business card", "poster", "booklet", "banner"],
            "required_fields": nlp_extractor.REQUIRED_FIELDS["benchmark"],
            "options": {
                "paper_size": sorted(bench["paper_rates"].keys()),
                "paper_finish": ["matte", "glossy", "uncoated"],
                "paper_gsm": sorted(int(k) for k in bench["gsm_multipliers"]),
                "print_side": ["single", "double"],
                "color_mode": ["full_color", "black_white"],
                "finishing": sorted(bench["finishing_rates"].keys()),
            },
        },
        "book": {
            "label": "Book",
            "blurb": "Textbooks, exercise books, novels, catalogue bindings.",
            "examples": ["textbook", "exercise book", "novel", "catalogue"],
            "required_fields": nlp_extractor.REQUIRED_FIELDS["book"],
            "options": {
                "item_type": ["textbook", "exercise book", "novel", "catalogue"],
                "trim_size": sorted(book["trim_sizes"].keys()),
                "interior_gsm": sorted(int(k) for k in book["interior_paper_rates_per_sheet"]),
                "cover_gsm": sorted(int(k) for k in book["cover_paper_rates_per_sheet"]),
                "binding": sorted(book["binding_rates"].keys()),
                "cover_finish": sorted(book["cover_finish_rates"].keys()),
                "color_mode": ["full_color", "black_white"],
                "finishing": sorted(book["finishing_rates"].keys()),
            },
        },
        "merch": {
            "label": "Merch",
            "blurb": "Shirts, mugs, caps, bags, umbrellas, lanyards.",
            "examples": ["shirt", "mug", "cap", "bag", "umbrella", "lanyard"],
            "required_fields": nlp_extractor.REQUIRED_FIELDS["merch"],
            "options": {
                "item_type": sorted(merch["blank_rates"].keys()),
                "garment_size": list(merch["size_multipliers"].keys()),
                "print_method": sorted(merch["print_methods"].keys()),
                "placements_by_item": merch["valid_placements_by_item"],
                "default_method_by_item": merch["default_method_by_item"],
            },
        },
        "_excluded": {
            "terms": load_matrix()["exclusions"]["terms"],
            "reason": load_matrix()["exclusions"]["reason"],
        },
    }
