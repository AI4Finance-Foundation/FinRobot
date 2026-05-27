"""Tests for engine/compute/fx_normalize.py — peer comps USD normalization."""

from __future__ import annotations

import math

import pytest

from finrobot.engine.compute.fx_normalize import normalize_company_to_usd
from finrobot.engine.models.financial import CompanyFinancials


def _peer(
    *,
    ticker: str,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
    revenue: float = 100e9,
    ebitda: float = 30e9,
    net_income: float = 20e9,
    market_cap: float = 500e9,
    total_debt: float = 10e9,
    total_cash: float = 5e9,
    enterprise_value: float | None = None,
) -> CompanyFinancials:
    return CompanyFinancials(
        ticker=ticker,
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        market_cap=market_cap,
        total_debt=total_debt,
        total_cash=total_cash,
        gross_margin=0.5,
        operating_margin=0.3,
        enterprise_value=enterprise_value,
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
    )


class TestNoOpFastPath:
    def test_pure_usd_company_returned_unchanged(self):
        """US peer (both currencies USD): returns the same instance, no copy."""
        company = _peer(ticker="NVDA")
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=999.0, quote_fx_rate_to_usd=999.0
        )
        # Identity check — fast path must not allocate a new model.
        assert result is company
        # Rates are intentionally absurd to prove they were ignored.
        assert result.revenue == 100e9


class TestAdrShape:
    """ADR shape: reporting currency differs from quote currency. Only IS/BS
    items need conversion; market_cap is already USD."""

    def test_tsm_adr_only_is_bs_scaled(self):
        """TSM-shape: reporting=TWD financials, quote=USD market_cap.
        Scale IS/BS by ~1/32 (TWD/USD), leave market_cap untouched."""
        rate = 1 / 32.0
        company = _peer(
            ticker="TSM",
            reporting_currency="TWD",
            quote_currency="USD",
            revenue=2_500_000e6,  # 2.5T TWD ≈ 78B USD
            ebitda=1_000_000e6,  # 1T TWD ≈ 31B USD
            net_income=800_000e6,
            market_cap=650e9,  # already USD
            total_debt=320_000e6,
            total_cash=1_700_000e6,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=rate, quote_fx_rate_to_usd=1.0
        )
        assert result is not company
        assert result.reporting_currency == "USD"
        assert result.quote_currency == "USD"
        # IS/BS items scaled to USD (allow tiny float jitter).
        assert math.isclose(result.revenue, 2_500_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.ebitda, 1_000_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.net_income, 800_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.total_debt, 320_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.total_cash, 1_700_000e6 * rate, rel_tol=1e-9)
        # market_cap stays put (quote already USD).
        assert result.market_cap == 650e9

    def test_adr_dropped_ev_when_currencies_mismatched(self):
        """A pre-computed EV mixed quote-USD market_cap with TWD debt/cash —
        it was already meaningless. Normalization MUST drop the cached value
        so calculate_multiples recomputes from consistent USD inputs."""
        company = _peer(
            ticker="TSM",
            reporting_currency="TWD",
            quote_currency="USD",
            enterprise_value=12345.0,  # bogus by construction
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=1 / 32.0, quote_fx_rate_to_usd=1.0
        )
        assert result.enterprise_value is None


class TestLocalListing:
    """Local-listing shape (e.g. 2330.TW): both currencies match — all
    monetary fields including market_cap need conversion."""

    def test_local_listing_all_fields_scaled(self):
        rate = 1 / 32.0
        company = _peer(
            ticker="2330.TW",
            reporting_currency="TWD",
            quote_currency="TWD",
            revenue=2_500_000e6,
            ebitda=1_000_000e6,
            net_income=800_000e6,
            market_cap=20_800_000e6,  # ≈ 650B USD at 32 TWD/USD
            total_debt=320_000e6,
            total_cash=1_700_000e6,
            enterprise_value=19_420_000e6,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=rate, quote_fx_rate_to_usd=rate
        )
        assert result.reporting_currency == "USD"
        assert result.quote_currency == "USD"
        assert math.isclose(result.market_cap, 20_800_000e6 * rate, rel_tol=1e-9)
        # When currencies match, the pre-computed EV is internally consistent
        # and can be scaled wholesale (no drop-to-None).
        assert result.enterprise_value is not None
        assert math.isclose(result.enterprise_value, 19_420_000e6 * rate, rel_tol=1e-9)

    def test_local_listing_ev_preserved_through_scaling(self):
        """ev = market_cap + debt - cash should remain consistent after
        wholesale scaling."""
        rate = 1 / 32.0
        company = _peer(
            ticker="2330.TW",
            reporting_currency="TWD",
            quote_currency="TWD",
            market_cap=100.0,
            total_debt=20.0,
            total_cash=5.0,
            enterprise_value=115.0,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=rate, quote_fx_rate_to_usd=rate
        )
        assert math.isclose(result.enterprise_value, 115.0 * rate, rel_tol=1e-9)
        assert math.isclose(
            result.market_cap + result.total_debt - result.total_cash,
            result.enterprise_value,
            rel_tol=1e-9,
        )


class TestRateValidation:
    def test_zero_reporting_rate_raises(self):
        company = _peer(ticker="X", reporting_currency="TWD", quote_currency="USD")
        with pytest.raises(ValueError, match="reporting_fx_rate_to_usd"):
            normalize_company_to_usd(
                company, reporting_fx_rate_to_usd=0.0, quote_fx_rate_to_usd=1.0
            )

    def test_negative_quote_rate_raises(self):
        company = _peer(ticker="Y", reporting_currency="USD", quote_currency="EUR")
        with pytest.raises(ValueError, match="quote_fx_rate_to_usd"):
            normalize_company_to_usd(
                company, reporting_fx_rate_to_usd=1.0, quote_fx_rate_to_usd=-0.5
            )

    def test_nan_rate_raises(self):
        company = _peer(ticker="Z", reporting_currency="JPY", quote_currency="USD")
        with pytest.raises(ValueError, match="reporting_fx_rate_to_usd"):
            normalize_company_to_usd(
                company, reporting_fx_rate_to_usd=float("nan"), quote_fx_rate_to_usd=1.0
            )

    def test_unused_rate_not_validated(self):
        """When a currency is already USD, the corresponding rate is unused
        and absurd values must not trip validation (we allow callers to pass
        a placeholder rather than branch on currency in the call site)."""
        company = _peer(ticker="USD_ONLY")  # both USD
        # Both rates absurd — the no-op fast path skips validation entirely.
        normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=-9.9, quote_fx_rate_to_usd=float("nan")
        )
