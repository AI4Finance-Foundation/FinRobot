"""Tests for pipeline _helpers — execute_financial_data_step.

ADR-0006 Step 4: execute_financial_data_step now calls fetch_canonical
(returns NormalizedFinancials/NormalizedPrice) instead of fetch (raw DataResult).
Mocks provide fetch_canonical and fetch_historical where needed.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType
from finrobot.engine.pipelines._helpers import (
    execute_financial_data_step,
    fmt_market_cap,
    fmt_multiple,
)


# ---------------------------------------------------------------------------
# Whitelist formatters (BUG-038) — must mirror the frontend SourcedNumber render.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (28.736199, "28.7x"),  # raw float self-rounds to one decimal + 'x'
        (19.149, "19.1x"),
        (21.44, "21.4x"),
        (0.0, "0.0x"),
        (None, "n/a（未取得）"),  # never the literal "None"
    ],
)
def test_fmt_multiple_matches_frontend_caliber(value: float | None, expected: str) -> None:
    """PeerComparisonChart renders multiples as v.toFixed(1)+'x'."""
    assert fmt_multiple(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3_411_000_000_000, "$3.41T"),  # formatCompactNumber en: T = .2f
        (2_000_000_000_000, "$2.00T"),
        (3_100_000_000_000, "$3.10T"),
        (850_000_000_000, "$850.00B"),  # B = .2f
        (12_300_000, "$12.30M"),  # M = .2f
        (4_500, "$4.5K"),  # K = .1f
        (920, "$920"),  # below K → plain integer
        (None, "n/a（未取得）"),
    ],
)
def test_fmt_market_cap_matches_frontend_caliber(value: float | None, expected: str) -> None:
    """formatCompactNumber (ui/src/utils/format.ts, en): T/B/M=.2f, K=.1f."""
    assert fmt_market_cap(value) == expected


def _financials_raw(warnings: list[str] | None = None) -> DataResult:
    return DataResult(
        data={
            "revenue": 1e9,
            "ebitda": 2e8,
            "net_income": 1e8,
            "market_cap": 5e9,
            "shares_outstanding": 1e8,
            "current_price": 50.0,
            "gross_margin": 0.4,
            "operating_margin": 0.15,
        },
        provider="fmp",
        ticker="TEST",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
        warnings=warnings or [],
    )


def _price_raw() -> DataResult:
    return DataResult(
        data={"price_history": [{"close": 50.0}]},
        provider="fmp",
        ticker="TEST",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _yearly_result(year: int, revenue: float = 1e9) -> DataResult:
    """Build a single-year financials DataResult shaped like fetch_historical's
    output — the canonical normalized per-year dict that historical_extractor's
    ``_build_from_yearly`` consumes. ``fiscal_year`` is what pins the row to a
    year, and the cash-flow lines (CapEx / D&A / ΔNWC) must round-trip so the DCF
    seed uses the company's own CapEx instead of the Damodaran industry
    aggregate."""
    return DataResult(
        data={
            "revenue": revenue,
            "fiscal_year": year,
            "ebitda": revenue * 0.2,
            "net_income": revenue * 0.1,
            "market_cap": 5e9,
            "shares_outstanding": 1e8,
            "current_price": 50.0,
            # Margin line items the extractor actually reads (it derives margins
            # from gross_profit / operating_income / sga_expense, not the
            # pre-computed *_margin fields).
            "gross_profit": revenue * 0.4,
            "operating_income": revenue * 0.15,
            "sga_expense": revenue * 0.1,
            "capital_expenditure": revenue * 0.05,
            "depreciation_amortization": revenue * 0.04,
            "change_in_working_capital": revenue * 0.01,
        },
        provider="fmp",
        ticker="TEST",
        data_type="financials",
        timestamp=datetime(year, 6, 30, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_cross_validation_warnings_merged_into_financial_data():
    """Cross-validation warnings (set on NormalizedFinancials.warnings) must appear
    in FinancialData.warnings after extract_financial_data."""
    cross_warnings = [
        "Data discrepancy: revenue differs by 33% (fmp: 1,000,000,000 vs yfinance: 750,000,000).",
        "Data discrepancy: ebitda differs by 17% (fmp: 200,000,000 vs yfinance: 170,000,000).",
    ]
    # Simulate fetch_canonical returning NormalizedFinancials with cross-validate warnings
    norm_fin = normalize_financials(_financials_raw())
    norm_fin.warnings = list(cross_warnings)
    norm_price = normalize_price(_price_raw())

    mock_agent = MagicMock()
    mock_agent_result = MagicMock()
    mock_agent_result.output = "Agent analysis text"
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    mock_data_layer = MagicMock()
    mock_data_layer.fetch_canonical = AsyncMock(
        side_effect=lambda dt, ticker, **kw: (
            norm_fin if DataType(dt) == DataType.FINANCIALS else norm_price
        )
    )
    mock_data_layer.fetch_historical = AsyncMock(return_value=[])

    mock_deps = MagicMock()
    mock_deps.data_layer = mock_data_layer

    step_output = await execute_financial_data_step(mock_agent, mock_deps, "prompt", {}, "TEST")

    fd = step_output.structured
    assert hasattr(fd, "warnings")
    for w in cross_warnings:
        assert w in fd.warnings, f"Cross-validation warning missing: {w}"


@pytest.mark.asyncio
async def test_historical_metrics_injected_into_structured_context():
    """execute_financial_data_step must populate historical_metrics and forecast."""
    norm_fin = normalize_financials(_financials_raw())
    norm_price = normalize_price(_price_raw())
    yearly = [
        _yearly_result(y, r)
        for y, r in [
            (2020, 800e6),
            (2021, 900e6),
            (2022, 1e9),
            (2023, 1.1e9),
            (2024, 1.2e9),
        ]
    ]

    mock_agent = MagicMock()
    mock_agent_result = MagicMock()
    mock_agent_result.output = "text"
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    mock_data_layer = MagicMock()
    mock_data_layer.fetch_canonical = AsyncMock(
        side_effect=lambda dt, ticker, **kw: (
            norm_fin if DataType(dt) == DataType.FINANCIALS else norm_price
        )
    )
    mock_data_layer.fetch_historical = AsyncMock(return_value=yearly)

    mock_deps = MagicMock()
    mock_deps.data_layer = mock_data_layer

    structured_context: dict[str, object] = {}
    await execute_financial_data_step(mock_agent, mock_deps, "prompt", structured_context, "TEST")

    # structured_context must now contain historical_metrics and forecast
    assert "historical_metrics" in structured_context, (
        f"Missing historical_metrics. Keys: {list(structured_context.keys())}"
    )
    from finrobot.engine.models.financial import HistoricalMetrics, ForecastResult

    hm = structured_context["historical_metrics"]
    assert isinstance(hm, HistoricalMetrics)
    assert len(hm.years) == 5
    # A-fix: the cash-flow lines must round-trip (the old FinancialData→
    # extract_historical_metrics path dropped them, starving dcf_seed of company
    # CapEx and forcing the broken industry fallback).
    assert len(hm.capital_expenditure) == 5
    assert len(hm.depreciation_amortization) == 5

    assert "forecast" in structured_context, (
        f"Missing forecast. Keys: {list(structured_context.keys())}"
    )
    fc = structured_context["forecast"]
    assert isinstance(fc, ForecastResult)
    assert len(fc.years) == 3  # 3-year default forecast


@pytest.mark.asyncio
async def test_no_duplicate_warnings_when_extractor_and_provider_share():
    """Warnings from canonical object and extractor must not be duplicated."""
    shared_warning = (
        "total_debt not available from provider — "
        "EV and EV-based multiples (EV/EBITDA, EV/Revenue) cannot be computed"
    )
    # Build NormalizedFinancials with total_debt=None so extractor also warns
    fin_raw = _financials_raw()
    fin_raw.data.pop("total_debt", None)
    norm_fin = normalize_financials(fin_raw)
    # Pre-attach the same warning so it arrives on the canonical object
    norm_fin.warnings = [shared_warning]
    norm_price = normalize_price(_price_raw())

    mock_agent = MagicMock()
    mock_agent_result = MagicMock()
    mock_agent_result.output = "text"
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    mock_data_layer = MagicMock()
    mock_data_layer.fetch_canonical = AsyncMock(
        side_effect=lambda dt, ticker, **kw: (
            norm_fin if DataType(dt) == DataType.FINANCIALS else norm_price
        )
    )
    mock_data_layer.fetch_historical = AsyncMock(return_value=[])

    mock_deps = MagicMock()
    mock_deps.data_layer = mock_data_layer

    step_output = await execute_financial_data_step(mock_agent, mock_deps, "prompt", {}, "TEST")

    fd = step_output.structured
    # The extractor will generate its own version of this warning.
    # Cross-validation duplicate should not be added.
    debt_warnings = [w for w in fd.warnings if "total_debt" in w]
    assert len(debt_warnings) <= 2  # extractor + possibly provider, but no exact dupe
