"""
Tests for the currency + market conversion used when importing price lists.

The arithmetic is trivial; what these actually protect is the honesty of the
output — that an uncalibrated factor, a stale rate, or an unknown currency
cannot pass silently into something presented as a Cameroonian price.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))

from fx import Converter, FxError, calibrate, load_config  # noqa: E402


@pytest.fixture
def config():
    return load_config()


def test_shipped_config_is_usable(config):
    conv = Converter(config)
    rate, as_of = conv.rate_for("NGN")
    assert rate > 0
    assert as_of != "unknown"


def test_cfa_peg_is_exact(config):
    """XAF is pegged to EUR; that conversion is arithmetic, not a market view."""
    conv = Converter(config)
    assert conv.convert(1, "EUR").amount_xaf == pytest.approx(655.957, abs=0.01)
    assert conv.convert(1000, "XOF").amount_xaf == 1000.0
    assert conv.convert(500, "XAF").amount_xaf == 500.0


def test_conversion_arithmetic(config):
    conv = Converter(config, market_factor_override=1.0)
    rate, _ = conv.rate_for("NGN")
    result = conv.convert(10000, "NGN")
    assert result.amount_xaf == pytest.approx(10000 * rate, abs=0.01)
    assert result.source_currency == "NGN"


def test_market_factor_is_applied_on_top_of_fx(config):
    plain = Converter(config, market_factor_override=1.0).convert(10000, "NGN")
    scaled = Converter(config, market_factor_override=1.25).convert(10000, "NGN")
    assert scaled.amount_xaf == pytest.approx(plain.amount_xaf * 1.25, abs=0.01)


def test_uncalibrated_factor_warns_every_time(config):
    """The shipped config is deliberately uncalibrated; that must be loud."""
    result = Converter(config).convert(10000, "NGN")
    assert any("uncalibrated" in w.lower() for w in result.warnings)
    assert result.market_calibrated is False


def test_local_currency_needs_no_market_disclaimer(config):
    """Converting XAF to XAF makes no cross-market claim."""
    result = Converter(config).convert(10000, "XAF")
    assert not any("uncalibrated" in w.lower() for w in result.warnings)


def test_unknown_currency_is_refused_not_guessed(config):
    with pytest.raises(FxError, match="No FX rate"):
        Converter(config).convert(100, "GBP")


@pytest.mark.parametrize("bad", [0, -5, None])
def test_nonpositive_price_is_refused(config, bad):
    with pytest.raises(FxError):
        Converter(config).convert(bad, "NGN")


def test_stale_rate_warns(config):
    old = (date.today() - timedelta(days=400)).isoformat()
    cfg = json.loads(json.dumps(config))
    cfg["rates"]["NGN"]["as_of"] = old
    result = Converter(cfg).convert(10000, "NGN")
    assert any("days old" in w for w in result.warnings)


def test_fresh_rate_does_not_warn_about_staleness(config):
    cfg = json.loads(json.dumps(config))
    cfg["rates"]["NGN"]["as_of"] = date.today().isoformat()
    result = Converter(cfg).convert(10000, "NGN")
    assert not any("days old" in w for w in result.warnings)


def test_pegged_rates_never_go_stale(config):
    """'fixed' means the peg — no staleness warning however long it sits."""
    result = Converter(config).convert(100, "EUR")
    assert not any("days old" in w for w in result.warnings)


def test_provenance_reproduces_the_price(config):
    result = Converter(config).convert(9500, "NGN")
    text = result.provenance()
    assert "9,500.00 NGN" in text
    assert str(result.fx_rate) in text
    assert result.fx_as_of in text


# ------------------------------------------------------------ calibration ---

def test_calibrate_uses_the_median_ratio():
    # Local quotes run ~1.2x the FX-converted foreign ones, with one outlier.
    local = [1200.0, 1180.0, 1220.0, 1210.0, 5000.0]
    foreign = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
    result = calibrate(local, foreign)
    assert result["factor"] == pytest.approx(1.21, abs=0.01), "median must ignore the outlier"
    assert result["calibrated"] is True
    assert result["n"] == 5


def test_calibrate_refuses_too_few_samples():
    with pytest.raises(FxError, match="at least 3"):
        calibrate([100.0, 110.0], [90.0, 95.0])


def test_calibrate_requires_matching_lists():
    with pytest.raises(FxError, match="same number"):
        calibrate([100.0, 110.0, 120.0], [90.0])
