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
from finrobot.engine.compute.coordinators.extractor import (
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


def test_extract_financial_data_timestamp_is_price_as_of():
    """The snapshot's as-of (→ data_fetched_at / the 'As of' pill) rides the PRICE
    canonical's semantic ``as_of`` — the session the displayed current_price
    belongs to — NOT the FINANCIALS fetch time. The two canonicals have
    independent TTLs and can be a full session apart; stamping the FINANCIALS
    fetch mislabels the pill against the fresh headline price (AAPL 2026-07-02:
    pill said 06-30 16:14 while the headline was 07-01's close)."""
    fin = _make_fin()
    price = _make_price()
    fd = extract_financial_data(fin, price)
    assert fd.timestamp == price.provenance.as_of
    # …and NOT the old (wrong) source — the financials fetch instant.
    assert fd.timestamp != fin.provenance.fetched_at


@pytest.mark.parametrize("beta", [-0.248, -1.0, 0.0, 6.0, 100.0])
def test_extract_financial_data_survives_out_of_band_beta(beta):
    """Out-of-band vendor beta must NOT crash extraction (refuse-to-conclude).

    Real vendor glitch: SHEL live beta = −0.248 (FMP and yfinance byte-identical,
    same upstream feed; BP −0.239, EQNR −0.752 — a whole sector compressed). The
    old MarketData.beta = Field(ge=0, le=5) raised ValidationError here, killing
    the entire extraction for every negative-beta energy name. The raw value is now
    stored verbatim; the WACC seed (not the schema) judges the band and substitutes
    the industry proxy. extract_financial_data must pass the raw beta straight
    through without raising.
    """
    fd = extract_financial_data(_make_fin(beta=beta), _make_price())
    assert fd.market.beta == beta


def test_extract_financial_data_carries_is_adr():
    # is_adr must reach MarketData so the family-1 acceptor can read fin.market.is_adr.
    fd = extract_financial_data(_make_fin(country="TW", is_adr=True), _make_price())
    assert fd.market.is_adr is True
    fd_none = extract_financial_data(_make_fin(country="TW"), _make_price())
    assert fd_none.market.is_adr is None


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
    # Structured: the caveat is attributed to the P/E cell.
    assert fd.field_warnings.get("pe") == ["shares_derived"]


def test_extract_financial_data_zero_shares_outstanding_warns():
    """When shares_outstanding is 0, derive from market_cap/price and warn."""
    fd = extract_financial_data(_make_fin(shares_outstanding=0), _make_price())
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("shares_outstanding" in w for w in fd.warnings)


def test_extract_multi_class_uses_price_consistent_shares():
    """A reported count covering only ONE class of a multi-class issuer (e.g.
    yfinance .info for GOOG) diverges from market_cap/price. Per-share valuation
    must divide by the price-consistent (all-class) count, not the single-class
    filing count — else total net_income ÷ single-class shares overstates EPS."""
    # market_cap 3e12 / price 200 = 15e9 implied; reported only 7e9 (one class).
    fd = extract_financial_data(_make_fin(shares_outstanding=7e9), _make_price())
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("diverges" in w and "per-share" in w for w in fd.warnings)
    assert fd.field_warnings.get("pe") == ["shares_derived"]


def test_extract_minor_share_noise_keeps_reported_count():
    """Within tolerance (timestamp drift between financials and price), keep the
    precise reported filing count — do NOT swap in the noisier mc/price value."""
    # 15.3e9 vs 15e9 implied = 2% — under threshold → keep reported.
    fd = extract_financial_data(_make_fin(shares_outstanding=15.3e9), _make_price())
    assert fd.market.shares_outstanding == pytest.approx(15.3e9, rel=1e-6)


def test_extract_marks_market_cap_to_live_price():
    """The provider market_cap can ride a cache-stale profile snapshot that lags
    the live quote (FMP profile mktCap froze at the prior close while the quote
    moved intraday). Since shares is forced onto current_price's basis, the cap
    must be too — market_cap = shares × current_price — else market_cap / P/E /
    EV-EBITDA read ~the day's move below the live price beside them (regression
    2026-06-09: AAPL ~+2%, MU ~+10% on up days)."""
    stale_cap = 15e9 * 196.0  # provider froze ~2% below the live 200 quote
    fin = _make_fin(market_cap=stale_cap, shares_outstanding=15e9)
    provider_pe = fin.pe_ratio
    fd = extract_financial_data(fin, _make_price())  # current_price = 200
    live_cap = 15e9 * 200.0
    assert fd.market.market_cap == pytest.approx(live_cap, rel=1e-9)
    assert fd.market.market_cap != pytest.approx(stale_cap, rel=1e-6)
    assert fd.market.market_cap == pytest.approx(fd.market.shares_outstanding * 200.0, rel=1e-9)
    # P/E tracks the live cap (scaled by the same ratio), preserving provider basis.
    if provider_pe is not None:
        assert fd.market.pe_ratio == pytest.approx(provider_pe * (live_cap / stale_cap), rel=1e-9)


def test_extract_live_cap_flows_into_ev():
    """EV / EV-EBITDA rebuild from the live cap, not the stale provider cap."""
    stale_cap = 15e9 * 196.0
    fd = extract_financial_data(
        _make_fin(market_cap=stale_cap, shares_outstanding=15e9, total_debt=0, total_cash=0),
        _make_price(),
    )
    # zero net debt → EV == live market_cap == shares × current_price
    assert fd.valuation.enterprise_value == pytest.approx(15e9 * 200.0, rel=1e-9)


def test_extract_market_cap_noop_when_shares_derived():
    """Degraded path (no independent share count): shares = market_cap/price, so
    shares × price recovers the provider cap unchanged — mark-to-live never
    fabricates a different cap when there's no real share count to mark with."""
    fd = extract_financial_data(_make_fin(shares_outstanding=None), _make_price())
    assert fd.market.market_cap == pytest.approx(3e12, rel=1e-9)  # provider cap, unchanged
    assert not any("diverges" in w for w in fd.warnings)


def test_extract_financial_data_ev_none_when_debt_missing():
    """N15: EV should be None (not computed with default 0) when total_debt missing."""
    fd = extract_financial_data(_make_fin(total_debt=None), _make_price())
    assert fd.valuation.enterprise_value is None
    assert fd.valuation.ev_ebitda is None
    assert fd.valuation.ev_revenue is None
    assert any("total_debt" in w and "EV" in w for w in fd.warnings)
    # Structured: the caveat is attributed to the EV/EBITDA cell.
    assert fd.field_warnings.get("ev_ebitda") == ["ev_missing_net_debt"]
    # #10: the stored balance itself must preserve None, not fabricate a 0 — the
    # old BalanceSheet default=0 silently turned EV into market_cap downstream.
    assert fd.balance.total_debt is None


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


def test_extract_financial_data_bank_suppresses_gross_margin():
    """Symmetric chokepoint: a bank has no COGS, so gross margin is undefined.
    yfinance serves 0.0 for JPM (no COGS in ``info``) — the extractor must null
    it so the engine model never shows a phantom 0% / ~60% bank gross margin,
    regardless of which provider produced the snapshot (Mode A/B parity)."""
    fd = extract_financial_data(
        _make_fin(
            gross_margin=0.0,  # the yfinance JPM phantom
            industry="Banks - Diversified",
            sector="Financial Services",
        ),
        _make_price(),
    )
    assert fd.income.gross_margin is None
    # Operating margin is meaningful on net revenue for a bank — keep it.
    assert fd.income.operating_margin == 0.28


def test_extract_financial_data_non_bank_keeps_gross_margin():
    """Control: a non-bank financial (insurer) is NOT suppressed by is_bank."""
    fd = extract_financial_data(
        _make_fin(gross_margin=0.47, industry="Insurance", sector="Financial Services"),
        _make_price(),
    )
    assert fd.income.gross_margin == 0.47


# ---------------------------------------------------------------------------
# extract_company_financials
# ---------------------------------------------------------------------------


def test_extract_company_financials_has_debt_cash():
    cf = extract_company_financials(_make_fin())
    assert cf.total_debt == 50e9
    assert cf.total_cash == 20e9


def test_extract_company_financials_bank_suppresses_gross_margin():
    """A bank peer row must not show ~60% (FMP) / 0% (yfinance) gross margin —
    symmetric with the target path."""
    cf = extract_company_financials(
        _make_fin(gross_margin=0.0, industry="Banks - Diversified", sector="Financial Services")
    )
    assert cf.gross_margin is None


def test_extract_company_financials_non_bank_keeps_gross_margin():
    cf = extract_company_financials(_make_fin(gross_margin=0.47))
    assert cf.gross_margin == 0.47


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
    from finrobot.engine.compute.operators.multiples import calculate_multiples

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


class TestExtractCompanyFinancialsCurrencyTags:
    """Currency tags pass through from the provider, untouched by geography.

    The country-based USD rewrite was retired 2026-06-10 (21-ticker probe:
    yfinance financialCurrency 21/21 correct; the rewrite corrupted 7/9 genuine
    USD-reporting foreign issuers). A double-USD foreign issuer is flagged for
    review by audit_foreign_issuer_usd_tags — never silently re-currencied."""

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
            "financial_currency": "USD",
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

    def test_usd_tag_foreign_country_passes_through(self) -> None:
        """The LULU/SHEL class: a USD tag with a foreign country stays USD —
        rewriting it FX-scaled correct statements by ~±27% (the retired bug)."""
        result = extract_company_financials(self._make_peer_fin("LULU", country="Canada"))
        assert result.reporting_currency == "USD"
        assert result.quote_currency == "USD"

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
