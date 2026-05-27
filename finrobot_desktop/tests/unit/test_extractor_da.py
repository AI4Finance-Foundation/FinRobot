from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.compute.extractor import extract_financial_data


def _make_financials_result(**overrides) -> DataResult:
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
    return DataResult(
        data=data,
        provider="fmp",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_price_result() -> DataResult:
    return DataResult(
        data={"current_price": 175.0, "price_history": [{"close": 175.0}]},
        provider="fmp",
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_extract_da_from_fmp():
    """When provider supplies D&A, it appears in FinancialData."""
    fin = _make_financials_result(depreciation_amortization=11.5e9)
    result = extract_financial_data(fin, _make_price_result())
    assert result.income.depreciation_amortization == 11.5e9


def test_extract_da_none_from_yfinance():
    """When provider doesn't supply D&A, field is None."""
    fin = _make_financials_result()  # no depreciation_amortization key
    result = extract_financial_data(fin, _make_price_result())
    assert result.income.depreciation_amortization is None


def test_extract_rd_sga_interest():
    fin = _make_financials_result(
        rd_expense=30e9,
        sga_expense=28e9,
        interest_expense=4e9,
    )
    result = extract_financial_data(fin, _make_price_result())
    assert result.income.rd_expense == 30e9
    assert result.income.sga_expense == 28e9
    assert result.income.interest_expense == 4e9


def test_data_source_reflects_provider():
    """data_source should be the provider name, not hardcoded 'yfinance'."""
    fin = _make_financials_result()
    result = extract_financial_data(fin, _make_price_result())
    assert result.data_source == "fmp"
