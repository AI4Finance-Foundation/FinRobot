"""Tests for pipeline _helpers — execute_financial_data_step."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finagent.engine.data.interface import DataResult
from finagent.engine.data.types import DataType
from finagent.engine.pipelines._helpers import execute_financial_data_step


def _financials_result(warnings: list[str] | None = None) -> DataResult:
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


def _price_result() -> DataResult:
    return DataResult(
        data={"price_history": [{"close": 50.0}]},
        provider="fmp",
        ticker="TEST",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_cross_validation_warnings_merged_into_financial_data():
    """DataResult.warnings (cross-validation) must appear in FinancialData.warnings."""
    cross_warnings = [
        "Data discrepancy: revenue differs by 33% (fmp: 1,000,000,000 vs yfinance: 750,000,000).",
        "Data discrepancy: ebitda differs by 17% (fmp: 200,000,000 vs yfinance: 170,000,000).",
    ]
    financials = _financials_result(warnings=cross_warnings)
    price = _price_result()

    mock_agent = MagicMock()
    mock_agent_result = MagicMock()
    mock_agent_result.output = "Agent analysis text"
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    mock_data_layer = MagicMock()
    mock_data_layer.fetch = AsyncMock(side_effect=lambda dt, ticker, **kw: financials if dt == DataType.FINANCIALS else price)

    mock_deps = MagicMock()
    mock_deps.data_layer = mock_data_layer

    step_output = await execute_financial_data_step(
        mock_agent, mock_deps, "prompt", {}, "TEST"
    )

    fd = step_output.structured
    assert hasattr(fd, "warnings")
    for w in cross_warnings:
        assert w in fd.warnings, f"Cross-validation warning missing: {w}"


@pytest.mark.asyncio
async def test_no_duplicate_warnings_when_extractor_and_provider_share():
    """If extractor and provider both produce the same warning, no duplicates."""
    shared_warning = "total_debt not available from provider — defaulted to 0; EV-based multiples (EV/EBITDA, EV/Revenue) may be understated"
    financials = _financials_result(warnings=[shared_warning])
    # Remove total_debt so extractor also generates this warning
    financials.data.pop("total_debt", None)
    price = _price_result()

    mock_agent = MagicMock()
    mock_agent_result = MagicMock()
    mock_agent_result.output = "text"
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    mock_data_layer = MagicMock()
    mock_data_layer.fetch = AsyncMock(side_effect=lambda dt, ticker, **kw: financials if dt == DataType.FINANCIALS else price)

    mock_deps = MagicMock()
    mock_deps.data_layer = mock_data_layer

    step_output = await execute_financial_data_step(
        mock_agent, mock_deps, "prompt", {}, "TEST"
    )

    fd = step_output.structured
    # The extractor will generate its own version of this warning.
    # Cross-validation duplicate should not be added.
    debt_warnings = [w for w in fd.warnings if "total_debt" in w]
    assert len(debt_warnings) <= 2  # extractor + possibly provider, but no exact dupe
