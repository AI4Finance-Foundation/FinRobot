"""Cross-currency (ADR) valuation correctness — BUG-073 + BUG-006.

Foreign issuers (TSM/ASML/SAP) carry reporting-currency IS/BS line items
(TWD/EUR) alongside a USD market quote. Mixing them silently inflates absolute
valuation (DCF/DDM implied price in TWD-per-share printed as USD) and the
comps-forward target (USD peer P/E × TWD forward EPS).

Expected magnitudes here come from EXTERNAL facts (live FMP, 2026-06), not from
our own output:
- TSM profile/quote currency = USD; price ≈ $441; mktCap ≈ $2.29T (USD).
- TSM income reportedCurrency = TWD; FY revenue ≈ 4.5T TWD (≈ $142B at 0.0313).
- TWD/USD ≈ 0.0313 (≈ 32 TWD/USD).
So an un-normalized TSM DCF implied price comes out ~30-40x too high (a TWD value
printed as USD) with a cross-currency debt_ratio; the fix must land it in USD
order-of-magnitude (tens-to-low-hundreds) with a sane single-digit-% debt_ratio.

The FX rate is FIXED in these tests (no network) — the rate fetch is mocked /
passed directly so the assertions are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.operators.fx_normalize import normalize_financialdata_to_usd
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    HistoricalMetrics,
    IncomeStatement,
    MarketData,
    PeerComps,
    CompanyFinancials,
)

# Fixed TWD→USD spot used throughout (≈ 32 TWD/USD). No network.
TWD_USD = 0.0313


def _empty_history(ticker: str) -> HistoricalMetrics:
    """No multi-year history → seed falls through to Damodaran industry medians.

    Ratios (margins, capex/rev) are currency-invariant, so the FX correctness of
    the absolute path is isolated cleanly with an empty history.
    """
    return HistoricalMetrics(
        years=[],
        revenue=[],
        revenue_growth_yoy=[],
        cogs=[],
        gross_profit=[],
        gross_margin=[],
        sga=[],
        sga_ratio=[],
        ebitda=[],
        ebitda_margin=[],
        operating_income=[],
        operating_margin=[],
        net_income=[],
        eps=[],
        pe_ratio=[],
        cagr_revenue=None,
        ticker=ticker,
    )


def _tsm_financialdata() -> FinancialData:
    """TSM-shape snapshot: TWD reporting financials, USD quote.

    total_debt is sized ≈ USD market_cap (in TWD nominal) so the un-normalized
    debt_ratio = debt(TWD) / (debt(TWD) + mktcap(USD)) ≈ 0.5 — the cross-currency
    garbage the fix removes (it should drop to ≈ 0.03 once debt is in USD).
    """
    return FinancialData(
        ticker="TSM",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=4_536_412e6,  # TWD FY revenue ≈ $142B
            ebitda=2_700_000e6,  # TWD
            net_income=1_500_000e6,  # TWD
            operating_income=1_900_000e6,  # TWD
            income_tax_expense=200_000e6,  # TWD
            interest_expense=6_000e6,  # TWD
            depreciation_amortization=600_000e6,  # TWD
        ),
        balance=BalanceSheet(
            total_debt=2_290_000e6,  # TWD (≈ $71.7B); sized to make pre-fix D/(D+E) ≈ 0.5
            total_cash=1_000_000e6,  # TWD (≈ $31.3B)
        ),
        market=MarketData(
            market_cap=2_290_000e6,  # USD ($2.29T) — already quote currency
            shares_outstanding=5_186e6,
            current_price=441.4,  # USD
            beta=1.05,
            industry="Semiconductor",
        ),
        reporting_currency="TWD",
        quote_currency="USD",
    )


class TestDcfSeedForeignIssuer:
    """BUG-073: DCF absolute valuation must FX-normalize before seeding."""

    def test_unnormalized_is_inflated_and_debt_ratio_garbage(self):
        """Baseline: the bug. Un-normalized TSM seeds a cross-currency debt_ratio
        (~0.5) and a TWD-per-share implied price printed as USD (thousands)."""
        fd = _tsm_financialdata()
        inputs = seed_dcf_inputs(fd, _empty_history("TSM"))
        result = calculate_dcf(inputs)
        # debt(TWD) mixed with mktcap(USD) → ~0.5 (garbage).
        assert 0.45 < inputs.debt_ratio < 0.55
        # revenue_base still TWD → implied price is TWD/share shown as USD: thousands.
        assert result.implied_price > 1000

    def test_normalized_lands_in_usd_order_of_magnitude(self):
        """After FX normalization the implied price is USD order-of-magnitude
        (tens to low hundreds, NOT ~32x inflated) and debt_ratio is sane (~0.03,
        a single-digit-% leverage, not ~0.5)."""
        fd_usd = normalize_financialdata_to_usd(_tsm_financialdata(), TWD_USD, 1.0)
        inputs = seed_dcf_inputs(fd_usd, _empty_history("TSM"))
        result = calculate_dcf(inputs)

        # revenue_base now ≈ $142B (was 4.5T TWD).
        assert 130e9 < inputs.revenue_base < 155e9
        # debt ≈ $71.7B vs mktcap $2.29T → D/(D+E) ≈ 0.030, not 0.5.
        assert 0.02 < inputs.debt_ratio < 0.05
        # Implied price now in USD order-of-magnitude, far below the inflated baseline.
        assert 10 < result.implied_price < 600

    def test_fix_collapses_implied_price_by_roughly_the_fx_factor(self):
        """The normalized implied price is dramatically (>20x) below the
        un-normalized one — the TWD-as-USD inflation is removed. Not exactly
        1/0.0313 because debt_ratio also corrects (changing WACC), which is the
        whole point: the pre-fix WACC weight was itself garbage."""
        hist = _empty_history("TSM")
        before = calculate_dcf(seed_dcf_inputs(_tsm_financialdata(), hist))
        after = calculate_dcf(
            seed_dcf_inputs(
                normalize_financialdata_to_usd(_tsm_financialdata(), TWD_USD, 1.0), hist
            )
        )
        assert before.implied_price / after.implied_price > 20

    def test_us_issuer_seed_is_unaffected_regression(self):
        """USD/USD issuer: normalization is an exact no-op, so the seeded
        DCFInputs are identical with or without the normalize step."""
        fd = FinancialData(
            ticker="AAPL",
            timestamp=datetime.now(tz=timezone.utc),
            income=IncomeStatement(
                revenue=383_285e6,
                ebitda=130_000e6,
                net_income=96_995e6,
                operating_income=114_301e6,
                income_tax_expense=16_741e6,
                interest_expense=3_933e6,
                depreciation_amortization=11_519e6,
            ),
            balance=BalanceSheet(total_debt=111_088e6, total_cash=29_965e6),
            market=MarketData(
                market_cap=2_900_000e6,
                shares_outstanding=15_300e6,
                current_price=189.0,
                beta=1.25,
                industry="Computers/Peripherals",
            ),
            reporting_currency="USD",
            quote_currency="USD",
        )
        hist = _empty_history("AAPL")
        raw = seed_dcf_inputs(fd, hist)
        normed = seed_dcf_inputs(normalize_financialdata_to_usd(fd, TWD_USD, TWD_USD), hist)
        assert raw.revenue_base == normed.revenue_base
        assert raw.debt_ratio == normed.debt_ratio
        assert raw.net_debt == normed.net_debt
        assert calculate_dcf(raw).implied_price == calculate_dcf(normed).implied_price


class TestCompsForwardFxConversion:
    """BUG-006: USD peer P/E × reporting-currency forward EPS must be converted.

    The aggregator (_comps_pe_method, used_forward branch) computes
    ``mid = median_pe * forward_eps``. median_pe is USD-normalized; forward_eps
    from FMP analyst-estimates is in the issuer's reporting currency (TWD for
    TSM, epsAvg ≈ 98.89). The forward EPS MUST be converted to USD
    BEFORE the multiply, or the target is wrong-dimension (~32x high).
    """

    def _peer_comps_usd(self, *, median_pe: float) -> PeerComps:
        target = CompanyFinancials(
            ticker="TSM", revenue=142e9, market_cap=2_290e9, reporting_currency="USD"
        )
        peer = CompanyFinancials(
            ticker="NVDA", revenue=130e9, market_cap=3_000e9, reporting_currency="USD"
        )
        return PeerComps(target=target, peers=[peer], median_pe=median_pe)

    def test_twd_forward_eps_converted_before_multiply(self):
        """Replicates the route-layer conversion (routes/valuation._forward_to_usd):
        forward_eps in TWD (98.89) × USD peer P/E (22) must use the USD EPS."""
        from finrobot.engine.compute.operators.valuation_aggregator import _comps_pe_method

        median_pe = 22.0
        forward_eps_twd = 98.89  # FMP epsAvg FY2026 — TWD per share
        forward_eps_usd = forward_eps_twd * TWD_USD  # ≈ $3.10

        comps = self._peer_comps_usd(median_pe=median_pe)

        # WRONG (the bug): TWD EPS straight into a USD multiple → ~$2,176 target.
        wrong = _comps_pe_method(comps, forward_eps_twd, shares_outstanding=5_186e6)
        assert wrong is not None
        assert wrong.mid > 1000  # absurd, ~32x a real ADR price

        # RIGHT (the fix): convert EPS to USD first → USD target near peer P/E × USD EPS.
        right = _comps_pe_method(comps, forward_eps_usd, shares_outstanding=5_186e6)
        assert right is not None
        expected = median_pe * forward_eps_usd  # ≈ $68
        assert abs(right.mid - expected) < 1e-6
        # The conversion collapses the target by ~1/TWD_USD ≈ 32x.
        assert wrong.mid / right.mid > 25

    def test_us_issuer_forward_eps_unchanged_regression(self):
        """A USD issuer's forward EPS is not scaled — the route-layer guard skips
        conversion when reporting_currency == USD, so the aggregator result for a
        given forward_eps is the plain USD P/E × USD EPS."""
        from finrobot.engine.compute.operators.valuation_aggregator import _comps_pe_method

        median_pe = 30.0
        forward_eps_usd = 6.50  # already USD
        comps = self._peer_comps_usd(median_pe=median_pe)
        m = _comps_pe_method(comps, forward_eps_usd, shares_outstanding=15_300e6)
        assert m is not None
        assert abs(m.mid - median_pe * forward_eps_usd) < 1e-6
