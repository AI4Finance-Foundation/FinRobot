"""Tests for HistoricalMetrics cash-flow fields and the provider-agnostic
historical_extractor (门一 Step 2).

What these tests verify beyond "code runs":
- HistoricalMetrics accepts the cash-flow / DCF line-item fields with correct types.
- fetch_historical_metrics consumes DataLayer.fetch_historical (normalized
  per-year dicts) and builds a complete HistoricalMetrics with derived
  ratios/CAGR, sorted oldest-first, with the None→0.0 fill dcf_seed expects.
- The build is source-agnostic: identical normalized input → identical output
  whether it came from FMP or the yfinance fallback.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import HistoricalMetrics


# ---------------------------------------------------------------------------
# Part 1: HistoricalMetrics model — cash flow fields
# ---------------------------------------------------------------------------


class TestHistoricalMetricsCashFlowFields:
    """Verify HistoricalMetrics accepts the three new cash flow fields."""

    def _minimal_kwargs(self) -> dict:
        """Minimum valid HistoricalMetrics constructor kwargs (no cash flow)."""
        return {
            "years": [2020, 2021, 2022],
            "revenue": [1e9, 1.1e9, 1.2e9],
            "revenue_growth_yoy": [None, 0.1, 0.09],
            "cogs": [6e8, 6.6e8, 7.2e8],
            "gross_profit": [4e8, 4.4e8, 4.8e8],
            "gross_margin": [0.4, 0.4, 0.4],
            "sga": [1e8, 1.1e8, 1.2e8],
            "sga_ratio": [0.1, 0.1, 0.1],
            "ebitda": [2e8, 2.2e8, 2.4e8],
            "ebitda_margin": [0.2, 0.2, 0.2],
            "operating_income": [1.5e8, 1.65e8, 1.8e8],
            "operating_margin": [0.15, 0.15, 0.15],
            "net_income": [1e8, 1.1e8, 1.2e8],
            "eps": [2.0, 2.2, 2.4],
            "pe_ratio": [20.0, 18.0, 17.0],
            "cagr_revenue": 0.095,
            "ticker": "TEST",
        }

    def test_cash_flow_fields_default_to_empty_list(self):
        """New cash flow fields must default to [] so existing code is not broken."""
        hm = HistoricalMetrics(**self._minimal_kwargs())
        assert hm.operating_cash_flow == []
        assert hm.investing_cash_flow == []
        assert hm.financing_cash_flow == []

    def test_dcf_line_item_fields_default_to_empty_list(self):
        """D&A / CapEx / ΔNWC fields must default to [] so dcf_seed can detect
        absence and fall back to industry medians."""
        hm = HistoricalMetrics(**self._minimal_kwargs())
        assert hm.depreciation_amortization == []
        assert hm.capital_expenditure == []
        assert hm.change_in_working_capital == []

    def test_dcf_line_item_fields_accept_lists(self):
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            depreciation_amortization=[1.1e10, 1.2e10, 1.3e10],
            capital_expenditure=[1e10, 1.1e10, 1.2e10],
            change_in_working_capital=[-5e8, -6e8, -7e8],
        )
        assert hm.depreciation_amortization == [1.1e10, 1.2e10, 1.3e10]
        assert hm.capital_expenditure == [1e10, 1.1e10, 1.2e10]
        assert hm.change_in_working_capital == [-5e8, -6e8, -7e8]

    def test_operating_cash_flow_accepts_list_of_floats(self):
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=[1.5e8, 1.7e8, 2.0e8],
        )
        assert hm.operating_cash_flow == [1.5e8, 1.7e8, 2.0e8]

    def test_investing_cash_flow_accepts_negative_values(self):
        """Investing cash flow is typically negative (capex)."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            investing_cash_flow=[-5e7, -6e7, -7e7],
        )
        assert hm.investing_cash_flow == [-5e7, -6e7, -7e7]

    def test_financing_cash_flow_accepts_negative_values(self):
        """Financing cash flow is often negative (buybacks, dividends)."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            financing_cash_flow=[-1e8, -1.1e8, -1.3e8],
        )
        assert hm.financing_cash_flow == [-1e8, -1.1e8, -1.3e8]

    def test_all_three_cash_flow_fields_together(self):
        """All three fields coexist without conflict."""
        ocf = [2e8, 2.2e8, 2.5e8]
        icf = [-3e7, -4e7, -5e7]
        fcf = [-1.5e8, -1.8e8, -2e8]
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=ocf,
            investing_cash_flow=icf,
            financing_cash_flow=fcf,
        )
        assert hm.operating_cash_flow == ocf
        assert hm.investing_cash_flow == icf
        assert hm.financing_cash_flow == fcf

    def test_serialises_to_dict_with_cash_flow_fields(self):
        """model_dump() must include the three new fields."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=[1e8],
            investing_cash_flow=[-2e7],
            financing_cash_flow=[-8e7],
        )
        d = hm.model_dump()
        assert "operating_cash_flow" in d
        assert "investing_cash_flow" in d
        assert "financing_cash_flow" in d
        assert d["operating_cash_flow"] == [1e8]


# ---------------------------------------------------------------------------
# Part 2: extract_historical_metrics — provider-agnostic DataLayer consumer
# ---------------------------------------------------------------------------


def _dr(data: dict[str, Any]) -> DataResult:
    return DataResult(
        data=data,
        provider="test",
        ticker="AAPL",
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
        warnings=[],
    )


def _normalized_yearly() -> list[dict[str, Any]]:
    """Canonical per-year normalized dicts, newest-first — the exact shape both
    FMPProvider and YFinanceProvider emit for historical financials. CapEx is a
    positive magnitude (providers already sign-flipped the outflow)."""
    # (fy, rev, gp, ebitda, oi, ni, eps, sga, ocf, icf, fcf, da, capex_pos, nwc) in $B
    raw = [
        ("2022-12-31", 400, 170, 130, 119, 99, 6.15, 25, 122, -23, -110, 11.0, 11, 1.2),
        ("2021-12-31", 365, 152, 120, 108, 95, 5.61, 22, 104, -15, -101, 11.3, 10, -0.3),
        ("2020-12-31", 274, 104, 77, 66, 57, 3.28, 19, 80, -10, -86, 11.1, 7.3, 0.8),
        ("2019-12-31", 260, 98, 76, 64, 55, 2.97, 18, 69, -12, -90, 12.5, 10, -0.5),
    ]
    return [
        {
            "fiscal_year": fy,
            "revenue": rev * 1e9,
            "gross_profit": gp * 1e9,
            "operating_income": oi * 1e9,
            "ebitda": ebitda * 1e9,
            "net_income": ni * 1e9,
            "eps": eps,
            "sga_expense": sga * 1e9,
            "operating_cash_flow": ocf * 1e9,
            "investing_cash_flow": icf * 1e9,
            "financing_cash_flow": fcf * 1e9,
            "depreciation_amortization": da * 1e9,
            "capital_expenditure": capex * 1e9,
            "change_in_working_capital": nwc * 1e9,
        }
        for (fy, rev, gp, ebitda, oi, ni, eps, sga, ocf, icf, fcf, da, capex, nwc) in raw
    ]


class FakeDataLayer:
    """Minimal DataLayer stand-in for the extractor's two calls.

    ADR-0006 Step 5: _fetch_trailing_pe now calls fetch_canonical(FINANCIALS)
    instead of fetch(FINANCIALS). fetch_canonical returns NormalizedFinancials.
    """

    def __init__(
        self,
        yearly: list[dict[str, Any]],
        *,
        snapshot: dict[str, Any] | None = None,
        snapshot_raises: bool = False,
    ) -> None:
        self._yearly = yearly
        self._snapshot = snapshot if snapshot is not None else {"pe_ratio": 25.0}
        self._snapshot_raises = snapshot_raises

    async def fetch_historical(
        self, data_type: Any, ticker: str, years: int = 5, **kwargs: Any
    ) -> list[DataResult]:
        return [_dr(y) for y in self._yearly]

    async def fetch(self, data_type: Any, ticker: str, **kwargs: Any) -> DataResult:
        if self._snapshot_raises:
            raise ProviderError("snapshot unavailable")
        return _dr(self._snapshot)

    async def fetch_canonical(self, data_type: Any, ticker: str, **kwargs: Any):
        """Return NormalizedFinancials built from the snapshot dict."""
        from finrobot.engine.data.normalize.financials import normalize_financials

        if self._snapshot_raises:
            raise ProviderError("snapshot unavailable")
        return normalize_financials(_dr(self._snapshot))


def _run(coro):
    return asyncio.run(coro)


def _extract(layer: FakeDataLayer, ticker: str = "AAPL") -> HistoricalMetrics:
    # FakeDataLayer is a structural stand-in; the extractor only calls
    # fetch_historical + fetch, both implemented above.
    return _run(fetch_historical_metrics(layer, ticker))  # type: ignore[arg-type]


class TestExtractHistoricalMetrics:
    def test_returns_historical_metrics_instance(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert isinstance(result, HistoricalMetrics)

    def test_ticker_is_set(self):
        result = _extract(FakeDataLayer(_normalized_yearly()), "MSFT")
        assert result.ticker == "MSFT"

    def test_years_sorted_oldest_first(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.years == [2019, 2020, 2021, 2022]

    def test_revenue_oldest_first(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.revenue[0] == pytest.approx(260e9)
        assert result.revenue[-1] == pytest.approx(400e9)

    def test_cogs_is_revenue_minus_gross_profit(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        # oldest year: 260B - 98B = 162B
        assert result.cogs[0] == pytest.approx(162e9)

    def test_cogs_and_gross_profit_none_when_provider_omits_gross_profit(self):
        """Banks (fmp_provider sets gross_profit=None — no COGS line) must NOT get
        a fabricated cogs = revenue − 0 / gross_profit = 0, which would render the
        history as "COGS = full revenue, gross profit = $0". Both propagate None."""
        bank_year = {
            "fiscal_year": "2024-12-31",
            "revenue": 280e9,
            "gross_profit": None,
            "operating_income": 90e9,
            "net_income": 58e9,
            "eps": 20.0,
        }
        result = _extract(FakeDataLayer([bank_year]))
        assert result.cogs == [None]
        assert result.gross_profit == [None]
        assert result.gross_margin == [None]

    def test_operating_cash_flow_oldest_first(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.operating_cash_flow[0] == pytest.approx(69e9)
        assert result.operating_cash_flow[-1] == pytest.approx(122e9)

    def test_investing_cash_flow_negative(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert all(v < 0 for v in result.investing_cash_flow)

    def test_capex_positive_oldest_first(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert all(v >= 0 for v in result.capital_expenditure)
        assert result.capital_expenditure[0] == pytest.approx(10e9)
        assert result.capital_expenditure[-1] == pytest.approx(11e9)

    def test_depreciation_oldest_first(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.depreciation_amortization[0] == pytest.approx(12.5e9)
        assert result.depreciation_amortization[-1] == pytest.approx(11e9)

    def test_change_in_working_capital_mixed_signs(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert any(v < 0 for v in result.change_in_working_capital)
        assert any(v > 0 for v in result.change_in_working_capital)

    def test_eps_populated_positive(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert len(result.eps) == len(result.years)
        assert all(v > 0 for v in result.eps)
        assert result.eps[-1] == pytest.approx(6.15)

    def test_revenue_growth_yoy_first_is_none(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.revenue_growth_yoy[0] is None

    def test_revenue_growth_yoy_second_year(self):
        """2019→2020: (274-260)/260 = 0.05385."""
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.revenue_growth_yoy[1] == pytest.approx(0.05385, abs=0.001)

    def test_cagr_revenue(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        # (400/260)^(1/3) - 1 ≈ 0.1543
        assert result.cagr_revenue == pytest.approx(0.1543, abs=0.01)

    def test_margins_in_unit_range(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        for gm in result.gross_margin:
            assert 0.0 <= gm <= 1.0
        for em in result.ebitda_margin:
            assert 0.0 <= em <= 1.0

    def test_trailing_pe_only_on_last_year(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        assert result.pe_ratio[-1] == pytest.approx(25.0)
        assert all(v is None for v in result.pe_ratio[:-1])
        assert result.price_data_available is True

    def test_snapshot_failure_yields_no_pe_but_still_builds(self):
        layer = FakeDataLayer(_normalized_yearly(), snapshot_raises=True)
        result = _extract(layer)
        assert result.price_data_available is False
        assert all(v is None for v in result.pe_ratio)
        # The history itself still builds from fetch_historical.
        assert result.revenue[-1] == pytest.approx(400e9)

    def test_all_parallel_lists_same_length(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        n = len(result.years)
        for field in (
            result.revenue,
            result.cogs,
            result.gross_profit,
            result.ebitda,
            result.net_income,
            result.eps,
            result.operating_cash_flow,
            result.investing_cash_flow,
            result.financing_cash_flow,
            result.depreciation_amortization,
            result.capital_expenditure,
            result.change_in_working_capital,
        ):
            assert len(field) == n


class TestExtractHistoricalMetricsEdgeCases:
    def test_empty_history_returns_placeholder(self):
        """No usable rows → minimal empty HistoricalMetrics (dcf_seed degrades
        to industry medians), not a crash."""
        result = _extract(FakeDataLayer([]))
        assert result.years == []
        assert result.revenue == []
        assert result.cagr_revenue is None
        assert result.operating_cash_flow == []

    def test_revenue_nan_year_is_dropped(self):
        """A year whose revenue is missing/None is excluded so it can't poison
        CAGR — mirrors the old revenue-NaN column filter."""
        yearly = _normalized_yearly()
        yearly.append({"fiscal_year": "2018-12-31", "revenue": None, "net_income": 50e9})
        result = _extract(FakeDataLayer(yearly))
        assert 2018 not in result.years
        assert result.years == [2019, 2020, 2021, 2022]

    def test_missing_cashflow_fields_zero_filled(self):
        """yfinance fallback where a year lacks the cash-flow statement → CF
        list entries are 0.0 (dcf_seed treats all-zero as 'missing')."""
        yearly = [
            {
                "fiscal_year": "2022-12-31",
                "revenue": 400e9,
                "gross_profit": 170e9,
                "operating_income": 119e9,
                "ebitda": 130e9,
                "net_income": 99e9,
                "eps": 6.15,
                "sga_expense": 25e9,
                # no operating_cash_flow / capex / d&a / nwc keys at all
            },
            {
                "fiscal_year": "2021-12-31",
                "revenue": 365e9,
                "gross_profit": 152e9,
                "operating_income": 108e9,
                "ebitda": 120e9,
                "net_income": 95e9,
                "eps": 5.61,
                "sga_expense": 22e9,
            },
        ]
        result = _extract(FakeDataLayer(yearly))
        assert result.operating_cash_flow == [0.0, 0.0]
        assert result.capital_expenditure == [0.0, 0.0]
        assert result.depreciation_amortization == [0.0, 0.0]
        # Income-statement fields still populate.
        assert result.revenue == [pytest.approx(365e9), pytest.approx(400e9)]

    def test_windows_to_requested_years(self):
        """More rows than `years` (default 5) keeps the most recent window."""
        yearly = _normalized_yearly()  # 4 years
        # add two older years → 6 total; default window is 5
        yearly.extend(
            [
                {"fiscal_year": "2018-12-31", "revenue": 240e9, "net_income": 50e9},
                {"fiscal_year": "2017-12-31", "revenue": 230e9, "net_income": 48e9},
            ]
        )
        result = _extract(FakeDataLayer(yearly))
        assert len(result.years) == 5
        assert result.years == [2018, 2019, 2020, 2021, 2022]


# ---------------------------------------------------------------------------
# Part 4: FX normalization (P0: TSM's TWD history mixed with USD snapshot)
# ---------------------------------------------------------------------------


class _FXFakeDataLayer(FakeDataLayer):
    """FakeDataLayer + the reporting_to_quote_rate chokepoint."""

    def __init__(self, yearly: list[dict[str, Any]], *, rate: float | None) -> None:
        super().__init__(yearly)
        self._rate = rate
        self.rate_calls: list[tuple[str, str]] = []

    async def reporting_to_quote_rate(self, reporting_ccy: str, quote_ccy: str) -> float:
        self.rate_calls.append((reporting_ccy, quote_ccy))
        if self._rate is None:
            raise ProviderError("FX provider down")
        return self._rate


def _twd_yearly() -> list[dict[str, Any]]:
    return [
        {
            "fiscal_year": "2024-12-31",
            "revenue": 2_894_307_699_000.0,  # native TWD
            "net_income": 1_173_268_000_000.0,
            "eps": 45.25,
            "ebitda": 2_000_000_000_000.0,
            "financial_currency": "TWD",
            "quote_currency": "USD",
        }
    ]


class TestExtractHistoricalMetricsFx:
    def test_adr_absolute_figures_converted_to_quote_currency(self):
        """TSM-shaped history: absolute monetary fields must be converted to the
        quote currency so the multi-year charts/LLM narrative speak the same
        currency as the FX-normalized snapshot FinancialData."""
        rate = 0.0312
        layer = _FXFakeDataLayer(_twd_yearly(), rate=rate)
        result = _extract(layer, "TSM")

        assert result.currency == "USD"
        assert result.revenue[0] == pytest.approx(2_894_307_699_000.0 * rate)
        assert result.net_income[0] == pytest.approx(1_173_268_000_000.0 * rate)
        assert result.eps[0] == pytest.approx(45.25 * rate)
        assert result.ebitda[0] == pytest.approx(2_000_000_000_000.0 * rate)
        # Margins are currency-invariant.
        assert result.ebitda_margin[0] == pytest.approx(2_000_000_000_000.0 / 2_894_307_699_000.0)
        assert layer.rate_calls == [("TWD", "USD")]

    def test_fx_unavailable_keeps_native_figures_with_honest_tag(self):
        """FX due but unavailable: figures stay native (ratios still serve
        dcf_seed's currency-invariant medians) and the currency tag discloses
        TWD instead of silently passing native values off as USD."""
        layer = _FXFakeDataLayer(_twd_yearly(), rate=None)
        result = _extract(layer, "TSM")

        assert result.currency == "TWD"
        assert result.revenue[0] == pytest.approx(2_894_307_699_000.0)

    def test_us_issuer_untouched_and_tagged(self):
        yearly = _twd_yearly()
        yearly[0]["financial_currency"] = "USD"
        layer = _FXFakeDataLayer(yearly, rate=0.5)
        result = _extract(layer, "AAPL")

        assert result.currency == "USD"
        assert result.revenue[0] == pytest.approx(2_894_307_699_000.0)
        assert layer.rate_calls == []


class TestDataSourceProvenance:
    """data_source carries which provider served the yearly statements, so the
    /historical route can disclose an FMP→yfinance silent fallback (the same
    contract /financials and /price already honour)."""

    def test_single_provider_tag_propagates(self):
        result = _extract(FakeDataLayer(_normalized_yearly()))
        # FakeDataLayer's DataResults all carry provider="test".
        assert result.data_source == "test"

    def test_mixed_providers_disclosed_not_last_wins(self):
        from finrobot.engine.compute.coordinators.historical_extractor import (
            _aggregate_provider,
        )

        rows = [_dr(d) for d in _normalized_yearly()]
        rows[0] = rows[0].model_copy(update={"provider": "fmp"})
        rows[1] = rows[1].model_copy(update={"provider": "yfinance"})
        assert _aggregate_provider(rows) == "mixed:fmp+test+yfinance"
        assert _aggregate_provider([]) is None

    def test_empty_history_has_no_source(self):
        result = _extract(FakeDataLayer([]))
        assert result.data_source is None
