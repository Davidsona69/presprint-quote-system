# ML Pricing — trainable, but gated on real data

The proposal scoped a regression model that prices jobs from historical sales.
This directory implements that end to end: dataset schema, training, held-out
evaluation, and serving. It is **off by default**, and the reason matters.

## The one thing to understand

A pricing model is only as accurate as the invoices it learns from. There is no
public dataset of Cameroonian print jobs, and none of Presprint's history is in
this repo. Until you have their real invoices, no amount of training produces
accurate prices — it just produces confident ones.

So the system is built to make that state safe rather than to hide it:

- The deterministic rate matrices price every job by default.
- A trained model does not replace them. It predicts a **multiplier** on the
  rate-card subtotal, shown as its own line on the quote.
- A model that loses to the rate matrices on held-out invoices **is refused by
  the API**, automatically. Training records the comparison in the artifact and
  `ml_pricing.py` reads it before serving.

That last point is the important one. It means turning ML on cannot quietly
make your quotes worse.

## Why a multiplier and not the price directly

`--target absolute` exists and predicts `final_price_xaf` outright. It is the
textbook approach and it is the wrong default here.

The rate matrices already encode the physics of a print job — sheets, imposition,
binding setup, ink per page. Handing the model that number as a feature means it
only has to learn where Presprint's *actual* invoices deviate from the card:
negotiation, client segment, press scheduling, competitive pressure. That is a
much smaller thing to learn, so it needs far fewer rows, and it degrades safely —
a model that knows nothing predicts ~1.0 and you get the rate card back.

Predicting the price from scratch throws that structure away and asks a few
hundred rows to rediscover arithmetic you already have exactly right.

## What you need

A CSV of completed jobs with what was **actually invoiced** — not the list
price, the real negotiated figure. See `data/sales_history.example.csv`.

Required: `category`, `quantity`, `final_price_xaf`.

Everything else is optional and every column you add helps: `item_type`,
`page_count`, `trim_size`, `interior_gsm`, `cover_gsm`, `binding`,
`cover_finish`, `color_mode`, `paper_size`, `paper_gsm`, `paper_finish`,
`print_side`, `print_method`, `color_count`, `garment_size`, `placements`,
`finishing`, `urgency`.

Those names are deliberately the spec fields the NLP extractor produces, so a
training row and a live request look identical to the model.

How many rows? The script refuses below 60 and that is a floor, not a target.
Realistically: ~150+ for a usable multiplier model, more if your job mix is
varied. Fitting to 20 invoices produces a model that scores well in testing and
misleads you in production.

## Training

**Train inside the backend container.** A model pickled with one numpy version
cannot always be unpickled by another; training in the image that serves it
removes the whole class of problem. (The API detects the mismatch and falls back
to the rate matrices rather than failing, but you still get no model.)

Build the image with the ML dependencies once:

```bash
docker compose build --build-arg INSTALL_ML=true backend
```

Drop your invoices at `ml/data/sales_history.csv`, then:

```bash
docker compose exec backend python /ml/train_pricing.py /ml/data/sales_history.csv
```

It prints the comparison that decides everything:

```
  Held-out accuracy vs the actual invoiced price
    rate matrices only : MAE      137,990 XAF   (9.2%)
    with the model     : MAE       54,101 XAF   (4.2%)
    improvement        : +60.8%
```

If the model wins, the artifact is marked active. If it loses, it is saved
*disabled* and the API says so on `/health`. Turn it on with:

```bash
ML_PRICING_ENABLED=true docker compose up -d
```

The API reloads the artifact when its file changes, so retraining takes effect
without a restart.

Useful flags: `--target absolute`, `--test-size 0.3`, `--min-rows N`, and
`--force` to serve a model that lost its evaluation (don't).

## Testing the pipeline without real data

`generate_synthetic.py` invents invoices by taking the rate matrices and applying
a known distortion — volume discounts, a rush premium, a small-order surcharge,
noise:

```bash
docker compose exec backend python /ml/generate_synthetic.py --rows 400 --out /ml/data/synthetic.csv
docker compose exec backend python /ml/train_pricing.py /ml/data/synthetic.csv
```

This proves the plumbing works. It proves **nothing** about real accuracy — the
model is rediscovering a distortion this repo invented. Do not put numbers
derived from synthetic data in your report. Delete the artifact when done:

```bash
rm ml/models/price_model.joblib ml/data/synthetic.csv
```

## Bootstrapping from a market price list

With no history of your own, an existing rate card is a reasonable cold start.
`market_import.py` converts any price list you are permitted to use into the
training schema:

```bash
python ml/market_import.py ml/data/market_pricelist.csv --currency NGN --source "acme-ratecard-2026"
python ml/train_pricing.py ml/data/market_training.csv --target absolute
```

`--target absolute` here, not the multiplier default: the multiplier measures
deviation from *Presprint's* rate card, and an external price list has no
opinion about that. Absolute makes the model learn the source's price function
directly.

Be clear about what that produces. A model trained on imported rates learns
**that source's pricing**, expressed in XAF. It is a defensible cold-start
baseline and it is not Presprint's pricing — every imported row carries a
`price_origin` column so the distinction survives into the data.

### What you may import

Check before collecting anything automatically. Many print sites disallow
crawling in `robots.txt`, and some publish a `Content-Signal` of `ai-train=no`,
which rules out exactly this use however public the pages look. Printivo does
both — its robots.txt disallows `ClaudeBot`, `GPTBot`, `CCBot` and others by
name and signals `ai-train=no` — so its catalogue is not a source you can use
this way.

Routes that do work: a rate card you were given or quoted, a supplier price
sheet, a printed catalogue you transcribe, a site whose terms permit it, or
simply asking. A student project that explains what it needs and why gets a
spreadsheet more often than you would expect, and a named permission is worth
more in your report than a scrape.

### Currency is two steps, not one

```
price_XAF = price_foreign x fx_rate x market_adjustment
                            ^^^^^^^   ^^^^^^^^^^^^^^^^^
                            a fact    an economic claim
```

The FX rate is lookup-able. The market adjustment asserts that two markets are
comparable — and a Lagos print e-commerce operation and a Limbe print shop are
not: different paper import costs, labour, electricity, scale, competition.
`ml/fx.py` keeps them separate so the second one stays arguable instead of
being buried in a single number.

`fx_config.json` ships with a real dated rate (1 NGN = 0.39473 XAF, 22 Aug 2026)
and an **uncalibrated** market factor of 1.0. Uncalibrated means every
conversion carries a warning saying so, because 1.0 is certainly wrong — it just
fails visibly rather than silently.

Two things about the rates themselves. XAF is pegged to the euro at a fixed
655.957, so EUR and XOF conversions are exact and never go stale. The naira
floats and moved between 0.332 and 0.406 XAF over 52 weeks — a ~22% spread — so
imported naira prices drift. Conversions warn once the rate is older than
`staleness_warning_days`; refresh and re-import rather than retraining on stale
numbers.

### Calibrating the market factor

Quote 5–10 identical jobs both locally and through the foreign source, FX the
foreign ones into XAF, and take the median ratio:

```python
from ml.fx import calibrate
calibrate(local_prices_xaf, foreign_prices_converted_to_xaf)
# {'factor': 1.21, 'n': 5, 'min_ratio': 1.18, 'max_ratio': 1.22, 'calibrated': True}
```

Median, not mean, so one unusual job cannot drag it. Put the result in
`fx_config.json` with `"calibrated": true` and a note on how you derived it —
that note is what makes the number defensible in your report. A wide
`min_ratio`/`max_ratio` spread is itself the finding: it means a single factor
does not describe the relationship and the two markets differ by product type.

## Safety rails, and why each exists

| Rail | Guards against |
|---|---|
| Held-out gate (`beats_baseline`) | shipping a model that prices worse than the rate card |
| Feature-layout check | a model trained before a code change serving garbage silently |
| Multiplier clamp, default 0.70–1.40 | extrapolation off the end of the training data quoting an absurd price |
| Non-finite / negative guard | NaN or a negative price reaching a client |
| Per-quote exception fallback | one odd job taking down quoting for everyone |
| Off by default | an untrained system pretending to be a trained one |

Clamping is not silent — hitting the band edge attaches a warning to the quote
telling staff to check the price by hand. Adjust the band with
`ML_MULTIPLIER_FLOOR` / `ML_MULTIPLIER_CEILING`.

## Checking what is actually pricing

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

`pricing_model.active` tells you which engine is live, and `reason` explains
why if it is not. Every quote response also carries `pricing_method`
(`deterministic` or `ml_adjusted`), `deterministic_subtotal_xaf` and
`ml_multiplier`, so any quote can be traced back to how it was produced.

## Collecting the data you need

The system is already building your training set. Every quote persists
`raw_query`, the extracted `parameters`, and the totals as JSONB. Add the price
actually invoiced — `orders.status` moving to `done` is the natural moment — and
after a few months of real trading you can export exactly the CSV above from the
`quotes` + `orders` tables.

Until then, the honest answer for the report is that the deterministic engine is
the production system, the ML path is built and tested, and it will be trained
when the data exists.
