"""
Rule-based print-order entity extractor.

Why rule-based first: a custom spaCy/Transformer NER model needs a labeled
training set of a few hundred examples we don't have yet. This module gets
`/extract-specs` working from day one, and every query it processes (plus
staff corrections during UAT) becomes the training data for a v2 ML model
later — see nlp/train_ner.py for that upgrade path.

Swap-in point: replace `extract()` internals with a spaCy pipeline call
once you have a trained model; keep the function signature identical so
the router doesn't need to change.
"""
import re

from app.schemas.schemas import ExtractedEntities

# --- lookup tables (extend these as you learn Presprint's actual vocabulary) ---

ITEM_TYPES = ["flyer", "flyers", "poster", "posters", "business card", "business cards",
              "brochure", "brochures", "banner", "banners", "booklet", "booklets",
              "invitation", "invitations", "sticker", "stickers", "calendar", "calendars"]

PAPER_SIZES = ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "letter", "legal"]

FINISHES = ["glossy", "gloss", "matte", "matt", "uncoated", "satin"]

FINISHING_OPS = ["lamination", "laminated", "spiral binding", "binding", "stapling",
                  "folding", "die-cut", "die cut", "perforation", "embossing"]

URGENT_WORDS = ["urgent", "asap", "rush", "today", "tomorrow", "by friday", "by monday",
                 "by tuesday", "by wednesday", "by thursday", "by saturday", "by sunday",
                 "immediately", "same day"]

QUANTITY_PATTERN = re.compile(r"\b(\d{1,6})\s*(?:copies|pieces|pcs|units)?\b", re.IGNORECASE)


def _find_first(text: str, options: list[str]) -> str | None:
    for opt in options:
        if opt in text:
            return opt
    return None


def extract(raw_query: str) -> tuple[ExtractedEntities, float]:
    """
    Returns (entities, confidence_score).
    Confidence is a simple heuristic here (fraction of key fields found),
    not a model probability — good enough to gate the "needs_confirmation"
    flag in the API response until a real model replaces this.
    """
    text = raw_query.lower()

    item_type = _find_first(text, ITEM_TYPES)
    if item_type:
        item_type = item_type.rstrip("s")  # normalize plural -> singular

    qty_match = QUANTITY_PATTERN.search(text)
    quantity = int(qty_match.group(1)) if qty_match else None

    paper_size = _find_first(text, PAPER_SIZES)
    if paper_size:
        paper_size = paper_size.upper()

    finish_raw = _find_first(text, FINISHES)
    paper_finish = "glossy" if finish_raw in ("glossy", "gloss") else finish_raw

    print_side = "double" if any(w in text for w in ["double-sided", "double sided", "both sides"]) else (
        "single" if any(w in text for w in ["single-sided", "single sided", "one side"]) else None
    )

    color_mode = "black_white" if any(w in text for w in ["black and white", "b&w", "grayscale", "greyscale"]) else (
        "full_color" if any(w in text for w in ["color", "colour", "full color", "full colour"]) else None
    )

    finishing = [op for op in FINISHING_OPS if op in text]

    urgency = "high" if any(w in text for w in URGENT_WORDS) else "standard"

    entities = ExtractedEntities(
        item_type=item_type,
        quantity=quantity,
        paper_size=paper_size,
        paper_finish=paper_finish,
        print_side=print_side,
        color_mode=color_mode,
        finishing=finishing,
        urgency=urgency,
    )

    # crude confidence: fraction of the "core" fields we managed to fill
    core_fields = [item_type, quantity, paper_size, print_side, color_mode]
    confidence = sum(1 for f in core_fields if f is not None) / len(core_fields)

    return entities, round(confidence, 2)
