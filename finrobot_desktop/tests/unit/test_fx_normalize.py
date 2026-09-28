"""Tests for engine/compute/operators/fx_normalize.py — peer comps USD normalization."""

from __future__ import annotations

import math

import pytest

from datetime import datetime, timezone

from finrobot.engine.compute.operators.fx_normalize import (
    normalize_company_to_usd,
    normalize_financialdata_to_usd,
)
from finrobot.engine.models.financial import (
    BalanceSheet,
    CompanyFinancials,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


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
    income_tax_expense: float | None = None,
    preferred_stock: float | None = None,
    noncontrolling_interest: float | None = None,
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
        income_tax_expense=income_tax_expense,
        preferred_stock=preferred_stock,
        noncontrolling_interest=noncontrolling_interest,
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

    def test_tsm_adr_preferred_and_nci_scaled(self):
        """Preferred + NCI are reporting-currency balance items: a TWD ADR peer's
        NCI/preferred must scale to USD with debt/cash. Otherwise calculate_multiples
        — which recomputes the EV dropped for the reporting≠quote mismatch — adds a
        TWD preferred/NCI onto a USD EV, reintroducing a mixed-currency EV (class A)."""
        rate = 1 / 32.0
        company = _peer(
            ticker="TSM",
            reporting_currency="TWD",
            quote_currency="USD",
            preferred_stock=64_000e6,
            noncontrolling_interest=96_000e6,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=rate, quote_fx_rate_to_usd=1.0
        )
        assert result.preferred_stock is not None
        assert result.noncontrolling_interest is not None
        assert math.isclose(result.preferred_stock, 64_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.noncontrolling_interest, 96_000e6 * rate, rel_tol=1e-9)

    def test_income_tax_expense_scaled_with_reporting_currency(self):
        """income_tax_expense is a reporting-currency line item. It must scale
        with revenue/net_income so calculate_core_pe's effective tax rate
        ``tax / (net_income + tax)`` stays currency-invariant after
        normalization — otherwise a foreign issuer's NOPAT core P/E is wrong
        (BUG-018 FX boundary)."""
        rate = 1 / 32.0
        company = _peer(
            ticker="TSM",
            reporting_currency="TWD",
            quote_currency="USD",
            net_income=800_000e6,
            income_tax_expense=160_000e6,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=rate, quote_fx_rate_to_usd=1.0
        )
        assert result.income_tax_expense is not None
        assert math.isclose(result.income_tax_expense, 160_000e6 * rate, rel_tol=1e-9)
        # Effective tax ratio is dimensionless — it must be identical pre/post.
        assert company.income_tax_expense is not None
        pre = company.income_tax_expense / (company.net_income + company.income_tax_expense)
        post = result.income_tax_expense / (result.net_income + result.income_tax_expense)
        assert math.isclose(pre, post, rel_tol=1e-9)

    def test_none_income_tax_expense_stays_none(self):
        """A provider-omitted tax figure stays None through FX — never fabricated."""
        company = _peer(
            ticker="TSM",
            reporting_currency="TWD",
            quote_currency="USD",
            income_tax_expense=None,
        )
        result = normalize_company_to_usd(
            company, reporting_fx_rate_to_usd=1 / 32.0, quote_fx_rate_to_usd=1.0
        )
        assert result.income_tax_expense is None

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


def _fd(
    *,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
    revenue: float = 100e9,
    ebitda: float | None = 30e9,
    net_income: float | None = 20e9,
    operating_income: float | None = 25e9,
    income_tax_expense: float | None = 4e9,
    interest_expense: float | None = 1e9,
    da: float | None = 5e9,
    total_debt: float = 10e9,
    total_cash: float = 5e9,
    market_cap: float = 500e9,
    current_price: float = 100.0,
    enterprise_value: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker="X",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=revenue,
            ebitda=ebitda,
            net_income=net_income,
            operating_income=operating_income,
            income_tax_expense=income_tax_expense,
            interest_expense=interest_expense,
            depreciation_amortization=da,
        ),
        balance=BalanceSheet(total_debt=total_debt, total_cash=total_cash),
        market=MarketData(
            market_cap=market_cap,
            shares_outstanding=5e9,
            current_price=current_price,
            price_52w_high=current_price * 1.2,
            price_52w_low=current_price * 0.8,
            beta=1.1,
        ),
        valuation=ValuationMetrics(enterprise_value=enterprise_value),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
    )


class TestFinancialDataNoOp:
    def test_pure_usd_returned_unchanged(self):
        """US issuer (both currencies USD): same instance, no copy, no FX read."""
        fd = _fd()
        result = normalize_financialdata_to_usd(
            fd, reporting_fx_rate_to_usd=999.0, quote_fx_rate_to_usd=999.0
        )
        assert result is fd

    def test_us_issuer_numbers_unchanged_exact_noop(self):
        """Regression: USD/USD must be a byte-for-byte no-op (numbers unchanged)."""
        fd = _fd(
            revenue=383_285e6,
            net_income=96_995e6,
            total_debt=111_088e6,
            total_cash=29_965e6,
            market_cap=2_900_000e6,
            current_price=185.0,
        )
        result = normalize_financialdata_to_usd(fd, 0.0313, 0.0313)
        assert result.income.revenue == 383_285e6
        assert result.income.net_income == 96_995e6
        assert result.balance.total_debt == 111_088e6
        assert result.balance.total_cash == 29_965e6
        assert result.market.market_cap == 2_900_000e6
        assert result.market.current_price == 185.0
        assert result.reporting_currency == "USD"
        assert result.quote_currency == "USD"


class TestFinancialDataAdr:
    """TSM-shape: TWD reporting financials, USD quote (market_cap / price)."""

    def test_is_bs_scaled_quote_untouched(self):
        rate = 0.0313
        fd = _fd(
            reporting_currency="TWD",
            quote_currency="USD",
            revenue=4_536_412e6,  # TWD
            ebitda=2_700_000e6,
            net_income=1_500_000e6,
            operating_income=1_900_000e6,
            income_tax_expense=200_000e6,
            interest_expense=6_000e6,
            da=600_000e6,
            total_debt=2_290_000e6,  # TWD
            total_cash=2_000_000e6,
            market_cap=2_290_000e6,  # USD — already quote ccy
            current_price=441.4,  # USD
        )
        result = normalize_financialdata_to_usd(fd, rate, 1.0)
        assert result is not fd
        assert result.reporting_currency == "USD"
        assert result.quote_currency == "USD"
        # Reporting-currency items scaled by the reporting rate.
        assert math.isclose(result.income.revenue, 4_536_412e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.income.net_income, 1_500_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.income.operating_income, 1_900_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.income.income_tax_expense, 200_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.income.depreciation_amortization, 600_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.balance.total_debt, 2_290_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.balance.total_cash, 2_000_000e6 * rate, rel_tol=1e-9)
        # Quote-currency items untouched (quote rate = 1.0 since already USD).
        assert result.market.market_cap == 2_290_000e6
        assert result.market.current_price == 441.4

    def test_effective_tax_ratio_currency_invariant(self):
        """tax / (net_income + tax) must be identical pre/post normalization."""
        rate = 0.0313
        fd = _fd(
            reporting_currency="TWD",
            quote_currency="USD",
            net_income=1_500_000e6,
            income_tax_expense=200_000e6,
        )
        result = normalize_financialdata_to_usd(fd, rate, 1.0)
        pre = fd.income.income_tax_expense / (fd.income.net_income + fd.income.income_tax_expense)
        post = result.income.income_tax_expense / (
            result.income.net_income + result.income.income_tax_expense
        )
        assert math.isclose(pre, post, rel_tol=1e-9)

    def test_none_fields_stay_none(self):
        fd = _fd(
            reporting_currency="TWD",
            quote_currency="USD",
            ebitda=None,
            net_income=None,
            income_tax_expense=None,
            da=None,
        )
        result = normalize_financialdata_to_usd(fd, 0.0313, 1.0)
        assert result.income.ebitda is None
        assert result.income.net_income is None
        assert result.income.income_tax_expense is None
        assert result.income.depreciation_amortization is None

    def test_shares_outstanding_and_beta_unchanged(self):
        """shares_outstanding is a count and beta is dimensionless — never scaled."""
        fd = _fd(reporting_currency="TWD", quote_currency="USD")
        result = normalize_financialdata_to_usd(fd, 0.0313, 1.0)
        assert result.market.shares_outstanding == fd.market.shares_outstanding
        assert result.market.beta == fd.market.beta

    def test_mismatched_currency_drops_cached_ev(self):
        """A cached EV mixed USD market_cap with TWD net debt — drop it."""
        fd = _fd(reporting_currency="TWD", quote_currency="USD", enterprise_value=99_999e6)
        result = normalize_financialdata_to_usd(fd, 0.0313, 1.0)
        assert result.valuation.enterprise_value is None


class TestFinancialDataLocalListing:
    """2330.TW shape: both currencies TWD — market_cap and price also scale."""

    def test_all_fields_including_quote_scaled(self):
        rate = 0.0313
        fd = _fd(
            reporting_currency="TWD",
            quote_currency="TWD",
            revenue=4_536_412e6,
            market_cap=73_000_000e6,  # TWD
            current_price=14_100.0,  # TWD
            total_debt=2_290_000e6,
            enterprise_value=75_000_000e6,
        )
        result = normalize_financialdata_to_usd(fd, rate, rate)
        assert math.isclose(result.market.market_cap, 73_000_000e6 * rate, rel_tol=1e-9)
        assert math.isclose(result.market.current_price, 14_100.0 * rate, rel_tol=1e-9)
        # When both tags match the cached EV is internally consistent — scale it.
        assert result.valuation.enterprise_value is not None
        assert math.isclose(result.valuation.enterprise_value, 75_000_000e6 * rate, rel_tol=1e-9)


class TestFinancialDataRateValidation:
    def test_zero_reporting_rate_raises(self):
        fd = _fd(reporting_currency="TWD", quote_currency="USD")
        with pytest.raises(ValueError, match="reporting_fx_rate_to_usd"):
            normalize_financialdata_to_usd(fd, 0.0, 1.0)

    def test_unused_rate_not_validated(self):
        """USD/USD no-op must skip validation even with absurd rates."""
        fd = _fd()
        normalize_financialdata_to_usd(fd, -9.9, float("nan"))

    def test_positive_inf_reporting_rate_raises(self):
        """+Inf is positive and equal to itself — the old `<=0 or x!=x` guard
        let it through, fabricating Inf USD line items. Explicit rejection."""
        fd = _fd(reporting_currency="TWD", quote_currency="USD")
        with pytest.raises(ValueError, match="reporting_fx_rate_to_usd"):
            normalize_financialdata_to_usd(fd, float("inf"), 1.0)


class TestFinancialDataPeRatio:
    """P/E must be re-derived from same-currency USD inputs at the FX boundary.

    The provider may have stamped a mixed-currency mc/ni P/E (quote-ccy market_cap
    over reporting-ccy net_income) for an ADR — SAP/TSM/TM, live probe 2026-06-06.
    fx_normalize is the first point that holds both in one currency, so it must
    recompute the ratio rather than carry the dimensionally-mixed cached value.
    """

    def test_adr_pe_recomputed_from_usd(self):
        rate = 0.0313  # TWD→USD
        fd = _fd(
            reporting_currency="TWD",
            quote_currency="USD",
            net_income=1_500_000e6,  # TWD
            market_cap=2_290_000e6,  # USD (already quote ccy)
        )
        # Simulate the mixed-currency P/E a naive provider fallback would stamp.
        fd.market.pe_ratio = 2_290_000e6 / 1_500_000e6  # USD-over-TWD garbage
        result = normalize_financialdata_to_usd(fd, rate, 1.0)
        expected = 2_290_000e6 / (1_500_000e6 * rate)  # USD mc / USD ni
        assert result.market.pe_ratio is not None
        assert math.isclose(result.market.pe_ratio, expected, rel_tol=1e-9)

    def test_adr_negative_net_income_pe_none(self):
        """Loss-making ADR: P/E is not meaningful — None, never a garbage number."""
        fd = _fd(reporting_currency="TWD", quote_currency="USD", net_income=-100_000e6)
        fd.market.pe_ratio = 123.0  # stale upstream value
        result = normalize_financialdata_to_usd(fd, 0.0313, 1.0)
        assert result.market.pe_ratio is None

    def test_usd_issuer_pe_preserved_through_fast_path(self):
        """Same-currency issuer: fast path no-op keeps the already-correct P/E."""
        fd = _fd()  # USD/USD
        fd.market.pe_ratio = 25.0
        result = normalize_financialdata_to_usd(fd, 999.0, 999.0)
        assert result.market.pe_ratio == 25.0


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

    def test_positive_inf_quote_rate_raises(self):
        """+Inf passes a naive `<=0 or x!=x` guard; must be rejected explicitly."""
        company = _peer(ticker="W", reporting_currency="USD", quote_currency="EUR")
        with pytest.raises(ValueError, match="quote_fx_rate_to_usd"):
            normalize_company_to_usd(
                company, reporting_fx_rate_to_usd=1.0, quote_fx_rate_to_usd=float("inf")
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
