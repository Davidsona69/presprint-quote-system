"""
Currency + market conversion for imported price lists.

Turning a foreign price list into Cameroonian rates is two steps, and
conflating them is the classic way to get this wrong:

    price_XAF = price_foreign x fx_rate x market_adjustment
                               ^^^^^^^^   ^^^^^^^^^^^^^^^^^
                               arithmetic  an economic claim

The FX rate is a fact you can look up. The market adjustment is an assertion
that two markets are comparable — different paper import costs, labour,
electricity, scale, competition. This module keeps them separate so the
assertion is visible and someone can argue with it, instead of being buried
inside a single mystery number.

Both are read from fx_config.json. Every conversion returns its own provenance
so any converted price can be traced back to the rate and factor that produced
it, on the date it was produced.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "fx_config.json"


class FxError(ValueError):
    """Raised when a conversion cannot be done honestly."""


@dataclass
class Conversion:
    """One converted price, with everything needed to reproduce it."""
    amount_xaf: float
    source_amount: float
    source_currency: str
    fx_rate: float
    fx_as_of: str
    market_factor: float
    market_calibrated: bool
    warnings: list[str] = field(default_factory=list)

    def provenance(self) -> str:
        return (f"{self.source_amount:,.2f} {self.source_currency} "
                f"x {self.fx_rate} (fx {self.fx_as_of}) "
                f"x {self.market_factor} (market) = {self.amount_xaf:,.2f} XAF")


def load_config(path: Path | None = None) -> dict:
    with open(path or CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _staleness(as_of: str, limit_days: int) -> tuple[int | None, str | None]:
    """Age of a quoted rate in days, and a warning if it is past its limit."""
    if as_of == "fixed":
        return None, None
    try:
        quoted = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return None, f"FX rate has an unparseable as_of ({as_of!r}); treat it as unverified."

    age = (date.today() - quoted).days
    if age < 0:
        return age, f"FX rate is dated in the future ({as_of}); check fx_config.json."
    if age > limit_days:
        return age, (f"FX rate is {age} days old (quoted {as_of}). Floating currencies move — "
                     f"refresh fx_config.json and re-import before relying on these prices.")
    return age, None


class Converter:
    """Converts foreign prices to XAF, carrying provenance and complaints."""

    def __init__(self, config: dict | None = None, market_profile: str = "default",
                 market_factor_override: float | None = None):
        self.config = config or load_config()
        self.market_profile = market_profile
        profiles = self.config.get("market_adjustment", {})
        profile = profiles.get(market_profile) or profiles.get("default") or {}

        self.market_factor = (
            market_factor_override if market_factor_override is not None
            else float(profile.get("factor", 1.0))
        )
        self.market_calibrated = bool(profile.get("calibrated", False)) and market_factor_override is None
        self.market_rationale = profile.get("rationale", "")

        if self.market_factor <= 0:
            raise FxError(f"market adjustment factor must be positive, got {self.market_factor}")

    def rate_for(self, currency: str) -> tuple[float, str]:
        currency = currency.strip().upper()
        entry = self.config.get("rates", {}).get(currency)
        if entry is None:
            known = ", ".join(sorted(self.config.get("rates", {})))
            raise FxError(f"No FX rate for {currency!r}. Known: {known}. Add it to ml/fx_config.json.")
        return float(entry["xaf_per_unit"]), str(entry.get("as_of", "unknown"))

    def convert(self, amount: float, currency: str) -> Conversion:
        if amount is None or amount <= 0:
            raise FxError(f"price must be positive, got {amount!r}")

        rate, as_of = self.rate_for(currency)
        warnings: list[str] = []

        _, stale = _staleness(as_of, int(self.config.get("staleness_warning_days", 30)))
        if stale:
            warnings.append(stale)

        if not self.market_calibrated and currency.upper() != "XAF":
            warnings.append(
                "Market adjustment is uncalibrated (factor "
                f"{self.market_factor:g}), so this is an FX conversion only. It is not "
                "a claim about Cameroonian market rates — calibrate it against real "
                "local quotes before presenting these as prices."
            )

        return Conversion(
            amount_xaf=round(amount * rate * self.market_factor, 2),
            source_amount=float(amount),
            source_currency=currency.upper(),
            fx_rate=rate,
            fx_as_of=as_of,
            market_factor=self.market_factor,
            market_calibrated=self.market_calibrated,
            warnings=warnings,
        )

    def summary(self) -> dict:
        return {
            "market_profile": self.market_profile,
            "market_factor": self.market_factor,
            "market_calibrated": self.market_calibrated,
            "market_rationale": self.market_rationale,
        }


def calibrate(local_prices: list[float], foreign_prices_xaf: list[float]) -> dict:
    """
    Work out the market adjustment factor from jobs you have priced both ways.

    Quote the same handful of jobs locally and through the foreign source, FX
    the foreign ones into XAF, and pass both lists here. The median ratio is
    your factor — median rather than mean so one odd job cannot drag it.
    """
    if len(local_prices) != len(foreign_prices_xaf):
        raise FxError("need the same number of local and foreign prices")
    if len(local_prices) < 3:
        raise FxError("calibrate on at least 3 comparable jobs; 5-10 is better")

    ratios = sorted(l / f for l, f in zip(local_prices, foreign_prices_xaf) if f > 0)
    if not ratios:
        raise FxError("no usable pairs")

    n = len(ratios)
    median = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
    return {
        "factor": round(median, 4),
        "n": n,
        "min_ratio": round(ratios[0], 4),
        "max_ratio": round(ratios[-1], 4),
        "spread": round(ratios[-1] - ratios[0], 4),
        "calibrated": True,
    }
