"""Canonical-layer FX (class A): a foreign ADR's reporting≠quote snapshot must be
made single-currency BEFORE any EV/multiple forms.

Confirmed live bug (probe 2026-06-09): GET /api/data/TSM/financials returns
enterprise_value = -75.1B because extract_financial_data forms
``EV = market_cap(USD) + total_debt(TWD) - total_cash(TWD)`` on a mixed-currency
NormalizedFinancials — the TWD cash (≈31x the USD nominal) swamps the USD market
cap and flips EV negative, with ev_ebitda/ev_revenue going sub-zero. ``warnings``
ships empty, so the garbage negative multiple surfaces silently to analysts.

Root-cause fix: convert the reporting-currency line items into the QUOTE currency
at the canonical chokepoint (DataLayer._fetch_canonical_uncached, ADR-0006), so
the projection layer only ever sees one currency. The market quote (market_cap /
current_price) is already in the quote currency and is left untouched.

External anchor (live FMP 2026-06-09, TWD→USD ≈ 0.03176):
  market_cap 2.2136T USD · total_debt 1.094T TWD · total_cash 3.383T TWD ·
  revenue 4.114T TWD · op_income 1.9T TWD · D&A 0.6T TWD.
  Pre-fix:  EV ≈ -73B (impossible), ev_ebitda ≈ -0.03, ev_revenue ≈ -0.018.
  Post-fix: EV ≈ +2.14T USD, ev_ebitda ≈ 27x, ev_revenue ≈ 16.4x.
The FX rate is FIXED here (no network) so the assertions are deterministic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.data.normalize.contracts import (
    NormalizedFinancials,
    NormalizedPrice,
    PriceBar,
    Provenance,
)
from finrobot.engine.data.normalize.currency import normalize_canonical_financials_currency

TWD_USD = 0.03176
_NOW = datetime(2026, 6, 9, tzinfo=timezone.utc)


def _prov() -> Provenance:
    return Provenance(provider="fmp", as_of=_NOW, fetched_at=_NOW)


def _tsm_canonical_twd() -> NormalizedFinancials:
    """TSM-shape canonical: TWD reporting line items beside a USD market quote."""
    return NormalizedFinancials(
        ticker="TSM",
        company_name="Taiwan Semiconductor",
        reporting_currency="TWD",
        quote_currency="USD",
        as_of=_NOW,
        revenue=4_113_789_591_000,  # TWD
        net_income=1_933_578_784_000,  # TWD
        operating_income=1_900_000_000_000,  # TWD
        income_tax_expense=200_000_000_000,  # TWD
        interest_expense=6_000_000_000,  # TWD
        depreciation_amortization=600_000_000_000,  # TWD
        total_debt=1_094_130_170_000,  # TWD
        total_cash=3_382_860_143_000,  # TWD
        market_cap=2_213_589_664_000,  # USD (quote currency)
        shares_outstanding=5_186_000_000,
        current_price=427.0,  # USD (quote currency)
        pe_ratio=None,
        forward_eps=300.0,  # TWD per share
        provenance=_prov(),
    )


def _tsm_price_usd() -> NormalizedPrice:
    return NormalizedPrice(
        ticker="TSM",
        quote_currency="USD",
        bars=[
            PriceBar(date=date(2025, 6, 10), close=300.0),
            PriceBar(date=date(2026, 6, 9), close=427.0),
        ],
        current_price=427.0,
        provenance=_prov(),
    )


def _aapl_canonical_usd() -> NormalizedFinancials:
    return NormalizedFinancials(
        ticker="AAPL",
        reporting_currency="USD",
        quote_currency="USD",
        as_of=_NOW,
        revenue=400_000_000_000,
        net_income=100_000_000_000,
        operating_income=120_000_000_000,
        depreciation_amortization=11_000_000_000,
        total_debt=100_000_000_000,
        total_cash=60_000_000_000,
        market_cap=3_000_000_000_000,
        shares_outstanding=15_000_000_000,
        current_price=200.0,
        provenance=_prov(),
    )


# ---------------------------------------------------------------------------
# Baseline: the bug. Un-normalized mixed-currency snapshot → negative EV.
# ---------------------------------------------------------------------------


def test_unconverted_mixed_currency_ev_withheld_by_invariant():
    """Defense-in-depth: if the canonical FX gate (class A) is bypassed/failed and a
    mixed TWD/USD snapshot still reaches extract, the FinancialData cross-currency
    invariant (class B) withholds EV and the EV-multiples (None) rather than forming
    the -75B garbage. Neither layer can emit a negative EV — that was the live bug."""
    fd = extract_financial_data(_tsm_canonical_twd(), _tsm_price_usd())
    assert fd.valuation.enterprise_value is None
    assert fd.valuation.ev_ebitda is None
    assert fd.valuation.ev_revenue is None
    assert any("withheld" in w.lower() for w in fd.warnings)


# ---------------------------------------------------------------------------
# The fix: canonical currency normalization.
# ---------------------------------------------------------------------------


def test_canonical_conversion_makes_single_currency():
    nf = _tsm_canonical_twd()
    out = normalize_canonical_financials_currency(nf, TWD_USD)
    # Both tags collapse to the quote currency — the object is now single-currency.
    assert out.reporting_currency == "USD"
    assert out.quote_currency == "USD"
    # Reporting-currency line items are scaled into the quote currency.
    assert out.revenue == pytest.approx(nf.revenue * TWD_USD)
    assert out.total_debt == pytest.approx(nf.total_debt * TWD_USD)
    assert out.total_cash == pytest.approx(nf.total_cash * TWD_USD)
    assert out.operating_income == pytest.approx(nf.operating_income * TWD_USD)
    assert out.depreciation_amortization == pytest.approx(nf.depreciation_amortization * TWD_USD)
    assert out.forward_eps == pytest.approx(nf.forward_eps * TWD_USD)
    # The market quote is already in the quote currency — left untouched.
    assert out.market_cap == nf.market_cap
    assert out.current_price == nf.current_price


def test_pe_recomputed_on_single_currency_after_conversion():
    """A provider P/E computed across two currencies must be re-derived once both
    sides share the quote currency (or None)."""
    nf = _tsm_canonical_twd()
    out = normalize_canonical_financials_currency(nf, TWD_USD)
    expected_pe = out.market_cap / out.net_income  # both USD now
    assert out.pe_ratio == pytest.approx(expected_pe)


def test_ev_positive_after_canonical_conversion():
    """The whole point: once the canonical is single-currency, extract forms a
    sane positive USD EV and order-of-magnitude-correct multiples."""
    converted = normalize_canonical_financials_currency(_tsm_canonical_twd(), TWD_USD)
    fd = extract_financial_data(converted, _tsm_price_usd())
    assert fd.valuation.enterprise_value is not None
    assert 2.0e12 < fd.valuation.enterprise_value < 2.3e12  # ≈ $2.14T
    assert fd.valuation.ev_ebitda is not None and 24 < fd.valuation.ev_ebitda < 30
    assert fd.valuation.ev_revenue is not None and 15 < fd.valuation.ev_revenue < 18


def test_us_issuer_is_noop():
    """reporting == quote == USD: the common case is an exact identity no-op."""
    nf = _aapl_canonical_usd()
    out = normalize_canonical_financials_currency(nf, 1.0)
    assert out is nf  # untouched, no copy


def test_local_listing_same_currency_is_noop():
    """A local listing (reporting == quote, both non-USD) is single-currency
    already — no conversion, so its EV stays internally consistent in TWD."""
    nf = _tsm_canonical_twd().model_copy(update={"quote_currency": "TWD"})
    out = normalize_canonical_financials_currency(nf, TWD_USD)
    assert out is nf


def test_nonpositive_rate_raises():
    with pytest.raises(ValueError, match="positive"):
        normalize_canonical_financials_currency(_tsm_canonical_twd(), 0.0)


def test_adr_dividend_per_share_reconciled_to_quote_unit():
    """ADR per-ordinary vs per-ADR DPS reconciliation (TSM 2026-07-02): the provider
    per-share DPS is per-ORDINARY-share (22 TWD) while the untouched price is per-ADR
    ($427). FX-scaling alone leaves $0.69 (per-ordinary-USD) beside a per-ADR price/
    yield — DPS/price implies 0.16% vs the provider yield 0.89%. Re-derive to the quote
    unit (yield × price ≈ $3.8) so the DISPLAYED DPS/price/yield are self-consistent."""
    nf = _tsm_canonical_twd().model_copy(
        update={"dividend_per_share": 22.0, "dividend_yield": 0.00892}
    )
    out = normalize_canonical_financials_currency(nf, TWD_USD)
    # Reconciled to per-ADR: yield × per-ADR price, NOT the per-ordinary FX-scaled 22×rate.
    assert out.dividend_per_share == pytest.approx(0.00892 * out.current_price)
    assert out.dividend_per_share > 3.0  # per-ADR ≈ $3.8, not the $0.70 per-ordinary
    # DPS/price now agrees with the provider yield (the whole point).
    assert out.dividend_per_share / out.current_price == pytest.approx(0.00892)
    assert any("per-ordinary-share vs per-ADR-price" in w for w in out.warnings)


def test_us_issuer_dividend_not_reconciled():
    """A US issuer (reporting == quote) whose DPS and yield already agree is the fast-path
    no-op — the reconciliation must not fire (no per-ADR caliber gap)."""
    nf = _aapl_canonical_usd().model_copy(
        update={"dividend_per_share": 1.0, "dividend_yield": 1.0 / 200.0}  # 200 price → 0.5%
    )
    out = normalize_canonical_financials_currency(nf, 1.0)
    assert out is nf  # identity no-op, DPS untouched
    assert out.dividend_per_share == 1.0
