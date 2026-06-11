"""equity_research financial-modeling step wires forward consensus into the DCF seed.

The DCF used to seed stage-1 growth from trailing CAGR only, ignoring the
analyst consensus the same pipeline already fetched (AAPL: 3.3% trailing while
consensus expected +14.9%). This wiring passes the forward path through to
seed_dcf_inputs; absent consensus, it falls back to trailing unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.config import get_settings
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    HistoricalMetrics,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)
from finrobot.engine.pipelines.equity_research import _execute_financial_modeling

NOW = datetime.now(tz=timezone.utc)


class _FakeDataLayer:
    async def fetch(self, *a, **k):  # pragma: no cover - not reached (historical preloaded)
        raise AssertionError("data_layer should not be hit when context is preloaded")

    async def fetch_canonical(self, *a, **k):  # pragma: no cover
        raise AssertionError("data_layer should not be hit when context is preloaded")


def _deps() -> FinRobotDeps:
    return FinRobotDeps(data_layer=_FakeDataLayer(), settings=get_settings(model_name="test"))


def _financials() -> FinancialData:
    return FinancialData(
        ticker="AAPL",
        company_name="Apple Inc.",
        timestamp=NOW,
        income=IncomeStatement(
            revenue=391_000_000_000,
            ebitda=131_900_000_000,
            net_income=93_700_000_000,
            gross_margin=0.46,
            operating_margin=0.30,
            depreciation_amortization=11_400_000_000,
            interest_expense=3_750_000_000,
        ),
        balance=BalanceSheet(total_debt=106_000_000_000, total_cash=65_000_000_000),
        market=MarketData(
            market_cap=3_500_000_000_000,
            shares_outstanding=15_115_000_000,
            current_price=232.0,
            pe_ratio=37.4,
            industry="Consumer Electronics",
            sector="Technology",
            beta=1.25,
        ),
        valuation=ValuationMetrics(),
    )


def _historical_trailing_3pct() -> HistoricalMetrics:
    """Trailing CAGR ≈ 3.3% — the backward-looking number the old seed used."""
    return HistoricalMetrics(
        years=[2021, 2022, 2023, 2024],
        revenue=[365_817_000_000, 394_328_000_000, 383_285_000_000, 391_035_000_000],
        revenue_growth_yoy=[None, 0.078, -0.028, 0.020],
        cogs=[212e9, 223e9, 214e9, 210e9],
        gross_profit=[152e9, 170e9, 169e9, 180e9],
        gross_margin=[0.42, 0.43, 0.44, 0.46],
        sga=[22e9, 25e9, 25e9, 26e9],
        sga_ratio=[0.06, 0.063, 0.065, 0.066],
        ebitda=[123e9, 130e9, 125e9, 131e9],
        ebitda_margin=[0.336, 0.33, 0.327, 0.337],
        operating_income=[108e9, 119e9, 114e9, 123e9],
        operating_margin=[0.297, 0.302, 0.298, 0.315],
        net_income=[94e9, 99e9, 96e9, 93e9],
        eps=[6.1, 6.15, 6.13, 6.08],
        pe_ratio=[28.0, 27.0, 29.0, 30.0],
        cagr_revenue=0.0328,
        ticker="AAPL",
    )


def _forward_rows() -> dict[str, list[dict[str, object]]]:
    """Consensus revenue ~+12%/yr — anchored to today so the past/forward split
    is stable whenever the test runs (one past actual + three future estimates)."""
    y = NOW.year
    revs = {y - 1: 400e9, y: 450e9, y + 1: 504e9, y + 2: 564e9}  # ~12.5% YoY
    return {"rows": [{"date": f"{yr}-09-27", "revenueAvg": rev} for yr, rev in revs.items()]}


async def test_forward_consensus_seeds_dcf_when_present() -> None:
    ctx = {
        "data_collection": _financials(),
        "historical_metrics": _historical_trailing_3pct(),
        "forward_estimates_raw": _forward_rows(),
    }
    out = await _execute_financial_modeling(None, _deps(), "", ctx, "AAPL")  # type: ignore[arg-type]
    g0 = out.structured.inputs.revenue_growth_rates[0]
    assert g0 > 0.10  # consensus ~12.5%, not the 3.3% trailing CAGR


async def test_falls_back_to_trailing_without_forward() -> None:
    ctx = {
        "data_collection": _financials(),
        "historical_metrics": _historical_trailing_3pct(),
    }
    out = await _execute_financial_modeling(None, _deps(), "", ctx, "AAPL")  # type: ignore[arg-type]
    g0 = out.structured.inputs.revenue_growth_rates[0]
    assert g0 < 0.05  # trailing CAGR ≈ 3.3%, no consensus override
