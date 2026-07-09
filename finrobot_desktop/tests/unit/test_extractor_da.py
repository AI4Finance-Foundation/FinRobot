"""Unit tests for D&A and related optional fields in extractor.py.

ADR-0006 Step 4: fixtures wrap raw DataResult dicts with normalize_financials /
normalize_price before passing to extractor functions.
"""

from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.compute.coordinators.extractor import extract_financial_data


def _make_fin(**overrides):
    data = {
        "revenue": 394e9,
        "ebitda": 137e9,
        "net_income": 97e9,
        "gross_margin": 0.43,
        "operating_margin": 0.30,
        "market_cap": 2.6e12,
        "shares_outstanding": 15e9,
        "total_debt": 111e9,
        "total_cash": 30e9,
    }
    data.update(overrides)
    raw = DataResult(
        data=data,
        provider="fmp",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_financials(raw)


def _make_price():
    raw = DataResult(
        data={"current_price": 175.0, "price_history": [{"close": 175.0}]},
        provider="fmp",
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_price(raw)


def test_extract_da_from_fmp():
    """When provider supplies D&A, it appears in FinancialData."""
    result = extract_financial_data(_make_fin(depreciation_amortization=11.5e9), _make_price())
    assert result.income.depreciation_amortization == 11.5e9


def test_extract_da_none_from_yfinance():
    """When provider doesn't supply D&A, field is None."""
    result = extract_financial_data(_make_fin(), _make_price())
    assert result.income.depreciation_amortization is None


def test_extract_capex_from_canonical():
    """When the canonical snapshot supplies capital_expenditure (TTM sum-of-4-
    quarters cash-flow-statement capex on the FMP path, or the
    operatingCashflow−freeCashflow derivation on yfinance), it appears in
    FinancialData.income — the field extract_financial_data was missing, which
    left dcf_current_actuals with no TTM capex source (falling back to latest-FY
    unconditionally) even though NormalizedFinancials has carried this field
    since the v2 canonical contract."""
    result = extract_financial_data(_make_fin(capital_expenditure=9.5e9), _make_price())
    assert result.income.capital_expenditure == 9.5e9


def test_extract_capex_none_when_cashflow_statement_unavailable():
    """When the provider's cash-flow statement never resolved a capex figure for
    this ticker, the field stays None (not fabricated as 0)."""
    result = extract_financial_data(_make_fin(), _make_price())
    assert result.income.capital_expenditure is None


def test_extract_rd_sga_interest():
    result = extract_financial_data(
        _make_fin(rd_expense=30e9, sga_expense=28e9, interest_expense=4e9),
        _make_price(),
    )
    assert result.income.rd_expense == 30e9
    assert result.income.sga_expense == 28e9
    assert result.income.interest_expense == 4e9


def test_data_source_reflects_provider():
    """data_source should be the provider name, not hardcoded 'yfinance'."""
    result = extract_financial_data(_make_fin(), _make_price())
    assert result.data_source == "fmp"
