"""
Tests for the ML pricing layer.

The point of most of these is not that the model is accurate — accuracy is a
property of Presprint's data, not of this code. The point is that every way the
model can be wrong, missing, stale or unhinged ends with a defensible quote
rather than a bad one.
"""
import math

import pytest

from app.core.config import settings
from app.schemas.schemas import BenchmarkSpec, BookSpec
from app.services import ml_pricing, pricing
from app.services.ml_features import FEATURE_NAMES, feature_row


@pytest.fixture(autouse=True)
def _reset_ml_state():
    """Each test starts with the loader cache cleared."""
    ml_pricing._state.update(loaded=False, model=None, meta={}, reason=None, mtime=None)
    yield
    ml_pricing._state.update(loaded=False, model=None, meta={}, reason=None, mtime=None)


BOOK = BookSpec(item_type="novel", quantity=800, page_count=128, trim_size="A5",
                interior_gsm=80, cover_gsm=250, binding="perfect",
                cover_finish="glossy", color_mode="black_white", urgency="standard")


class _ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return [self.value] * len(X)


class _ExplodingModel:
    """Module level so joblib can pickle it."""

    def predict(self, X):
        raise RuntimeError("boom")


def _meta(**over):
    base = {"target": "multiplier", "feature_names": FEATURE_NAMES,
            "beats_baseline": True, "model_mae": 50000.0, "baseline_mae": 138000.0}
    base.update(over)
    return base


def _save(tmp_path, model, meta):
    joblib = pytest.importorskip("joblib")
    path = tmp_path / "m.joblib"
    joblib.dump({"model": model, "meta": meta}, path)
    return path


def _use(monkeypatch, path):
    monkeypatch.setattr(settings, "ml_pricing_enabled", True)
    monkeypatch.setattr(settings, "ml_model_path", str(path))


# ------------------------------------------------------------- features ----

def test_feature_row_is_stable_and_typed():
    row = feature_row(BOOK, 1474200.0)
    assert len(row) == len(FEATURE_NAMES)
    f = dict(zip(FEATURE_NAMES, row))
    assert f["quantity"] == 800
    assert f["deterministic_subtotal"] == 1474200.0
    assert f["category"] == "book"
    assert f["binding"] == "perfect"


def test_unstated_numerics_are_nan_not_zero():
    """A book with no stated page count is not a 0-page book."""
    row = dict(zip(FEATURE_NAMES, feature_row(BookSpec(quantity=10), 5000.0)))
    assert math.isnan(row["page_count"])
    assert math.isnan(row["interior_gsm"])


def test_features_accept_a_csv_style_row():
    """Training reads dicts of strings; inference passes Pydantic specs."""
    row = dict(zip(FEATURE_NAMES, feature_row(
        {"category": "merch", "quantity": "150", "placements": "front|back",
         "color_count": "3", "urgency": "high"}, 500000.0)))
    assert row["quantity"] == 150
    assert row["n_placements"] == 2
    assert row["is_rush"] == 1.0


# ------------------------------------------------------------ fallbacks ----

def test_disabled_by_default_means_deterministic_pricing(monkeypatch):
    monkeypatch.setattr(settings, "ml_pricing_enabled", False)
    assert ml_pricing.adjust(BOOK, 1474200.0) is None

    quote = pricing.calculate_quote(BOOK)
    assert quote["pricing_method"] == "deterministic"
    assert quote["ml_multiplier"] is None
    assert quote["subtotal_xaf"] == quote["deterministic_subtotal_xaf"]


def test_missing_artifact_is_reported_not_crashed(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path / "nope.joblib")
    assert ml_pricing.adjust(BOOK, 1474200.0) is None
    status = ml_pricing.status()
    assert status["active"] is False
    assert "No model artifact" in status["reason"]


def test_model_that_lost_to_the_rate_matrices_is_refused(monkeypatch, tmp_path):
    """The whole point of the held-out gate: a worse model must not ship."""
    _use(monkeypatch, _save(tmp_path, _ConstantModel(1.5),
         _meta(beats_baseline=False, model_mae=200000.0, baseline_mae=138000.0)))
    assert ml_pricing.adjust(BOOK, 1474200.0) is None
    assert "did not beat the deterministic baseline" in ml_pricing.status()["reason"]


def test_model_trained_on_stale_features_is_refused(monkeypatch, tmp_path):
    _use(monkeypatch, _save(tmp_path, _ConstantModel(1.1),
         _meta(feature_names=["quantity", "gsm"])))
    assert ml_pricing.adjust(BOOK, 1474200.0) is None
    assert "different feature set" in ml_pricing.status()["reason"]


def test_a_model_that_raises_falls_back_to_the_rate_matrices(monkeypatch, tmp_path):
    _use(monkeypatch, _save(tmp_path, _ExplodingModel(), _meta()))
    result = ml_pricing.adjust(BOOK, 1474200.0)
    assert result["applied"] is False
    assert result["subtotal_xaf"] == 1474200.0
    assert "priced from the rate matrices" in result["warnings"][0]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -2.0, 0.0])
def test_nonsense_predictions_never_reach_a_quote(monkeypatch, tmp_path, bad):
    _use(monkeypatch, _save(tmp_path, _ConstantModel(bad), _meta()))
    result = ml_pricing.adjust(BOOK, 1474200.0)
    assert result["applied"] is False
    assert result["subtotal_xaf"] == 1474200.0


# ------------------------------------------------------------- clamping ----

def test_wild_multiplier_is_clamped_and_flagged(monkeypatch, tmp_path):
    _use(monkeypatch, _save(tmp_path, _ConstantModel(9.0), _meta()))
    result = ml_pricing.adjust(BOOK, 1000000.0)
    assert result["applied"] is True
    assert result["multiplier"] == settings.ml_multiplier_ceiling
    assert "have a human check the price" in result["warnings"][0]


def test_sane_multiplier_passes_through(monkeypatch, tmp_path):
    _use(monkeypatch, _save(tmp_path, _ConstantModel(0.9), _meta()))
    result = ml_pricing.adjust(BOOK, 1000000.0)
    assert result["applied"] is True
    assert result["multiplier"] == 0.9
    assert result["subtotal_xaf"] == 900000.0
    assert result["warnings"] == []


# --------------------------------------------------- quote integration ----

def test_adjustment_shows_as_its_own_line_item(monkeypatch, tmp_path):
    """The deterministic breakdown must stay intact and legible."""
    _use(monkeypatch, _save(tmp_path, _ConstantModel(0.9), _meta()))
    quote = pricing.calculate_quote(BOOK)
    assert quote["pricing_method"] == "ml_adjusted"
    assert quote["ml_multiplier"] == 0.9

    labels = [li["label"] for li in quote["breakdown"]]
    assert any("Interior paper" in l for l in labels), "rate-card lines must survive"
    assert labels[-1].startswith("Market adjustment")

    # The line items still sum to the adjusted subtotal.
    assert sum(li["amount_xaf"] for li in quote["breakdown"]) == pytest.approx(
        quote["subtotal_xaf"], abs=0.01)


def test_absolute_target_is_converted_to_a_multiplier(monkeypatch, tmp_path):
    _use(monkeypatch, _save(tmp_path, _ConstantModel(1200000.0), _meta(target="absolute")))
    result = ml_pricing.adjust(BenchmarkSpec(quantity=100), 1000000.0)
    assert result["multiplier"] == 1.2
    assert result["subtotal_xaf"] == 1200000.0
