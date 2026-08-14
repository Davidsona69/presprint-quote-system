# Presprint — Automated Print Cost Estimation & Order Extraction System

Internship project (L400, University of Buea) for Presprint PLC, Limbe.
Turns a plain-text client order request into a structured spec and an
instant, itemized price quote.

## Architecture

```
frontend/        Single-page HTML/Tailwind UI (no build step needed)
backend/          FastAPI app
  app/
    routers/      extract-specs, calculate-quote, orders
    services/
      nlp_extractor.py   rule-based entity extraction (MVP — see nlp/)
      pricing.py          deterministic cost engine (see pricing_matrix.json)
    models/        SQLAlchemy ORM (materials, pricing_tiers, quotes, orders)
    schemas/        Pydantic request/response models
nlp/              v2 NER training upgrade path (post-MVP)
ml/               ML cost-adjustment upgrade path (stretch goal, needs real data)
infra/            Nginx reverse proxy config for prod deployment
```

## Why rule-based NLP + deterministic pricing, not ML, for the MVP

The original proposal scoped a trained NER model and an XGBoost regressor
for Week 3–4. In practice you won't have annotated training data or clean
historical pricing data that early. This build instead:

1. Ships a **rule-based extractor** from day one (`app/services/nlp_extractor.py`) —
   good accuracy for a constrained domain, no training data needed.
2. Ships a **deterministic pricing formula** (`app/services/pricing.py` +
   `pricing_matrix.json`) as the real production cost engine — auditable,
   easy for Presprint staff to update without touching code.
3. Logs every real query during UAT so a genuine ML upgrade (NER fine-tune,
   regression adjustment layer) becomes possible *later*, with real data —
   see `nlp/train_ner.py` and `ml/README.md` for that path.

This is a stronger, more honest story for your final report than promising
a trained model you can't realistically validate in 8 weeks.

## Local development

```bash
# 1. Start everything (Postgres + backend + static frontend)
docker compose up --build

# Backend:  http://localhost:8000        (Swagger docs at /docs)
# Frontend: http://localhost:8080
```

Or run the backend natively:

```bash
cd backend
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `frontend/index.html` directly in a browser (or serve it with
any static server) — it talks to `http://localhost:8000` by default.

## Running tests

```bash
cd backend
pytest tests/ -v
```

## Editing pricing rules

All rates live in `backend/pricing_matrix.json` — no code changes needed
to update paper costs, ink rates, finishing costs, discount tiers, rush
fee %, or tax %. Get real numbers from Presprint during Week 1 interviews
and replace the placeholders.

## Roadmap status

- [x] Repo scaffold, Docker Compose, Postgres schema
- [x] Rule-based `/extract-specs` endpoint
- [x] Deterministic `/calculate-quote` endpoint
- [x] `/orders` CRUD
- [x] Frontend demo UI
- [ ] Real Presprint pricing data → `pricing_matrix.json`
- [ ] UAT query logging → training data for `nlp/train_ner.py`
- [ ] Nginx SSL termination + GitHub Actions deploy job (Week 7)
- [ ] UAT sign-off (Week 8)

## Deployment (Week 7)

```bash
docker compose --profile prod up -d
```

This brings up `nginx-proxy` in front of the backend and frontend
containers, using `infra/nginx.conf`. Point a domain's DNS at the host and
add SSL certs (Let's Encrypt/certbot) before going live — see commented
block in `infra/nginx.conf`.
