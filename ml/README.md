# ML Cost Adjustment — Stretch Goal, Not MVP

The proposal's original plan calls for an XGBoost/RandomForest regression
model trained on historical production logs. In practice, most 8-week
internship projects at a business like Presprint won't have clean,
sufficiently large historical job data on day one.

**The system does not depend on this.** `backend/app/services/pricing.py`
implements a deterministic, auditable pricing formula that is the real
production cost engine. This directory is where an ML layer plugs in
*if and only if* real data materializes.

## When to build this

Only pursue this once you have Presprint's actual historical job records —
ideally 200+ rows with: paper type, quantity, finishing, and the *actual*
final price charged (not the list price — the real negotiated/adjusted one).

## How it should plug in (don't replace pricing.py — adjust it)

Train a regression model that predicts a **multiplier** on top of the
deterministic subtotal, not an absolute price from scratch. This:
- keeps quotes explainable to Presprint's sales/finance team
- degrades gracefully if the model is wrong (worst case: multiplier ≈ 1.0)
- lets you validate the model against the deterministic baseline directly

```python
# sketch — not wired up yet
adjustment = ml_model.predict(feature_vector)  # e.g. 0.95–1.15
adjusted_subtotal = deterministic_subtotal * adjustment
```

## Suggested feature set

- quantity (log-transformed — pricing isn't linear at scale)
- paper gsm, finish type (one-hot)
- number of finishing operations
- day-of-week / rush flag
- historical client segment, if tracked

## Minimum bar before shipping

Only deploy this if it beats the deterministic-only baseline on a held-out
set of real quotes (lower MAE against actual final invoiced price). If it
doesn't clear that bar, the deterministic engine alone is the better,
more honest deliverable — say so plainly in the final report rather than
forcing an ML component in for its own sake.
