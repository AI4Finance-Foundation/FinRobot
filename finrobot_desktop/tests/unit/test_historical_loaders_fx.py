"""FX normalisation of the historical-band loader (W3-A路 · Bug B).

Foreign ADRs (TSM/SONY/BABA) have FMP report their yearly statements in the
native currency (financial_currency=TWD/JPY) while the ADR trades — and the
band's price history is fetched — in the quote currency (USD). The yearly
EBITDA / net-debt must therefore be converted to the quote currency BEFORE they
meet the USD price in ``_compute_multiple``; otherwise EV/EBITDA mixes
currencies and collapses (TSM live band came out ~0.05x instead of ~23x).

These tests pin the conversion using FMP's real TSM payload shape and confirm
the same-currency (US issuer) path is left untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.data.historical_loaders import load_yearly_financials
from finrobot.engine.data.interface import DataResult


class _FXStubLayer:
    """fetch_historical returns native-currency financials + a quote currency.

    Mirrors the FMP TSM payload: statements in TWD, ADR quoted in USD. Records
    the (reporting, quote) pairs requested so the test can assert the loader
    converts exactly once.
    """

    def __init__(self, *, fin_ccy: str, quote_ccy: str, rate: float) -> None:
        self._fin_ccy = fin_ccy
        self._quote_ccy = quote_ccy
        self._rate = rate
        self.rate_calls: list[tuple[str, str]] = []

    async def fetch_historical(self, data_type: str, ticker: str, years: int) -> list[DataResult]:
        return [
            DataResult(
                data={
                    "fiscal_year": "2024-12-31",
                    "ebitda": 2_752_481_885_000,  # native (TWD for TSM)
                    "total_debt": 1_064_582_700_000,
                    "total_cash": 3_128_297_700_000,
                    "shares_outstanding": 5_180_000_000,
                    "financial_currency": self._fin_ccy,
                    "quote_currency": self._quote_ccy,
                },
                provider="stub",
                ticker=ticker,
                data_type=data_type,
                timestamp=datetime.now(tz=timezone.utc),
            )
        ]

    async def reporting_to_quote_rate(self, reporting_ccy: str, quote_ccy: str) -> float:
        self.rate_calls.append((reporting_ccy, quote_ccy))
        return self._rate


@pytest.mark.asyncio
async def test_load_yearly_financials_fx_normalizes_adr_to_quote_currency():
    rate = 0.0312  # 1 TWD ≈ 0.0312 USD
    layer = _FXStubLayer(fin_ccy="TWD", quote_ccy="USD", rate=rate)

    out = await load_yearly_financials("TSM", layer, years=3)

    assert len(out) == 1
    yf, shares = out[0]
    # EBITDA must be the USD-converted figure, not the raw TWD trillions.
    assert yf.ebitda == pytest.approx(2_752_481_885_000 * rate)
    # net_debt = (total_debt − total_cash) also converted to the quote currency.
    assert yf.net_debt == pytest.approx((1_064_582_700_000 - 3_128_297_700_000) * rate)
    # Share count is currency-neutral — never scaled.
    assert shares == 5_180_000_000
    # Rate fetched exactly once (per ticker, not per year).
    assert layer.rate_calls == [("TWD", "USD")]


@pytest.mark.asyncio
async def test_load_yearly_financials_no_fx_for_same_currency():
    # US issuer: financial_currency == quote_currency → no FX call, raw values kept.
    layer = _FXStubLayer(fin_ccy="USD", quote_ccy="USD", rate=0.5)

    out = await load_yearly_financials("AAPL", layer, years=3)

    yf, _ = out[0]
    assert yf.ebitda == pytest.approx(2_752_481_885_000)  # untouched (rate not applied)
    assert layer.rate_calls == []


class _FXFailLayer(_FXStubLayer):
    async def reporting_to_quote_rate(self, reporting_ccy: str, quote_ccy: str) -> float:
        from finrobot.engine.data.interface import ProviderError

        raise ProviderError("FX provider down")


@pytest.mark.asyncio
async def test_load_yearly_financials_fx_unavailable_refuses_band():
    """FX due but unavailable must NOT silently apply 1.0: the band's multiple
    mixes the native financial leg with the USD price leg in one number — the
    ~0.05x TSM garbage. The loader refuses (empty → no band) instead, honoring
    fx.py's 'never fall back to 1.0' contract (the canonical path's sibling)."""
    layer = _FXFailLayer(fin_ccy="TWD", quote_ccy="USD", rate=0.0)

    out = await load_yearly_financials("TSM", layer, years=3)

    assert out == []


class _MissingBalanceLayer(_FXStubLayer):
    async def fetch_historical(self, data_type: str, ticker: str, years: int) -> list[DataResult]:
        rows = await super().fetch_historical(data_type, ticker, years)
        # Simulate a year whose balance rows failed to align: debt/cash absent.
        del rows[0].data["total_debt"]
        del rows[0].data["total_cash"]
        return rows


@pytest.mark.asyncio
async def test_load_yearly_financials_missing_balance_leg_keeps_net_debt_none():
    """None ≠ 0: a missing balance leg means UNKNOWN net debt — filling 0
    fabricated a debt-free EV (band skewed low for levered issuers). The year
    keeps net_debt=None and the EV/EBITDA sample for it is skipped by
    _compute_multiple."""
    layer = _MissingBalanceLayer(fin_ccy="USD", quote_ccy="USD", rate=1.0)

    out = await load_yearly_financials("AAPL", layer, years=3)

    yf, _ = out[0]
    assert yf.net_debt is None


# ---------------------------------------------------------------------------
# fetch_reverse_multiple_band — the door that revives the EV/EBITDA reverse row.
# Pins: a real band yields (p25, p75) + sample_count; a too-thin band is withheld
# (no degenerate point); a degenerate/non-positive band is withheld.
# ---------------------------------------------------------------------------


def _band(*, p25, p75, sample_count, current=24.0):
    from finrobot.engine.primitives.historical_valuation import HistoricalBand

    return HistoricalBand(
        metric="ev_ebitda",
        current=current,
        median=(p25 + p75) / 2 if p25 and p75 else None,
        p25=p25,
        p75=p75,
        p90=p75,
        timeline=[],
        sample_count=sample_count,
        warnings=[],
    )


@pytest.mark.asyncio
async def test_fetch_reverse_multiple_band_returns_spread(monkeypatch):
    from finrobot.engine.data import historical_loaders as hl

    async def _fake(ticker, metric, years, data_layer, *, current_override=None):
        return _band(p25=20.0, p75=30.0, sample_count=900)

    monkeypatch.setattr(hl, "compute_bands_via_data_layer", _fake)
    spread = await hl.fetch_reverse_multiple_band("AAPL", "ev_ebitda", object())
    assert spread is not None
    assert (spread.p25, spread.p75, spread.sample_count) == (20.0, 30.0, 900)


@pytest.mark.asyncio
async def test_fetch_reverse_multiple_band_withholds_thin_history(monkeypatch):
    """Below the sample floor the band carries no distribution — p25/p75 would
    echo one multiple dressed as a range. Withhold rather than emit a fake range."""
    from finrobot.engine.data import historical_loaders as hl

    async def _fake(ticker, metric, years, data_layer, *, current_override=None):
        return _band(p25=23.0, p75=23.0, sample_count=hl._MIN_BAND_SAMPLES - 1)

    monkeypatch.setattr(hl, "compute_bands_via_data_layer", _fake)
    assert await hl.fetch_reverse_multiple_band("IPO", "ev_ebitda", object()) is None


@pytest.mark.asyncio
async def test_fetch_reverse_multiple_band_withholds_nonpositive_band(monkeypatch):
    from finrobot.engine.data import historical_loaders as hl

    async def _fake(ticker, metric, years, data_layer, *, current_override=None):
        return _band(p25=None, p75=None, sample_count=900)

    monkeypatch.setattr(hl, "compute_bands_via_data_layer", _fake)
    assert await hl.fetch_reverse_multiple_band("X", "ev_ebitda", object()) is None


@pytest.mark.asyncio
async def test_fetch_reverse_multiple_band_none_layer_returns_none():
    from finrobot.engine.data import historical_loaders as hl

    assert await hl.fetch_reverse_multiple_band("X", "ev_ebitda", None) is None
