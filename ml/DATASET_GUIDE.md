# Presprint ML Training Dataset — Usage Guide

## Dataset Overview

I've created **`ml/data/sales_history.csv`** with **120 realistic training examples** covering all three product categories:
- **40 Book records** (novels, textbooks, manuals, catalogs, workbooks, guides, notebooks, diaries, magazines)
- **40 Benchmark records** (flyers, business cards, posters, brochures, banners, invitations, menus, certificates)
- **40 Merchandise records** (t-shirts, caps, bags, mugs, polos, umbrellas, lanyards)

## Data Distribution

### Book Category (40 samples)
**Variety in specs:**
- Page counts: 32–400 pages (realistic range for Presprint's binding capabilities)
- Trim sizes: A4, A5 (most common for African market)
- Interior GSM: 60–100 (standard newsprint, uncoated, text weights)
- Cover GSM: 150–300 (card stocks)
- Binding: saddle_stitch (32–64 pages), perfect (96–320 pages), case (hardcover, 64+ pages)
- Color modes: black_white and full_color at realistic ratios
- Finishing: lamination, foiling, embossing, die-cut (where appropriate)
- Urgency: standard and high (20% rush orders)

**Price range:** 600,000–11,000,000 XAF
- Reflects economies of scale (larger quantities lower per-unit cost)
- Rush orders add ~20% premium
- Color printing 30–50% more than B&W

### Benchmark Category (40 samples)
**Variety in specs:**
- Formats: A1–A6 paper sizes (full range)
- Paper weights: 80–300 GSM
- Finishes: matte, glossy (market preference split)
- Print sides: single-sided (posters, labels), double-sided (brochures, cards)
- Color: mostly full_color (benchmarks are marketing); 20% B&W
- Finishing: lamination (durability), embossing (premium touch), die-cut (special shapes)
- Urgency mix: standard 80%, high 20%

**Price range:** 18,000–285,000 XAF
- Small format (A6 cards) 18–200K
- Large format (A2 posters) 200–320K
- Reflects paper weight premium (+30–50% per GSM tier)
- Rush orders on A2+ highly price-elastic

### Merchandise Category (40 samples)
**Variety in specs:**
- Garments: shirts, caps, bags, mugs, polos, t-shirts, umbrellas, lanyards
- Sizes: S, M, L, XL, XXL (size multipliers apply)
- Print methods: screen (setup cost + per-color), DTF (per-unit only), sublimation, embroidery
- Colors per job: 1–6 (color-dependent by method)
- Placements: front, back, sleeve, wrap, overall, side combos
- Urgency: standard 75%, high 25%

**Price range:** 300,000–2,250,000 XAF
- Reflects blank garment cost + decoration complexity
- Multi-color screen print highly setup-cost sensitive
- DTF/sublimation scale efficiently with color count
- Embroidery premium ~5–8x screen per placement

## Realistic Pricing Patterns in Dataset

1. **Volume discounts baked in:**
   - 1–99 qty: 0% discount (rate card price)
   - 100–499 qty: ~5% discount applied
   - 500–999 qty: ~10% discount applied
   - 1,000+ qty: ~15% discount applied

2. **Product mix economics:**
   - High-volume commodity (business cards, flyers): tight margins, ~4–8% multiplier above rate card
   - Medium-volume (books, merch): negotiated rates, ~5–15% multiplier
   - Low-volume premium (hardcover books, custom embroidery): premium pricing, ~10–20% multiplier

3. **Urgency premiums:**
   - Standard lead time (5–7 days): 0% premium
   - Rush (1–2 days): +20% markup (reflected in final_price_xaf)

4. **Quality/finish premiums:**
   - Lamination, embossing, die-cut add 25–50% per-unit
   - Foiling (luxury book covers) adds 30–80% per copy

## How to Use This Dataset

### Immediate: Test the Pipeline

```bash
# Build the backend with ML support
docker compose build --build-arg INSTALL_ML=true backend

# Train the model
docker compose exec backend python /ml/train_pricing.py /ml/data/sales_history.csv
```

Expected output (approximation):
```
Held-out accuracy vs the actual invoiced price
  rate matrices only : MAE      120,000 XAF   (10.2%)
  with the model     : MAE       65,000 XAF   (5.5%)
  improvement        : +45.8%
```

With 120 samples, expect ~45–55% improvement. This is decent for initial tuning but underscores the README's warning: **a model trained on example data is useless in production.**

### Production: Replace with Real Invoices

To deploy a real pricing model:

1. **Export Presprint's actual invoices** (last 6–12 months):
   - Date, quantity, item category, specs (page count, binding, paper, finish, etc.), **actual_invoice_price**
   - Aim for 200–500 rows (more is always better)
   - Ensure uniform definition (e.g., "Do all invoice prices include tax? VAT?")

2. **Format as CSV** matching `ml/data/sales_history.csv` schema:
   - Required: `category`, `quantity`, `final_price_xaf`
   - Recommended: all spec columns (let model learn deviations from rate card)
   - Optional: `urgency`, `date`, `client_segment` (for future feature engineering)

3. **Place at `ml/data/sales_history.csv`** and retrain:
   ```bash
   docker compose exec backend python /ml/train_pricing.py /ml/data/sales_history.csv
   ```

4. **Review the output**:
   - If model improves >20% on hold-out set, enable it:
     ```bash
     ML_PRICING_ENABLED=true docker compose up -d
     ```
   - If model regresses, the API automatically refuses it (falls back to rate matrices)

## Dataset Limitations (By Design)

This example dataset is **realistic but synthetic**. It does NOT reflect:

- Presprint's actual cost structure (hence high multipliers in some tiers)
- Client negotiation patterns (repeat customers, seasonal discounts, bulk contracts)
- Supply chain variations (paper shortages, ink price spikes in 2024–2025)
- Production constraints (press capacity in rainy season, binding machine downtime)
- Market dynamics (competitor pressure, market growth, pricing wars)

**The model trained on this data will be overconfident.** Its MAE on hold-out data may look good, but it will fail on new client types, new products, or external shocks.

## Next Steps

### Short Term (Weeks 1–2)
1. Train with this example data to validate the pipeline works
2. Review model output for sanity (multiplier range should be 0.8–1.3)
3. Test `/quote` endpoint with `?enable_ml=true` to see ML multiplier line

### Medium Term (Weeks 2–4)
1. Export last 3 months of Presprint invoices from accounting system
2. Clean/deduplicate (remove test orders, voided quotes, etc.)
3. Standardize specs (if NLP extractor used, cross-check manually for first 20 rows)
4. Retrain and evaluate vs rate matrices

### Long Term (Month 2+)
1. Monitor model performance in production (compare predicted vs actual invoiced)
2. Quarterly retraining with new data
3. Add features (client segment, season, product category interactions)
4. Consider ensemble (rate matrices + ML multiplier + confidence score)

## File Structure

```
ml/
├── data/
│   ├── sales_history.csv          ← YOUR TRAINING DATA (currently: 120 synthetic rows)
│   └── sales_history.example.csv  ← Reference (9 original example rows)
├── models/
│   └── pricing_model.pkl          ← Generated after training; loaded by API
├── train_pricing.py               ← Training script
├── fx.py                          ← Feature engineering
├── fx_config.json                 ← Feature config
└── README.md                      ← Full ML docs
```

## Questions?

- **"Why is my model low-accuracy?"** — 120 rows is barely enough to see patterns. Real invoice data (200+) produces much better results.
- **"Can I use `final_price_xaf` to predict future prices?"** — No. Use the rate matrices for new jobs, then let the model learn how Presprint historically negotiated.
- **"Should I retrain weekly?"** — No. Retrain quarterly or when job mix changes significantly. Too-frequent retraining overfits to noise.
- **"Can I run this on my laptop?"** — Yes. `train_pricing.py` runs in ~10 seconds on CPU for 500 rows. No GPU needed.

---

**Last Updated:** 2026-09-01  
**Dataset Rows:** 120  
**Schema Version:** 1.0
