"""
Category-aware, rule-based print-order entity extractor.

Two things happen here, in order:

  1. **Category routing** — decide which production line the request belongs
     to (book / merch / benchmark), or honour the category the user picked in
     the UI. The category then *constrains* extraction: a book request is
     never scanned for garment sizes, a mug request is never scanned for GSM.

  2. **Constrained extraction** — pull only the parameters that category
     defines. Anything not explicitly stated stays `None`. The extractor
     never guesses; `missing_fields` tells the frontend what to ask for and
     the pricing engine substitutes documented defaults instead.

An exclusion guardrail runs before both: pens, pencils, markers and ID cards
are priced by hand at Presprint and are refused by the automated workflow.

Why rule-based rather than a trained spaCy/Transformer NER: a custom model
needs a few hundred labelled examples that don't exist yet. This module works
from day one, and every query it processes (plus staff corrections during UAT)
becomes the training set for a v2 model — see nlp/train_ner.py. Keep
`extract()`'s signature identical when you swap the internals.
"""
from __future__ import annotations

import re

from app.schemas.schemas import (
    BenchmarkSpec,
    BookSpec,
    Category,
    ExclusionNotice,
    MerchSpec,
    Spec,
)
from app.services.pricing import load_matrix

# --------------------------------------------------------------- routing ---

BOOK_TERMS = ["textbook", "text book", "exercise book", "workbook", "novel",
              "catalogue", "catalog", "journal", "notebook", "manual", "yearbook",
              "magazine", "booklet binding", "book"]

MERCH_TERMS = ["t-shirt", "tshirt", "t shirt", "shirt", "polo", "jersey",
               "mug", "cup", "cap", "hat", "bag", "tote", "umbrella",
               "lanyard", "hoodie", "apron"]

BENCHMARK_TERMS = ["flyer", "leaflet", "poster", "business card", "complimentary card",
                   "brochure", "banner", "booklet", "invitation", "sticker", "label",
                   "calendar", "letterhead", "receipt book", "handbill"]

# The merch item vocabulary maps many spoken words onto six priced blanks.
MERCH_ITEM_MAP = {
    "shirt": "shirt", "t-shirt": "shirt", "tshirt": "shirt", "t shirt": "shirt",
    "polo": "shirt", "jersey": "shirt", "hoodie": "shirt", "apron": "shirt",
    "mug": "mug", "cup": "mug",
    "cap": "cap", "hat": "cap",
    "bag": "bag", "tote": "bag",
    "umbrella": "umbrella",
    "lanyard": "lanyard",
}

BOOK_ITEM_MAP = {
    "textbook": "textbook", "text book": "textbook",
    "exercise book": "exercise book", "workbook": "exercise book",
    "notebook": "exercise book",
    "novel": "novel", "yearbook": "novel",
    "catalogue": "catalogue", "catalog": "catalogue", "magazine": "catalogue",
    "journal": "catalogue", "manual": "textbook",
}

# ------------------------------------------------------ shared vocabulary ---

PAPER_SIZES = ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "b5", "letter", "legal"]

FINISHES = {"glossy": "glossy", "gloss": "glossy", "matte": "matte", "matt": "matte",
            "uncoated": "uncoated", "satin": "glossy"}

URGENT_WORDS = ["urgent", "asap", "rush", "today", "tomorrow", "immediately",
                "same day", "by friday", "by monday", "by tuesday", "by wednesday",
                "by thursday", "by saturday", "by sunday", "end of day"]

QUANTITY_PATTERN = re.compile(
    r"\b(\d{1,3}(?:[,\s]\d{3})+|\d{1,7})\s*(?:copies|copy|pieces|pcs|units|off)?\b",
    re.IGNORECASE,
)
PAGES_PATTERN = re.compile(r"\b(\d{1,4})\s*(?:pages?|pp\b|leaves)", re.IGNORECASE)
GSM_PATTERN = re.compile(r"\b(\d{2,3})\s*(?:gsm|g/m2|grams?)\b", re.IGNORECASE)
COLOR_COUNT_PATTERN = re.compile(r"\b(\d{1,2})[\s-]*(?:colou?rs?)\b", re.IGNORECASE)

# --------------------------------------------------- category vocabularies ---

BINDINGS = {
    "saddle stitch": "saddle_stitch", "saddle-stitch": "saddle_stitch",
    "saddle stitched": "saddle_stitch", "stapled": "saddle_stitch",
    "perfect bound": "perfect", "perfect binding": "perfect", "perfect": "perfect",
    "spiral": "spiral", "wire-o": "spiral", "coil": "spiral", "comb": "spiral",
    "case bound": "case", "case binding": "case", "hardcover": "case",
    "hard cover": "case", "hardback": "case",
}

PRINT_METHODS = {
    "screen print": "screen", "screen-print": "screen", "silk screen": "screen",
    "silkscreen": "screen", "screen": "screen",
    "dtf": "dtf", "direct to film": "dtf", "heat transfer": "dtf", "vinyl": "dtf",
    "sublimation": "sublimation", "sublimated": "sublimation", "dye sub": "sublimation",
    "embroidery": "embroidery", "embroidered": "embroidery", "stitched logo": "embroidery",
}

GARMENT_SIZES = {"xxl": "XXL", "2xl": "XXL", "xl": "XL", "large": "L", "medium": "M",
                 "small": "S"}

# Bare letter sizes only count next to the word "size" — otherwise every
# stray "l" or "m" in the sentence would look like a garment size.
BARE_SIZE_PATTERN = re.compile(r"\bsizes?\s+(xxl|2xl|xl|l|m|s)\b", re.IGNORECASE)

PLACEMENTS = ["front", "back", "sleeve", "side", "wrap", "panel", "chest"]

BENCHMARK_FINISHING = ["lamination", "laminated", "spiral binding", "stapling",
                       "folding", "die-cut", "die cut", "perforation", "embossing"]

BOOK_FINISHING = ["lamination", "laminated", "foiling", "foil", "embossing",
                  "die-cut", "die cut"]

FINISHING_CANON = {
    "laminated": "lamination", "die cut": "die-cut", "foil": "foiling",
}

# Fields the UI should insist on before quoting, per category.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "benchmark": ["item_type", "quantity", "paper_size", "print_side", "color_mode"],
    "book": ["item_type", "quantity", "page_count", "trim_size", "binding", "color_mode"],
    "merch": ["item_type", "quantity", "print_method", "color_count"],
}


# ------------------------------------------------------------- helpers ------

def _find_first(text: str, options) -> str | None:
    """Longest-match-first so 'business card' wins over 'card'."""
    for opt in sorted(options, key=len, reverse=True):
        if opt in text:
            return opt
    return None


def _int(raw: str) -> int:
    return int(re.sub(r"[,\s]", "", raw))


def _quantity(text: str, exclude: list[str]) -> int | None:
    """
    First number in the text that isn't already claimed by another field
    (page count, GSM, colour count).
    """
    for m in QUANTITY_PATTERN.finditer(text):
        raw = m.group(1)
        span_text = text[max(0, m.start() - 12):m.end() + 12]
        if any(tok in span_text for tok in exclude):
            continue
        return _int(raw)
    return None


def _urgency(text: str) -> str:
    return "high" if any(w in text for w in URGENT_WORDS) else "standard"


def _canon_finishing(found: list[str]) -> list[str]:
    out: list[str] = []
    for op in found:
        canon = FINISHING_CANON.get(op, op)
        if canon not in out:
            out.append(canon)
    return out


# ---------------------------------------------------------- exclusions ------

def check_exclusions(raw_query: str) -> ExclusionNotice:
    matrix = load_matrix()
    text = raw_query.lower()
    terms = matrix["exclusions"]["terms"]
    hits = [t for t in terms if re.search(rf"\b{re.escape(t)}\b", text)]
    if not hits:
        return ExclusionNotice()
    return ExclusionNotice(
        excluded=True,
        matched_terms=sorted(set(hits)),
        reason=matrix["exclusions"]["reason"],
    )


# ------------------------------------------------------ category routing ----

def detect_category(raw_query: str) -> tuple[Category | None, float]:
    """
    Returns (category, confidence). Confidence is the share of matched
    vocabulary that pointed at the winning category — a crude but honest
    signal that the UI surfaces rather than hiding.
    """
    text = raw_query.lower()

    scores: dict[str, int] = {
        "book": sum(1 for t in BOOK_TERMS if t in text),
        "merch": sum(1 for t in MERCH_TERMS if t in text),
        "benchmark": sum(1 for t in BENCHMARK_TERMS if t in text),
    }
    # "booklet" is a benchmark product, not a book — don't let "book" claim it.
    if "booklet" in text:
        scores["book"] = max(0, scores["book"] - 1)

    total = sum(scores.values())
    if total == 0:
        return None, 0.0

    winner = max(scores, key=lambda k: scores[k])
    return winner, round(scores[winner] / total, 2)  # type: ignore[return-value]


# ------------------------------------------------- per-category extraction ---

def _extract_benchmark(text: str) -> BenchmarkSpec:
    item = _find_first(text, BENCHMARK_TERMS)
    if item:
        item = item.rstrip("s") if item.endswith("s") else item

    size = _find_first(text, PAPER_SIZES)
    gsm_m = GSM_PATTERN.search(text)
    finish_raw = _find_first(text, FINISHES.keys())

    print_side = (
        "double" if any(w in text for w in ["double-sided", "double sided", "both sides", "duplex"])
        else "single" if any(w in text for w in ["single-sided", "single sided", "one side", "simplex"])
        else None
    )
    color_mode = (
        "black_white" if any(w in text for w in ["black and white", "black & white", "b&w", "grayscale", "greyscale", "monochrome"])
        else "full_color" if any(w in text for w in ["full color", "full colour", "color", "colour", "cmyk"])
        else None
    )

    return BenchmarkSpec(
        item_type=item,
        quantity=_quantity(text, exclude=["gsm", "g/m2", "page", "colour", "color"]),
        paper_size=size.upper() if size else None,
        paper_gsm=_int(gsm_m.group(1)) if gsm_m else None,
        paper_finish=FINISHES.get(finish_raw) if finish_raw else None,
        print_side=print_side,
        color_mode=color_mode,
        finishing=_canon_finishing([op for op in BENCHMARK_FINISHING if op in text]),
        urgency=_urgency(text),
    )


def _extract_book(text: str) -> BookSpec:
    item_key = _find_first(text, BOOK_ITEM_MAP.keys())
    pages_m = PAGES_PATTERN.search(text)

    trim = _find_first(text, ["a4", "a5", "a6", "b5"])

    # Two GSM figures usually means "interior gsm ... cover gsm".
    gsms = [_int(m.group(1)) for m in GSM_PATTERN.finditer(text)]
    interior_gsm = cover_gsm = None
    if len(gsms) == 1:
        # A single figure above 150 almost always refers to the cover board.
        if gsms[0] >= 150:
            cover_gsm = gsms[0]
        else:
            interior_gsm = gsms[0]
    elif len(gsms) >= 2:
        interior_gsm, cover_gsm = min(gsms), max(gsms)

    binding_key = _find_first(text, BINDINGS.keys())
    finish_raw = _find_first(text, FINISHES.keys())

    color_mode = (
        "black_white" if any(w in text for w in ["black and white", "black & white", "b&w", "grayscale", "greyscale", "monochrome"])
        else "full_color" if any(w in text for w in ["full color", "full colour", "color", "colour", "cmyk"])
        else None
    )

    return BookSpec(
        item_type=BOOK_ITEM_MAP.get(item_key) if item_key else None,
        quantity=_quantity(text, exclude=["gsm", "g/m2", "page", "pp", "leaves"]),
        page_count=_int(pages_m.group(1)) if pages_m else None,
        trim_size=trim.upper() if trim else None,
        interior_gsm=interior_gsm,
        cover_gsm=cover_gsm,
        binding=BINDINGS.get(binding_key) if binding_key else None,
        cover_finish=FINISHES.get(finish_raw) if finish_raw else None,
        color_mode=color_mode,
        finishing=_canon_finishing([op for op in BOOK_FINISHING if op in text]),
        urgency=_urgency(text),
    )


def _extract_merch(text: str) -> MerchSpec:
    item_key = _find_first(text, MERCH_ITEM_MAP.keys())
    item = MERCH_ITEM_MAP.get(item_key) if item_key else None

    method_key = _find_first(text, PRINT_METHODS.keys())
    colors_m = COLOR_COUNT_PATTERN.search(text)

    size = None
    bare = BARE_SIZE_PATTERN.search(text)
    if bare:
        token = bare.group(1).lower()
        size = GARMENT_SIZES.get(token, token.upper())
    else:
        for token, canon in GARMENT_SIZES.items():
            if re.search(rf"\b{re.escape(token)}\b", text):
                size = canon
                break

    placements = [p for p in PLACEMENTS if re.search(rf"\b{p}\b", text)]
    placements = ["front" if p == "chest" else p for p in placements]

    base_color = None
    for c in ["white", "black", "navy", "red", "blue", "green", "grey", "gray", "yellow"]:
        if re.search(rf"\b{c}\b", text):
            base_color = c
            break

    return MerchSpec(
        item_type=item,
        quantity=_quantity(text, exclude=["colour", "color", "size"]),
        garment_size=size,
        print_method=PRINT_METHODS.get(method_key) if method_key else None,
        placements=list(dict.fromkeys(placements)),
        color_count=_int(colors_m.group(1)) if colors_m else None,
        base_color=base_color,
        finishing=[],
        urgency=_urgency(text),
    )


_EXTRACTORS = {
    "benchmark": _extract_benchmark,
    "book": _extract_book,
    "merch": _extract_merch,
}


# ------------------------------------------------------------- public -------

def missing_fields(spec: Spec) -> list[str]:
    """Required-but-unstated parameters for this spec's category."""
    data = spec.model_dump()
    return [f for f in REQUIRED_FIELDS[spec.category] if not data.get(f)]


def extract(
    raw_query: str,
    category: Category | None = None,
) -> tuple[Category | None, float, Spec | None, float]:
    """
    Returns (category, category_confidence, spec, field_confidence).

    Pass `category` to pin extraction to a line the user picked in the UI —
    that always wins over auto-detection, and auto-detection is then reported
    with full confidence because there was nothing to guess.

    Field confidence is the fraction of that category's *required* fields the
    extractor managed to fill — a heuristic, not a model probability. It gates
    the `needs_confirmation` flag until a trained model replaces this.
    """
    text = raw_query.lower()

    if category is not None:
        cat_confidence = 1.0
    else:
        category, cat_confidence = detect_category(raw_query)

    if category is None:
        return None, 0.0, None, 0.0

    spec: Spec = _EXTRACTORS[category](text)

    required = REQUIRED_FIELDS[category]
    filled = len(required) - len(missing_fields(spec))
    field_confidence = round(filled / len(required), 2)

    return category, cat_confidence, spec, field_confidence
