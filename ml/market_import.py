"""
Import a market price list and convert it into training data.

    python ml/market_import.py ml/data/market_pricelist.csv --currency NGN

Source-agnostic on purpose. It takes any published rate card you are permitted
to use — a competitor's printed price list, a supplier quote sheet, a rate card
you were given, Presprint's own — converts it to XAF, and writes the schema
ml/train_pricing.py expects.

WHAT YOU MAY IMPORT
-------------------
Check before you scrape anything. Many print sites disallow automated
collection in robots.txt, and some publish a Content-Signal of ai-train=no,
which specifically rules out using their catalogue to train a model. Printivo
does both. A price list you were given, quoted, or that carries a permissive
licence is fine; one that says no is not, however public the page looks.
Asking is often the fastest route: a student project explaining what it needs
gets a spreadsheet more often than you would think.

WHAT YOU GET
------------
A model trained on imported rates learns THAT SOURCE'S pricing, expressed in
XAF. That is a genuinely useful cold-start baseline for a shop with no history
of its own, and it is not the same thing as Presprint's pricing. Every output
row is stamped with `price_origin` so a model can never quietly be presented as
something it is not.

INPUT SCHEMA
------------
Required: `price` and the spec columns you have. Everything from
sales_history.example.csv is accepted; `category` and `quantity` are the
minimum useful set.

    category,item_type,quantity,paper_size,paper_gsm,...,price

Currency comes from `--currency`, or per-row from a `currency` column.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fx import Converter, FxError, load_config  # noqa: E402

PASSTHROUGH = [
    "category", "item_type", "quantity", "page_count", "trim_size", "interior_gsm",
    "cover_gsm", "binding", "cover_finish", "color_mode", "paper_size", "paper_gsm",
    "paper_finish", "print_side", "print_method", "color_count", "garment_size",
    "placements", "finishing", "urgency",
]
OUTPUT_FIELDS = PASSTHROUGH + ["final_price_xaf", "price_origin", "source_price", "source_currency"]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a market price list into XAF training data.",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--currency", default=None, help="source currency if the CSV has no `currency` column")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "market_training.csv")
    ap.add_argument("--source", default="market-reference",
                    help="what this list is, e.g. 'acme-print-ratecard-2026'. Recorded on every row.")
    ap.add_argument("--market-profile", default="default")
    ap.add_argument("--market-factor", type=float, default=None,
                    help="override the adjustment factor from fx_config.json")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"No such file: {args.csv}")
        print("Start from ml/data/market_pricelist.example.csv.")
        return 2

    try:
        conv = Converter(load_config(), args.market_profile, args.market_factor)
    except FxError as exc:
        print(f"Configuration problem: {exc}")
        return 2

    rows_out, skipped, seen_warnings = [], 0, []

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            raw_price = (row.get("price") or "").strip()
            currency = (row.get("currency") or args.currency or "").strip()

            if not raw_price:
                print(f"  ! line {line_no}: no price, skipped")
                skipped += 1
                continue
            if not currency:
                print(f"  ! line {line_no}: no currency (pass --currency), skipped")
                skipped += 1
                continue

            try:
                result = conv.convert(float(raw_price.replace(",", "").replace(" ", "")), currency)
            except (FxError, ValueError) as exc:
                print(f"  ! line {line_no}: {exc}")
                skipped += 1
                continue

            for w in result.warnings:
                if w not in seen_warnings:
                    seen_warnings.append(w)

            out = {k: (row.get(k) or "") for k in PASSTHROUGH}
            out["final_price_xaf"] = f"{result.amount_xaf:.2f}"
            out["price_origin"] = args.source
            out["source_price"] = f"{result.source_amount:.2f}"
            out["source_currency"] = result.source_currency
            rows_out.append(out)

    if not rows_out:
        print("\nNothing imported.")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    rate, as_of = conv.rate_for(rows_out[0]["source_currency"])
    print(f"\nImported {len(rows_out)} row(s)" + (f", {skipped} skipped" if skipped else ""))
    print(f"  source        : {args.source}")
    print(f"  fx            : 1 {rows_out[0]['source_currency']} = {rate} XAF  (as of {as_of})")
    print(f"  market factor : {conv.market_factor:g}"
          + ("" if conv.market_calibrated else "  [UNCALIBRATED]"))
    print(f"  written to    : {args.out}")

    for w in seen_warnings:
        print(f"\n  ! {w}")

    print("\nTrain on it with:")
    print(f"    python ml/train_pricing.py {args.out} --target absolute")
    print("\n`--target absolute` because the multiplier target measures deviation from")
    print("Presprint's own rate card, which an external price list has no opinion about.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
