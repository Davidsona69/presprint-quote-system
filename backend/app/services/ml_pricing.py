"""
ML pricing inference.

Loads a model trained by `ml/train_pricing.py` and applies it to a spec. The
module is written so that *every* failure path degrades to deterministic
pricing rather than to a wrong price:

  - scikit-learn not installed        -> disabled
  - no artifact on disk               -> disabled
  - artifact trained on old features  -> disabled, with a loud reason
  - model failed its own accuracy gate-> disabled (the gate is stored in the
                                         artifact; see train_pricing.py)
  - prediction raises, or comes back
    non-finite / negative / absurd    -> that quote falls back to deterministic

A print shop can survive a quote that is 5% off. It cannot survive a quote of
NaN, or of 12 XAF because a model extrapolated off the end of its training
data. Hence the clamp: predictions are held inside a configurable band around
the deterministic subtotal, and hitting the edge of that band is reported as a
warning on the quote rather than silently accepted.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ml_features import FEATURE_NAMES, feature_row

_lock = threading.Lock()
_state: dict[str, Any] = {"loaded": False, "model": None, "meta": {}, "reason": None, "mtime": None}


def _artifact_path() -> Path:
    return Path(settings.ml_model_path)


def _load() -> None:
    """Load (or reload) the artifact. Called under _lock."""
    path = _artifact_path()

    if not settings.ml_pricing_enabled:
        _state.update(loaded=False, model=None, meta={}, reason="ML pricing is disabled (ML_PRICING_ENABLED=false).", mtime=None)
        return

    if not path.exists():
        _state.update(loaded=False, model=None, meta={}, reason=f"No model artifact at {path}.", mtime=None)
        return

    try:
        import joblib  # noqa: PLC0415 — optional dependency, only needed when ML is on
    except ImportError:
        _state.update(loaded=False, model=None, meta={}, reason="scikit-learn/joblib are not installed in this image (see requirements-ml.txt).", mtime=None)
        return

    try:
        artifact = joblib.load(path)
    except Exception as exc:
        _state.update(loaded=False, model=None, meta={}, reason=f"Could not load {path}: {exc}", mtime=None)
        return

    meta = artifact.get("meta", {})

    # Refuse a model whose feature layout no longer matches the code.
    if meta.get("feature_names") != FEATURE_NAMES:
        _state.update(loaded=False, model=None, meta=meta, mtime=path.stat().st_mtime,
                      reason="Model was trained on a different feature set — retrain with ml/train_pricing.py.")
        return

    # Refuse a model that did not beat the deterministic baseline on held-out
    # data. train_pricing.py records this; see ml/README.md for the rationale.
    if not meta.get("beats_baseline", False):
        _state.update(loaded=False, model=None, meta=meta, mtime=path.stat().st_mtime,
                      reason=("Model did not beat the deterministic baseline on held-out data "
                              f"(model MAE {meta.get('model_mae')}, baseline MAE {meta.get('baseline_mae')}) — "
                              "not used. The rate matrices are the better estimate."))
        return

    _state.update(loaded=True, model=artifact["model"], meta=meta, reason=None, mtime=path.stat().st_mtime)


def _ensure_loaded() -> None:
    """Load on first use, and reload when the artifact is retrained on disk."""
    path = _artifact_path()
    current_mtime = path.stat().st_mtime if path.exists() else None
    if _state["loaded"] and _state["mtime"] == current_mtime:
        return
    with _lock:
        if _state["loaded"] and _state["mtime"] == current_mtime:
            return
        _load()


def status() -> dict:
    """What the API reports about the pricing model. Safe to call anytime."""
    _ensure_loaded()
    meta = _state["meta"] or {}
    return {
        "enabled": settings.ml_pricing_enabled,
        "active": bool(_state["loaded"]),
        "reason": _state["reason"],
        "model_path": str(_artifact_path()),
        "target": meta.get("target"),
        "trained_at": meta.get("trained_at"),
        "training_rows": meta.get("training_rows"),
        "model_mae_xaf": meta.get("model_mae"),
        "baseline_mae_xaf": meta.get("baseline_mae"),
        "improvement_percent": meta.get("improvement_percent"),
    }


def adjust(spec: Any, deterministic_subtotal: float) -> dict | None:
    """
    Predict what Presprint would actually charge for this job.

    Returns None when the deterministic subtotal should stand as-is. Otherwise
    a dict with the adjusted subtotal, the multiplier it implies, and any
    warning worth showing the user.
    """
    _ensure_loaded()
    if not _state["loaded"]:
        return None

    meta = _state["meta"]
    warnings: list[str] = []

    try:
        import numpy as np  # noqa: PLC0415

        row = np.array([feature_row(spec, deterministic_subtotal)], dtype=object)
        raw = float(_state["model"].predict(row)[0])
    except Exception as exc:
        return {
            "subtotal_xaf": deterministic_subtotal,
            "multiplier": 1.0,
            "applied": False,
            "warnings": [f"Pricing model failed on this job ({type(exc).__name__}); priced from the rate matrices instead."],
        }

    # Two training targets are supported — see ml/train_pricing.py.
    if meta.get("target") == "multiplier":
        multiplier = raw
    else:  # "absolute": the model predicts the final subtotal directly
        multiplier = raw / deterministic_subtotal if deterministic_subtotal else 1.0

    if not math.isfinite(multiplier) or multiplier <= 0:
        return {
            "subtotal_xaf": deterministic_subtotal,
            "multiplier": 1.0,
            "applied": False,
            "warnings": ["Pricing model returned an invalid value; priced from the rate matrices instead."],
        }

    lo, hi = settings.ml_multiplier_floor, settings.ml_multiplier_ceiling
    if multiplier < lo or multiplier > hi:
        clamped = min(max(multiplier, lo), hi)
        warnings.append(
            f"Pricing model wanted a {multiplier:.2f}x adjustment, outside the trusted "
            f"{lo:g}–{hi:g}x band — clamped to {clamped:.2f}x. This job may be unlike "
            "anything in the training data; have a human check the price."
        )
        multiplier = clamped

    return {
        "subtotal_xaf": round(deterministic_subtotal * multiplier, 2),
        "multiplier": round(multiplier, 4),
        "applied": True,
        "warnings": warnings,
    }
