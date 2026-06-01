"""Unit tests for extractor.py.

ADR-0006 Step 4: extractor functions now accept ``NormalizedFinancials`` /
``NormalizedPrice`` instead of raw ``DataResult``.  Fixtures wrap raw dicts
with ``normalize_financials`` / ``normalize_price`` (the same path a
``DataLayer.fetch_canonical`` consumer would take).
"""

import pytest
from datetime import date, datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.compute.extractor import (
    extract_financial_data,
    extract_company_financials,
    extract_price_history,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_fin(**overrides):
    """Build a NormalizedFinancials from a representative raw dict."""
    data = dict(
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.47,
        operating_margin=0.28,
        pe_ratio=28.5,
        market_cap=3e12,
        shares_outstanding=15e9,
        current_price=200.0,
        total_debt=50e9,
        total_cash=20e9,
    )
    data.update(overrides)
    raw = DataResult(
        data=data,
        provider="yfinance",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_financials(raw)


def _make_price():
    """Build a NormalizedPrice from a representative raw dict."""
    prices = [
        {"date": "2024-01-01", "close": 180.0},
        {"date": "2024-06-01", "close": 220.0},
        {"date": "2024-12-01", "close": 200.0},
    ]
    raw = DataResult(
        data={"current_price": 200.0, "price_history": prices},
        provider="yfinance",
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_price(raw)


def _make_price_from(bars: list[dict]):
    last = bars[-1].get("close")
    raw = DataResult(
        data={"current_price": last, "price_history": bars},
        provider="fmp",
        ticker="TSLA",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_price(raw)


# ---------------------------------------------------------------------------
# extract_financial_data
# ---------------------------------------------------------------------------


def test_extract_financial_data_valid():
    fd = extract_financial_data(_make_fin(), _make_price())
    assert fd.ticker == "AAPL"
    assert fd.income.revenue == 100e9
    assert fd.income.ebitda == 35e9
    assert fd.income.gross_margin == 0.47


def test_extract_financial_data_dual_ebitda_caliber():
    """EBITDA is recomputed from absolute line items in two calibers; the
    opaque provider ebitda field (here deliberate garbage) is ignored.

    External baseline — TSLA TTM Q2'25–Q1'26 (FMP quarterly statements,
    D&A from cash flow): operating EBITDA 11.188B → EV/EBITDA 147x;
    reported EBITDA 12.017B → EV/EBITDA 137x. EV = 1.6465T."""
    fd = extract_financial_data(
        _make_fin(
            revenue=97.879e9,
            ebitda=999e9,  # garbage provider field — must NOT leak through
            net_income=3.876e9,
            operating_income=4.897e9,
            income_tax_expense=1.511e9,
            interest_expense=0.339e9,
            depreciation_amortization=6.291e9,
            market_cap=1_653_868_859_200,
            total_debt=9.229e9,
            total_cash=16.603e9,
        ),
        _make_price(),
    )
    # Operating caliber (EBIT + D&A) is primary and what the financials card shows.
    assert fd.income.ebitda == pytest.approx(11.188e9)
    assert fd.valuation.ebitda_operating == pytest.approx(11.188e9)
    assert fd.valuation.ebitda_reported == pytest.approx(12.017e9)
    assert fd.valuation.ev_ebitda == pytest.approx(147.2, abs=0.5)
    assert fd.valuation.ev_ebitda_reported == pytest.approx(137.0, abs=0.5)
    # Reported caliber sits above operating (TSLA interest income), and the
    # garbage 999B provider field never reaches the multiple.
    assert fd.valuation.ev_ebitda > fd.valuation.ev_ebitda_reported
    assert fd.valuation.ev_ebitda > 100


def test_extract_financial_data_no_fiscal_period_when_provider_omits_it():
    """TTM single-year fetches don't carry fiscal_year — field stays None,
    downstream falls back to timestamp.year."""
    fd = extract_financial_data(_make_fin(), _make_price())
    assert fd.fiscal_period_end is None


def test_extract_financial_data_reads_fiscal_year_iso_string():
    """yfinance historical-fetch shape: fiscal_year='2024-09-30' → parsed date."""
    fd = extract_financial_data(_make_fin(fiscal_year="2024-09-30"), _make_price())
    assert fd.fiscal_period_end == date(2024, 9, 30)


def test_extract_financial_data_reads_date_iso_string():
    """FMP historical-fetch shape: date='2023-12-31' → parsed date.
    Live NVDA bug was that this never got read; assert the contract."""
    fd = extract_financial_data(_make_fin(date="2023-12-31"), _make_price())
    assert fd.fiscal_period_end == date(2023, 12, 31)


def test_extract_financial_data_unparseable_fiscal_year_returns_none():
    """Garbage fiscal_year string shouldn't crash extraction — just skip the
    field so downstream falls back to timestamp."""
    fd = extract_financial_data(_make_fin(fiscal_year="not-a-date"), _make_price())
    assert fd.fiscal_period_end is None


def test_extract_financial_data_missing_revenue_raises():
    with pytest.raises(ValueError, match="revenue"):
        extract_financial_data(_make_fin(revenue=None), _make_price())


def test_extract_financial_data_computes_ev():
    fd = extract_financial_data(_make_fin(), _make_price())
    # EV = 3e12 + 50e9 - 20e9 = 3.03e12
    assert abs(fd.valuation.enterprise_value - 3.03e12) < 1e6


def test_extract_financial_data_ev_ebitda():
    fd = extract_financial_data(_make_fin(), _make_price())
    assert fd.valuation.ev_ebitda is not None
    assert abs(fd.valuation.ev_ebitda - fd.valuation.enterprise_value / fd.income.ebitda) < 1e-6


def test_extract_financial_data_ev_ebitda_none_when_negative_ebitda():
    fd = extract_financial_data(_make_fin(ebitda=-1e9), _make_price())
    assert fd.valuation.ev_ebitda is None


def test_extract_financial_data_zero_debt_cash():
    fd = extract_financial_data(_make_fin(total_debt=0, total_cash=0), _make_price())
    assert abs(fd.valuation.enterprise_value - fd.market.market_cap) < 1


def test_extract_financial_data_missing_shares_outstanding_warns():
    """When shares_outstanding is missing, derive from market_cap/price and warn."""
    fd = extract_financial_data(_make_fin(shares_outstanding=None), _make_price())
    # Derived: market_cap / current_price = 3e12 / 200 = 15e9
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("shares_outstanding" in w for w in fd.warnings)


def test_extract_financial_data_zero_shares_outstanding_warns():
    """When shares_outstanding is 0, derive from market_cap/price and warn."""
    fd = extract_financial_data(_make_fin(shares_outstanding=0), _make_price())
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("shares_outstanding" in w for w in fd.warnings)


def test_extract_financial_data_ev_none_when_debt_missing():
    """N15: EV should be None (not computed with default 0) when total_debt missing."""
    fd = extract_financial_data(_make_fin(total_debt=None), _make_price())
    assert fd.valuation.enterprise_value is None
    assert fd.valuation.ev_ebitda is None
    assert fd.valuation.ev_revenue is None
    assert any("total_debt" in w and "EV" in w for w in fd.warnings)


def test_extract_financial_data_ev_none_when_cash_missing():
    """N15: EV should be None when total_cash missing."""
    fd = extract_financial_data(_make_fin(total_cash=None), _make_price())
    assert fd.valuation.enterprise_value is None
    assert any("total_cash" in w and "EV" in w for w in fd.warnings)


def test_extract_financial_data_ev_none_when_both_missing():
    """N15: Warning should list both missing components."""
    fd = extract_financial_data(_make_fin(total_debt=None, total_cash=None), _make_price())
    assert fd.valuation.enterprise_value is None
    assert any("total_debt" in w and "total_cash" in w for w in fd.warnings)


# ---------------------------------------------------------------------------
# None ≠ 0: missing income-statement figures stay None (BUG #5 cluster)
# ---------------------------------------------------------------------------


def test_extract_financial_data_ebitda_none_when_missing():
    """Missing EBITDA (no operating components, no provider ebitda) must stay
    None — not fabricated as 0, which would read as a going-concern signal and
    poison EV/EBITDA. Provider gave neither operating_income/D&A nor ebitda."""
    fd = extract_financial_data(_make_fin(ebitda=None), _make_price())
    assert fd.income.ebitda is None
    assert fd.valuation.ebitda_operating is None
    assert fd.valuation.ev_ebitda is None


def test_extract_financial_data_net_income_none_when_missing():
    """Missing net income stays None, not 0 — 0 would mean a break-even firm and
    silently zero out derived per-share/tax-rate inputs downstream."""
    fd = extract_financial_data(_make_fin(net_income=None), _make_price())
    assert fd.income.net_income is None


def test_extract_financial_data_margins_none_when_missing():
    """Missing gross/operating margin stay None, not 0% — 0% margin is a
    distinct (going-concern) signal from 'provider didn't report it'."""
    fd = extract_financial_data(_make_fin(gross_margin=None, operating_margin=None), _make_price())
    assert fd.income.gross_margin is None
    assert fd.income.operating_margin is None


# ---------------------------------------------------------------------------
# extract_company_financials
# ---------------------------------------------------------------------------


def test_extract_company_financials_has_debt_cash():
    cf = extract_company_financials(_make_fin())
    assert cf.total_debt == 50e9
    assert cf.total_cash == 20e9


def test_extract_company_financials_uses_operating_ebitda_caliber():
    """D1: peer EBITDA must be the operating caliber (EBIT + D&A), recomputed
    from line items, NOT the opaque provider ``ebitda`` field — otherwise the
    peer numerator differs from the target's and the comps table mixes calibers.

    Baseline (same TSLA TTM line items as the target dual-caliber test):
    operating EBITDA = operating_income 4.897B + D&A 6.291B = 11.188B."""
    cf = extract_company_financials(
        _make_fin(
            ebitda=999e9,  # garbage provider field — must NOT leak through
            operating_income=4.897e9,
            depreciation_amortization=6.291e9,
        )
    )
    assert cf.ebitda == pytest.approx(11.188e9)


def test_extract_company_financials_falls_back_to_reported_ebitda():
    """When operating components are absent the peer falls back to the provider
    ebitda — the same fallback the target uses, so neither side fabricates."""
    cf = extract_company_financials(_make_fin())  # no operating_income/D&A
    assert cf.ebitda == 35e9


def test_extract_company_financials_debt_cash_none_when_missing():
    """D2: a peer whose provider omits total_debt/total_cash must carry None
    (not 0) so calculate_multiples withholds EV instead of fabricating
    EV=market_cap and poisoning the peer median."""
    from finrobot.engine.compute.multiples import calculate_multiples

    cf = extract_company_financials(_make_fin(total_debt=None, total_cash=None))
    assert cf.total_debt is None
    assert cf.total_cash is None
    computed = calculate_multiples(cf)
    assert computed.enterprise_value is None
    assert computed.ev_ebitda is None
    assert computed.ev_revenue is None
    # P/E is equity-only and still computable.
    assert computed.pe_ratio is not None


def test_extract_company_financials_missing_revenue_raises():
    """Missing revenue must raise so the caller drops the peer rather than
    comparing a zero-revenue row."""
    with pytest.raises(ValueError, match="revenue"):
        extract_company_financials(_make_fin(revenue=None))


# ---------------------------------------------------------------------------
# 52-week window tests
# ---------------------------------------------------------------------------


def test_52w_excludes_prices_outside_trailing_year():
    """Regression: FMP's timeseries=365 returns 365 *trading* days (~17 months).
    The early-2025 low must NOT count toward the 52-week low. Window is anchored
    on the most recent bar (2026-05-27), so cutoff is 2025-05-27.
    """
    bars = [
        {"date": "2024-12-10", "close": 221.86},  # ~17mo ago — OUTSIDE 52wk
        {"date": "2025-03-01", "close": 250.00},  # OUTSIDE 52wk
        {"date": "2025-06-01", "close": 300.00},  # inside (lowest in-window)
        {"date": "2025-12-16", "close": 489.88},  # inside (highest in-window)
        {"date": "2026-05-27", "close": 440.36},  # last bar / anchor
    ]
    fd = extract_financial_data(_make_fin(), _make_price_from(bars))
    assert fd.market.price_52w_low == 300.00, "out-of-window 221.86 leaked into 52w low"
    assert fd.market.price_52w_high == 489.88


def test_52w_uses_intraday_high_low_not_close():
    """52-week high/low should use intraday high/low (what brokers show), not the
    max/min of closing prices. serietype=line stripped these, capping the high.
    """
    bars = [
        {"date": "2025-06-01", "close": 400.0, "high": 405.0, "low": 395.0},
        {"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0},
    ]
    fd = extract_financial_data(_make_fin(), _make_price_from(bars))
    assert fd.market.price_52w_high == 450.0, "should be intraday high, not max close 440"
    assert fd.market.price_52w_low == 395.0, "should be intraday low, not min close 400"


def test_52w_falls_back_to_close_when_intraday_missing():
    """Close-only providers (or legacy cache rows) must still yield 52w from close."""
    bars = [
        {"date": "2025-06-01", "close": 300.0},
        {"date": "2026-05-27", "close": 440.0},
    ]
    fd = extract_financial_data(_make_fin(), _make_price_from(bars))
    assert fd.market.price_52w_high == 440.0
    assert fd.market.price_52w_low == 300.0


# ---------------------------------------------------------------------------
# extract_price_history
# ---------------------------------------------------------------------------


def test_extract_price_history_valid():
    ph = extract_price_history(_make_price())
    assert ph.ticker == "AAPL"
    assert ph.high_52w == 220.0
    assert ph.low_52w == 180.0
    assert abs(ph.avg_price - (180.0 + 220.0 + 200.0) / 3) < 1e-6


# ---------------------------------------------------------------------------
# Currency override (carried through normalize_financials)
# ---------------------------------------------------------------------------


class TestExtractCompanyFinancialsCurrencyOverride:
    """ADR currency-override: when yfinance mis-tags financialCurrency=USD for
    a foreign issuer, the country field must correct it so FX normalization runs."""

    def _make_peer_fin(self, ticker: str, **overrides: object):
        data: dict[str, object] = {
            "revenue": 2_500_000e6,
            "ebitda": 800_000e6,
            "net_income": 600_000e6,
            "gross_margin": 0.55,
            "operating_margin": 0.35,
            "pe_ratio": 20.0,
            "market_cap": 650e9,
            "total_debt": 320_000e6,
            "total_cash": 1_700_000e6,
            "financial_currency": "USD",  # provider mis-tag
            "quote_currency": "USD",
        }
        data.update(overrides)  # type: ignore[arg-type]
        raw = DataResult(
            data=data,
            provider="yfinance",
            ticker=ticker,
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        return normalize_financials(raw)

    def test_tsm_adr_country_taiwan_overrides_usd_to_twd(self) -> None:
        """TSM (no '.' suffix) with country=Taiwan: financial_currency="USD" is
        overridden to "TWD" so FX normalization will convert IS/BS items."""
        result = extract_company_financials(self._make_peer_fin("TSM", country="Taiwan"))
        assert result.reporting_currency == "TWD", (
            f"Expected TWD, got {result.reporting_currency} — FX override not applied"
        )
        assert result.quote_currency == "USD"

    def test_asml_adr_country_netherlands_overrides_usd_to_eur(self) -> None:
        """ASML (no '.' suffix) with country=Netherlands: USD → EUR."""
        result = extract_company_financials(self._make_peer_fin("ASML", country="Netherlands"))
        assert result.reporting_currency == "EUR"

    def test_us_issuer_no_override(self) -> None:
        """AAPL: country=None → USD tag is trusted as-is."""
        result = extract_company_financials(self._make_peer_fin("AAPL", country=None))
        assert result.reporting_currency == "USD"

    def test_local_listing_no_override(self) -> None:
        """2330.TW: ticker has '.', provider already returns TWD correctly —
        the override must NOT apply (we trust the provider for local listings)."""
        result = extract_company_financials(
            self._make_peer_fin("2330.TW", country="Taiwan", financial_currency="TWD")
        )
        assert result.reporting_currency == "TWD"

    def test_adr_with_correct_non_usd_tag_not_overridden(self) -> None:
        """If provider correctly tags TSM as TWD, the override must not clobber it."""
        result = extract_company_financials(
            self._make_peer_fin("TSM", country="Taiwan", financial_currency="TWD")
        )
        assert result.reporting_currency == "TWD"

    def test_unknown_country_trusts_provider_tag(self) -> None:
        """Country not in the mapping: fall back to provider tag (USD)."""
        result = extract_company_financials(self._make_peer_fin("XYZ", country="Narnia"))
        assert result.reporting_currency == "USD"
