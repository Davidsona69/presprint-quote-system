"""
Generate a synthetic invoice CSV — FOR TESTING THE PIPELINE ONLY.

    python ml/generate_synthetic.py --rows 400 --out ml/data/synthetic.csv

READ THIS BEFORE YOU USE THE OUTPUT FOR ANYTHING
------------------------------------------------
These invoices are invented. They are produced by taking the rate matrices and
applying a *known* distortion — a client-segment discount, a rush premium, a
small-order surcharge, and some noise. So a model trained on them will learn
that distortion and score well, which proves the plumbing works and proves
nothing whatsoever about how the system prices real jobs.

Use it to check that training runs, the artifact loads, and the API picks the
model up. Then delete it and train on Presprint's actual invoices. Do not put
numbers derived from this file in your report.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

# The feature definition and the pricing engine both live in the backend, so a
# model can never be trained on a different layout than the API serves. Look
# for it beside this repo (host) or at /app (inside the backend container —
# which is where you should train, so the pickled model matches the numpy and
# scikit-learn the API will unpickle it with).
for _candidate in (Path(__file__).resolve().parent.parent / "backend", Path("/app")):
    if (_candidate / "app" / "services" / "ml_features.py").exists():
        sys.path.insert(0, str(_candidate))
        break
else:  # pragma: no cover
    raise SystemExit("Cannot find the backend package (expected ../backend or /app).")

from app.schemas.schemas import BenchmarkSpec, BookSpec, MerchSpec  # noqa: E402
from app.services.pricing import calculate_quote  # noqa: E402

FIELDS = [
    "category", "item_type", "quantity", "page_count", "trim_size", "interior_gsm",
    "cover_gsm", "binding", "cover_finish", "color_mode", "paper_size", "paper_gsm",
    "paper_finish", "print_side", "print_method", "color_count", "garment_size",
    "placements", "finishing", "urgency", "final_price_xaf",
]


def _book(rng: random.Random) -> BookSpec:
    return BookSpec(
        item_type=rng.choice(["novel", "textbook", "exercise book", "catalogue"]),
        quantity=rng.choice([50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000]),
        page_count=rng.choice([32, 48, 64, 96, 128, 160, 200, 240, 320]),
        trim_size=rng.choice(["A4", "A5", "B5"]),
        interior_gsm=rng.choice([60, 70, 80, 100]),
        cover_gsm=rng.choice([170, 200, 250, 300]),
        binding=rng.choice(["saddle_stitch", "perfect", "spiral", "case"]),
        cover_finish=rng.choice(["matte", "glossy", "uncoated"]),
        color_mode=rng.choice(["full_color", "black_white"]),
        finishing=rng.choice([[], ["lamination"], ["foiling"]]),
        urgency=rng.choices(["standard", "high"], weights=[0.8, 0.2])[0],
    )


def _merch(rng: random.Random) -> MerchSpec:
    item = rng.choice(["shirt", "mug", "cap", "bag", "umbrella", "lanyard"])
    placements = {"shirt": ["front", "back", "sleeve"], "cap": ["front", "back", "side"],
                  "bag": ["front", "back"], "mug": ["wrap", "front"],
                  "umbrella": ["panel", "wrap"], "lanyard": ["wrap"]}[item]
    return MerchSpec(
        item_type=item,
        quantity=rng.choice([20, 50, 100, 150, 250, 500, 1000]),
        garment_size=rng.choice(["S", "M", "L", "XL", "XXL"]) if item == "shirt" else None,
        print_method=rng.choice(["screen", "dtf", "sublimation", "embroidery"]),
        placements=rng.sample(placements, k=rng.randint(1, len(placements))),
        color_count=rng.randint(1, 5),
        urgency=rng.choices(["standard", "high"], weights=[0.8, 0.2])[0],
    )


def _benchmark(rng: random.Random) -> BenchmarkSpec:
    return BenchmarkSpec(
        item_type=rng.choice(["flyer", "poster", "business card", "booklet", "banner"]),
        quantity=rng.choice([50, 100, 250, 500, 1000, 2000, 5000]),
        paper_size=rng.choice(["A2", "A3", "A4", "A5", "A6"]),
        paper_gsm=rng.choice([80, 100, 130, 170, 250, 300]),
        paper_finish=rng.choice(["matte", "glossy", "uncoated"]),
        print_side=rng.choice(["single", "double"]),
        color_mode=rng.choice(["full_color", "black_white"]),
        finishing=rng.choice([[], ["lamination"], ["folding"], ["die-cut"]]),
        urgency=rng.choices(["standard", "high"], weights=[0.8, 0.2])[0],
    )


BUILDERS = {"book": _book, "merch": _merch, "benchmark": _benchmark}


def invented_market_price(spec, rate_card: float, rng: random.Random) -> float:
    """
    The made-up 'reality' the model is asked to rediscover: big jobs get quietly
    discounted, rush jobs carry more than the flat fee, tiny jobs cost more per
    unit than the card says, plus noise. Entirely fictional.
    """
    qty = spec.quantity or 1
    m = 1.0
    if qty >= 1000:
        m *= 0.88
    elif qty >= 500:
        m *= 0.93
    elif qty < 100:
        m *= 1.12
    if spec.urgency == "high":
        m *= 1.09
    if spec.category == "merch":
        m *= 1.05
    elif spec.category == "book":
        m *= 0.97
    m *= rng.gauss(1.0, 0.045)
    return max(rate_card * m, 1.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "synthetic.csv")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for _ in range(args.rows):
            category = rng.choices(["book", "merch", "benchmark"], weights=[0.35, 0.3, 0.35])[0]
            spec = BUILDERS[category](rng)
            rate_card = calculate_quote(spec)["deterministic_subtotal_xaf"]
            row = spec.model_dump()
            row["placements"] = "|".join(row.get("placements") or [])
            row["finishing"] = "|".join(row.get("finishing") or [])
            row["final_price_xaf"] = round(invented_market_price(spec, rate_card, rng), 2)
            writer.writerow({k: ("" if row.get(k) is None else row.get(k, "")) for k in FIELDS})

    print(f"Wrote {args.rows} SYNTHETIC invoices to {args.out}")
    print("These are invented. Use them to test the pipeline, never to judge accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
