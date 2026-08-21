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

**Excluded items.** Pens, pencils, markers and ID cards are sourced and priced
by hand at Presprint. `/extract-specs` refuses them with a reason instead of
inventing a price, and the UI routes the client to a staff member.

## The 3D preview is not decoration

`/preview-model` returns the *parametric* geometry the price was built from,
so the model on screen is dimensionally the job being quoted. A book's spine is
`ceil(pages / 2) leaves × interior gsm × caliper + 2 cover boards` — the same
function the pricing engine calls. Change the page count in the form and the
spine thickens in the viewport as the price moves.

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

## Local development

```bash
docker compose up --build
```

- Backend: http://localhost:8000 (Swagger docs at `/docs`)
- Frontend: http://localhost:8080

Or run the backend natively:

```bash
cd backend
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then serve `frontend/` with any static server (`python -m http.server 8080`).
Opening `index.html` from disk won't work — the page is an ES module.

If port 8000 is already taken, start the API elsewhere and aim the page at it:
`http://localhost:8080/index.html?api=http://localhost:8010`.

## Running tests

```bash
cd backend
pytest tests/ -v
```

With no `DATABASE_URL` set the suite runs against a throwaway SQLite file, so it
works with no containers running. CI sets `DATABASE_URL` to the Postgres service,
which is what exercises the real JSONB columns.

## Migrations

The schema is owned by Alembic. `create_all` runs only when
`ENVIRONMENT=development`.

```bash
cd backend
alembic upgrade head                        # apply
alembic revision --autogenerate -m "..."    # after changing models
```

## Editing pricing rules

Everything lives in `backend/pricing_matrix.json` — paper and board rates,
ink rates, binding costs, blank goods, decoration methods, discount tiers, rush
fee %, tax %, and the excluded-terms list. No code changes needed.

Adding a binding style or a merch blank there also adds it to the review form's
dropdowns and to the 3D preview, because the form is generated from
`/categories`, which reads the matrix. One source of truth.

Get real numbers from Presprint during Week 1 interviews and replace the
placeholders.

## Roadmap status

- [x] Repo scaffold, Docker Compose, Postgres schema
- [x] Category routing (book / merch / benchmark) + excluded-item guardrail
- [x] Rule-based `/extract-specs`, constrained per category
- [x] Multi-matrix deterministic `/calculate-quote` with per-line derivations
- [x] Parametric `/preview-model` + Three.js viewport
- [x] JSONB parameter/breakdown/preview storage under Alembic
- [x] `/orders` CRUD, receipt endpoint, printable receipt
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

```bash
docker compose --profile prod up -d
```

This brings up `nginx-proxy` in front of the backend and frontend containers,
using `infra/nginx.conf`. Point a domain's DNS at the host and add SSL certs
(Let's Encrypt/certbot) before going live — see the commented block in
`infra/nginx.conf`.
