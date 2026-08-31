"""
Train the pricing model on Presprint's historical invoices.

    python ml/train_pricing.py ml/data/sales_history.csv

What it does, in order:

  1. Reads the invoice CSV (schema below; see ml/data/sales_history.example.csv).
  2. Re-prices every historical job through the deterministic rate matrices, so
     each row carries the rate-card number alongside what was actually charged.
  3. Trains a gradient-boosted regressor to predict the gap.
  4. Scores it against the deterministic engine on a held-out split, and records
     whether it won. The API refuses to serve a model that lost.
  5. Saves model + metrics to ml/models/price_model.joblib.

Two targets:

  --target multiplier   (default) predict final_price / rate_card_subtotal.
                        The rate card does the physics; the model learns only
                        the deviation. Needs less data, extrapolates safely.
  --target absolute     predict final_price_xaf directly. Closer to a textbook
                        regression, but needs substantially more rows and can
                        produce nonsense outside its training range.

Required CSV columns:

    category            book | merch | benchmark
    quantity            integer
    final_price_xaf     what the client was actually invoiced  <-- the target

Optional columns (more of these = a better model). They mirror the spec fields
the NLP extractor produces, so training data and live requests look identical
to the model:

    item_type page_count trim_size interior_gsm cover_gsm binding cover_finish
    color_mode paper_size paper_gsm paper_finish print_side print_method
    color_count garment_size placements finishing urgency

placements and finishing are pipe- or comma-separated (e.g. "front|back").
urgency is "standard" or "high".
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

# The feature definition and the pricing engine both live in the backend, so a
# model can never be trained on a different layout than the API serves.
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
from app.services.ml_features import (  # noqa: E402
    CATEGORICAL_INDICES,
    FEATURE_NAMES,
    NUMERIC_FEATURES,
    feature_row,
)
from app.services.pricing import calculate_quote  # noqa: E402

SPEC_CLASSES = {"book": BookSpec, "merch": MerchSpec, "benchmark": BenchmarkSpec}

LIST_FIELDS = {"placements", "finishing"}
INT_FIELDS = {"quantity", "page_count", "interior_gsm", "cover_gsm", "paper_gsm", "color_count"}


def _parse_row(row: dict) -> tuple[object, float]:
    """CSV row -> (spec, final_price_xaf)."""
    category = (row.get("category") or "").strip().lower()
    if category not in SPEC_CLASSES:
        raise ValueError(f"unknown category {category!r} (expected book, merch or benchmark)")

    fields: dict = {}
    for key, raw in row.items():
        if key in (None, "category", "final_price_xaf") or raw is None:
            continue
        value = raw.strip()
        if value == "":
            continue
        if key in LIST_FIELDS:
            fields[key] = [v.strip() for v in value.replace("|", ",").split(",") if v.strip()]
        elif key in INT_FIELDS:
            fields[key] = int(float(value))
        else:
            fields[key] = value

    spec_cls = SPEC_CLASSES[category]
    known = set(spec_cls.model_fields)
    spec = spec_cls(**{k: v for k, v in fields.items() if k in known})

    price = float(row["final_price_xaf"])
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"final_price_xaf must be positive, got {row['final_price_xaf']!r}")
    return spec, price


def load_dataset(path: Path) -> tuple[list, list[float], list[float]]:
    """Returns (feature rows, targets, deterministic subtotals)."""
    rows, prices, baselines = [], [], []
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        for line_no, raw in enumerate(csv.DictReader(f), start=2):
            try:
                spec, price = _parse_row(raw)
            except Exception as exc:
                print(f"  ! line {line_no}: skipped - {exc}")
                skipped += 1
                continue

            quote = calculate_quote(spec)
            baseline = quote["deterministic_subtotal_xaf"]

            rows.append(feature_row(spec, baseline))
            prices.append(price)
            baselines.append(baseline)

    if skipped:
        print(f"  {skipped} row(s) skipped.")
    return rows, prices, baselines


def build_model():
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OrdinalEncoder

    encoder = ColumnTransformer(
        transformers=[
            ("num", "passthrough", list(range(len(NUMERIC_FEATURES)))),
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                   encoded_missing_value=-1), CATEGORICAL_INDICES),
        ],
    )
    # Categorical columns land last, after the passthrough numerics.
    cat_positions = list(range(len(NUMERIC_FEATURES), len(FEATURE_NAMES)))
    regressor = HistGradientBoostingRegressor(
        loss="absolute_error",      # matches how we score, and shrugs off outlier invoices
        max_iter=400,
        learning_rate=0.06,
        min_samples_leaf=5,         # small datasets are the norm here
        l2_regularization=1.0,
        categorical_features=cat_positions,
        random_state=42,
    )
    return Pipeline([("encode", encoder), ("model", regressor)])


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Train the Presprint pricing model on historical invoices.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("csv", type=Path, help="historical invoices; see --help for the schema")
    ap.add_argument("--target", choices=["multiplier", "absolute"], default="multiplier")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "models" / "price_model.joblib")
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--min-rows", type=int, default=60,
                    help="refuse to train below this many usable rows")
    ap.add_argument("--force", action="store_true",
                    help="save the artifact even if it loses to the rate matrices")
    args = ap.parse_args()

    try:
        import numpy as np
        import joblib
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("This needs the ML dependencies:\n\n    pip install -r backend/requirements-ml.txt\n")
        return 2

    if not args.csv.exists():
        print(f"No such file: {args.csv}")
        print("Start from ml/data/sales_history.example.csv - it documents the schema.")
        return 2

    print(f"Reading {args.csv} ...")
    rows, prices, baselines = load_dataset(args.csv)
    n = len(rows)
    print(f"  {n} usable invoice(s).")

    if n < args.min_rows:
        print(f"\nRefusing to train on {n} rows (minimum {args.min_rows}).")
        print("A model fitted to a handful of invoices will look accurate in testing and")
        print("mislead you in production. Keep quoting from the rate matrices and collect")
        print("more history first - or pass --min-rows if you know what you are doing.")
        return 1

    X = np.array(rows, dtype=object)
    y_price = np.array(prices, dtype=float)
    base = np.array(baselines, dtype=float)

    if (base <= 0).any():
        print("\nSome jobs priced to a zero/negative rate-card subtotal; check the matrices.")
        return 1

    y = y_price / base if args.target == "multiplier" else y_price

    X_tr, X_te, y_tr, y_te, base_tr, base_te, price_tr, price_te = train_test_split(
        X, y, base, y_price, test_size=args.test_size, random_state=42
    )
    print(f"  train {len(X_tr)} / test {len(X_te)}")

    print(f"Training (target = {args.target}) ...")
    model = build_model()
    model.fit(X_tr, y_tr)

    # Score both approaches in XAF on the same held-out invoices.
    pred = model.predict(X_te)
    pred_price = pred * base_te if args.target == "multiplier" else pred

    model_mae = float(np.mean(np.abs(pred_price - price_te)))
    baseline_mae = float(np.mean(np.abs(base_te - price_te)))
    model_mape = float(np.mean(np.abs(pred_price - price_te) / price_te) * 100)
    baseline_mape = float(np.mean(np.abs(base_te - price_te) / price_te) * 100)
    improvement = (baseline_mae - model_mae) / baseline_mae * 100 if baseline_mae else 0.0
    beats = model_mae < baseline_mae

    print("\n  Held-out accuracy vs the actual invoiced price")
    print(f"    rate matrices only : MAE {baseline_mae:>12,.0f} XAF   ({baseline_mape:.1f}%)")
    print(f"    with the model     : MAE {model_mae:>12,.0f} XAF   ({model_mape:.1f}%)")
    print(f"    improvement        : {improvement:+.1f}%")

    if not beats and not args.force:
        print("\nThe model is LESS accurate than the rate matrices on unseen invoices.")
        print("Saving it anyway would make your quotes worse, so it is saved disabled -")
        print("the API keeps using the matrices and reports why.")
        print("Options: collect more history, fill in missing spec columns, or --force.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "target": args.target,
        "feature_names": FEATURE_NAMES,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_rows": int(n),
        "test_rows": int(len(X_te)),
        "model_mae": round(model_mae, 2),
        "baseline_mae": round(baseline_mae, 2),
        "model_mape": round(model_mape, 2),
        "baseline_mape": round(baseline_mape, 2),
        "improvement_percent": round(improvement, 2),
        "beats_baseline": bool(beats or args.force),
        "forced": bool(args.force and not beats),
        "source_csv": str(args.csv),
    }
    joblib.dump({"model": model, "meta": meta}, args.out)
    report = args.out.with_suffix(".metrics.json")
    report.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\nSaved {args.out}")
    print(f"      {report}")
    print(f"Active in the API: {'yes' if meta['beats_baseline'] else 'no (see above)'}")
    if meta["beats_baseline"]:
        print("\nTurn it on:  ML_PRICING_ENABLED=true  then  docker compose up -d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
