# Presprint — Automated Multi-Category Print Cost Estimation & Order Extraction

Internship project (L400, University of Buea) for Presprint PLC, Limbe.
Turns a plain-text client request into a structured spec, a live 3D preview,
and an instant itemized quote in XAF — then into a printable order receipt.

## What this build is

Two designs were on the table:

- an **implementation-first** build — one flat product category, rule-based
  extraction, a deterministic cost engine, and a complete quote → order →
  receipt → print flow that actually worked; and
- a **proposal-first** design — three production lines, category-aware NLP with
  exclusion guardrails, per-category cost matrices, JSONB storage under Alembic,
  and a Three.js parametric 3D preview.

This repository is the merge. The working flow and the deterministic,
auditable pricing survive; the category axis, the guardrails, the JSONB
schema and the 3D viewport are built on top of them.

## Architecture

```
frontend/         Single-page HTML/Tailwind wizard (no build step)
                    5 steps: category → describe → review + 3D → quote → receipt
                    Three.js viewport renders geometry sent by the backend
backend/          FastAPI app
  app/
    routers/
      meta.py       GET  /categories        form options, derived from the matrices
      extract.py    POST /extract-specs     category-aware extraction + guardrail
      preview.py    POST /preview-model     parametric 3D geometry (stateless)
      quote.py      POST /calculate-quote   price + persist
      orders.py     POST /orders, GET /orders/{id}/receipt
    services/
      nlp_extractor.py  category routing + constrained rule-based extraction
      pricing.py        one cost engine per line + shared discount/rush/tax tail
      preview.py        parametric geometry (book spine, trim sizes, blanks)
    models/         SQLAlchemy ORM, JSONB payloads on `quotes`
    schemas/        Pydantic discriminated union on `category`
  alembic/          schema migrations (JSONB columns, category index)
  pricing_matrix.json   every rate, in one file, editable by non-engineers
nlp/              v2 NER training upgrade path (post-MVP)
ml/               ML cost-adjustment upgrade path (stretch goal, needs real data)
infra/            Nginx reverse proxy config for prod deployment
```

## The three production lines

| Line | Products | Costed as |
|---|---|---|
| **book** | textbooks, exercise books, novels, catalogues | interior sheets (imposed *n*-up) + ink per page + cover board + binding + lamination |
| **merch** | shirts, mugs, caps, bags, umbrellas, lanyards | blank goods + setup per colour per placement + decoration per unit |
| **benchmark** | flyers, business cards, posters, booklets, banners | paper (size × finish × gsm) + ink (sides) + finishing |

All three share one tail: volume discount → rush fee → tax.

Picking a category in the UI *pins* extraction to that line's vocabulary; skip
it and the router infers the line from the wording. Either way, unstated
parameters stay `null` — never guessed — and `missing_fields` tells the form
what to ask for. Anything still blank at quote time is priced at a documented
default and reported back in `warnings`.

Request models reject non-positive or unreasonably large quantities, page
counts, GSM values and colour counts. They also reject unsupported enum values
instead of allowing the pricing engine to fail with a server error.

**Excluded items.** Pens, pencils, markers and ID cards are sourced and priced
by hand at Presprint. `/extract-specs` refuses them with a reason instead of
inventing a price, and the UI routes the client to a staff member.

## The 3D preview is not decoration

`/preview-model` returns the *parametric* geometry the price was built from,
so the model on screen is dimensionally the job being quoted. A book's spine is
`ceil(press-ready pages / 2) leaves × interior gsm × caliper + 2 cover boards`.
Page counts are rounded up to the next four-page signature once and that same
press-ready count is used by both the pricing engine and the viewport.

The viewport degrades gracefully: no WebGL, or a CDN that won't load Three.js,
falls back to a text readout of the same dimensions. Quoting never depends on it.

## Why rule-based NLP + deterministic pricing, not ML

The original proposal scoped a trained NER model and an XGBoost regressor for
Week 3–4. In practice you won't have annotated training data or clean historical
pricing data that early. This build instead:

1. Ships a **category-aware rule-based extractor** from day one
   (`app/services/nlp_extractor.py`) — good accuracy in a constrained domain,
   no training data needed.
2. Ships a **deterministic pricing engine** (`app/services/pricing.py` +
   `pricing_matrix.json`) as the real production cost calculator. Every line
   item carries a `detail` string showing its own arithmetic
   (`32 sheets/copy (64 leaves, 2-up) × 26 XAF × 800`), so a quote can be
   defended line by line during UAT.
3. Logs every real query as JSONB so a genuine ML upgrade (NER fine-tune,
   regression adjustment layer) becomes possible *later*, with real data — see
   `nlp/train_ner.py` and `ml/README.md`.

Deterministic pricing is auditable, which matters far more to a print shop's
finance team than an ML black box.

## Training the pricing model

The proposal scoped a regression model that prices from historical sales, and
that path is built: dataset schema, training, held-out evaluation, and serving
— see [ml/README.md](ml/README.md).

It is **off by default**, because a pricing model is only as accurate as the
invoices it learns from and Presprint's history is not in this repo yet. The
build is arranged so that state is safe rather than hidden:

- The deterministic rate matrices price every job unless a model has earned the
  right to adjust it.
- A trained model does not replace them — it predicts a **multiplier** on the
  rate-card subtotal, itemised on the quote as its own line, so the arithmetic
  stays defensible.
- A model that loses to the rate matrices on held-out invoices is **refused by
  the API automatically**. Turning ML on cannot quietly make quotes worse.

```bash
# once: build the image with scikit-learn included
docker compose build --build-arg INSTALL_ML=true backend

# train on real invoices (ml/data/sales_history.example.csv documents the schema)
docker compose exec backend python /ml/train_pricing.py /ml/data/sales_history.csv

# if it beat the rate matrices, switch it on
ML_PRICING_ENABLED=true docker compose up -d
```

`GET /health` reports which engine is live and why; every quote carries
`pricing_method`, `deterministic_subtotal_xaf` and `ml_multiplier`.

What needs training, and what does not:

| | Trained? | Needs |
|---|---|---|
| NLP extractor | eventually — currently rule-based | annotated *text* queries (`nlp/train_ner.py`) |
| Pricing | optional adjustment layer | historical *invoices* with the price actually charged |
| Rate matrices | never | an interview with Presprint |

## Running it on Docker

Everything — Postgres, the API, the matrices and the frontend — comes up with
one command. You need Docker Desktop running; nothing else is installed on the
host.

### 1. Stop anything already on the ports

The stack binds `5432`, `8000` and `8080`. If you have an older copy of this
project running, stop it first or the new containers won't get their ports:

```bash
docker compose ls
```

Then, from whichever directory that stack was started in:

```bash
docker compose down
```

### 2. Build and start

From the repository root:

```bash
docker compose up --build -d
```

First build takes about a minute. On start the backend waits for Postgres, runs
`alembic upgrade head`, and only then binds port 8000 — so the API is never up
with a half-built schema.

### 3. Watch it come up

```bash
docker compose logs -f backend
```

You want these four lines:

```
[entrypoint] waiting for the database…
[entrypoint] database is up (attempt 1)
[entrypoint] applying migrations…
[entrypoint] starting API
```

`Ctrl-C` stops tailing, not the containers.

### 4. Confirm all three services are healthy

```bash
docker compose ps
```

`db` and `backend` should both say `(healthy)`. The backend healthcheck has a
40-second grace period because migrations run first.

### 5. Open it

| | |
|---|---|
| Frontend | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Category matrices | http://localhost:8000/categories |

The header pill should read **API connected**. Run one job end to end — pick
Book and paste `800 copies of a 128 page A5 novel, 80gsm interior, 250gsm gloss
cover, perfect bound, black and white`. You should get a 3D book with a 7.03 mm
spine and a total around 1,582,185 XAF.

For local development, the database and backend are bound to `127.0.0.1`.
Set `POSTGRES_PASSWORD`, `ENVIRONMENT` and `ADMIN_API_KEY` in a root `.env`
file when overriding the Compose defaults. Never use the example password in a
public deployment.

### 6. Stopping

```bash
docker compose down          # stop, keep the database
docker compose down -v       # stop and wipe the database too
```

## Working with the matrices under Docker

`backend/pricing_matrix.json` is **mounted into the container as config**, not
baked into the image:

```yaml
environment:
  PRICING_MATRIX_PATH: /config/pricing_matrix.json
volumes:
  - ./backend/pricing_matrix.json:/config/pricing_matrix.json:ro
```

So changing a rate is just editing the file on your machine. The engine keys its
cache on the file's modification time, so the next quote picks up the new number
— **no rebuild, no restart**. Edit a rate, then immediately:

```bash
curl -s -X POST http://localhost:8000/calculate-quote -H "Content-Type: application/json" -d '{"spec":{"category":"benchmark","quantity":100,"paper_size":"A4","paper_finish":"matte","print_side":"single","color_mode":"black_white","urgency":"standard"}}'
```

If an edit doesn't seem to take — some editors replace the file rather than
writing in place, which can break a single-file mount — force it:

```bash
docker compose restart backend
```

Because `/categories` is derived from the matrix, adding a binding style or a
merch blank there also adds it to the review form's dropdowns and to the 3D
preview. Reload the page to pick it up.

A malformed JSON edit will make every pricing endpoint fail, so validate before
saving:

```bash
python -m json.tool backend/pricing_matrix.json > /dev/null && echo "matrix OK"
```

## Production profile (reverse proxy)

```bash
docker compose --profile prod up -d
```

This adds `nginx-proxy` in front of everything on port 80, using
`infra/nginx.conf`:

| Path | Goes to |
|---|---|
| `/` | frontend |
| `/api/` | backend, rate-limited to 10 r/s with burst 20 |
| `/docs`, `/redoc`, `/openapi.json` | Swagger in development only |

The frontend finds the API by probing same-origin `/api/health` at load time
and falling back to `host:8000`, so the same page works behind the proxy or on
plain Compose without a build step. Behind the proxy everything is same-origin,
so CORS does not apply.

Before going live, add SSL: point a domain at the host and uncomment the `443`
block in `infra/nginx.conf` with Let's Encrypt certs.

Set `ENVIRONMENT=production` to disable Swagger/OpenAPI routes. The staff order
listing, lookup, receipt and status endpoints require the `X-Admin-Key` header,
whose value must match `ADMIN_API_KEY`. Customer order creation remains
available through `POST /orders`, which returns the receipt directly. Keep the
admin key out of frontend code and use a proper authentication system when
multiple staff users or audit roles are required.

## Running without Docker

```bash
cd backend
cp .env.example .env
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

You still need a Postgres reachable at whatever `DATABASE_URL` says. Serve the
frontend with any static server (`cd frontend && python -m http.server 8080`).
Opening `index.html` from disk won't work — the page is an ES module.

If port 8000 is taken, start the API elsewhere and aim the page at it:
`http://localhost:8080/index.html?api=http://localhost:8010`.

The NLP/ML upgrade-path packages (spaCy, scikit-learn, XGBoost, pandas) are
**not** installed by default — nothing in `app/` imports them and they add
~1.5GB to the image. Install them only when you start on `nlp/` or `ml/`:

```bash
pip install -r requirements.txt -r requirements-ml.txt
```

## Running tests

```bash
cd backend
pytest tests/ -v
```

With no `DATABASE_URL` set the suite runs against a throwaway SQLite file, so it
works with no containers running. CI sets `DATABASE_URL` to the Postgres service,
which is what exercises the real JSONB columns.

To run them inside the container instead:

```bash
docker compose exec backend pytest tests/ -v
```

## Migrations

The schema is owned by Alembic, and the container applies migrations on every
start. `create_all` only runs when `ENVIRONMENT=development`.

```bash
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "your message"
```

An autogenerated revision lands in `backend/alembic/versions/` on your host,
because the backend directory is mounted — commit it like any other file.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `port is already allocated` | an older stack is still up | `docker compose ls`, then `docker compose down` in that directory |
| Header says **API offline** | backend still migrating, or it crashed | `docker compose logs backend` |
| Header connected, but "Couldn't load the category matrices" | you're talking to an *older* backend on :8000 | `docker compose down` the stale stack, then bring this one up |
| `relation "quotes" already exists` at start | the database predates Alembic | Back up the database, migrate its legacy columns into the current schema, then run `alembic upgrade head`; use `docker compose down -v` only when deleting local development data |
| 3D preview says "unavailable" | no WebGL, or the Three.js CDN is unreachable | it's optional — quoting is unaffected; check the browser console |
| Pricing endpoints fail after a rate edit | malformed JSON in the matrix | `python -m json.tool backend/pricing_matrix.json` |

## Roadmap status

- [x] Repo scaffold, Docker Compose, Postgres schema
- [x] Category routing (book / merch / benchmark) + excluded-item guardrail
- [x] Rule-based `/extract-specs`, constrained per category
- [x] Multi-matrix deterministic `/calculate-quote` with per-line derivations
- [x] Parametric `/preview-model` + Three.js viewport
- [x] JSONB parameter/breakdown/preview storage under Alembic
- [x] `/orders` CRUD, receipt endpoint, printable receipt
- [x] Input bounds and enum validation for quote requests
- [x] Shared press-ready book page normalization for pricing and preview
- [x] Staff key protection for order administration and production-only docs disablement
- [x] Five-step frontend wizard
- [ ] Real Presprint pricing data → `pricing_matrix.json`
- [ ] UAT query logging → training data for `nlp/train_ner.py`
- [ ] Nginx SSL termination + GitHub Actions deploy job (Week 7)
- [ ] UAT sign-off (Week 8)

## API note

The proposal listed a `/generate-receipt` endpoint. It exists here as
`GET /orders/{order_id}/receipt`, and `POST /orders` returns the same receipt
payload directly so placing an order is a single round trip.

## Deployment (Week 7)

See **Production profile** above for the proxy setup. Point a domain's DNS at
the host and add SSL certs (Let's Encrypt/certbot) before going live — see the
commented `443` block in `infra/nginx.conf`.
