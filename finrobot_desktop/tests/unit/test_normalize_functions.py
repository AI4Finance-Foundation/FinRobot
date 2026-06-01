"""normalize_price / normalize_financials fixtures (ADR-0004 step 3).

Five scenarios: yfinance OHLC price, FMP close-only price (degraded),
over-wide price window (17 months → trimmed), ADR currency override,
TTM lag exposure.
"""

from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CCY_INFERRED,
    DEGRADED_CLOSE_ONLY,
    DEGRADED_PRICE_FALLBACK_CLOSE,
    DEGRADED_TTM_LAG,
)
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price

FETCH = datetime(2026, 5, 28, 3, 21, tzinfo=timezone.utc)


def _price_result(history, provider="fmp", **data) -> DataResult:
    base = {"price_history": history}
    base.update(data)
    return DataResult(
        data=base, provider=provider, ticker="TSLA", data_type="price", timestamp=FETCH
    )


def _fin_result(provider="fmp", **data) -> DataResult:
    return DataResult(
        data=data, provider=provider, ticker="TSLA", data_type="financials", timestamp=FETCH
    )


def test_price_ohlc_complete_keeps_intraday():
    hist = [
        {"date": "2025-06-01", "close": 300.0, "high": 305.0, "low": 295.0},
        {"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0},
    ]
    p = normalize_price(_price_result(hist, provider="yfinance", current_price=440.36))
    assert p.is_ohlc_complete is True
    assert p.provenance.degraded == []
    assert p.fifty_two_week_high() == 450.0
    assert p.fifty_two_week_low() == 295.0
    assert p.current_price == 440.36
    # as_of is the latest bar date, NOT the fetch wall-clock — drives the pill
    assert p.provenance.as_of.date().isoformat() == "2026-05-27"
    assert p.provenance.fetched_at == FETCH


def test_price_close_only_is_degraded():
    hist = [
        {"date": "2025-06-01", "close": 300.0},
        {"date": "2026-05-27", "close": 440.0},
    ]
    p = normalize_price(_price_result(hist))
    assert p.is_ohlc_complete is False
    assert DEGRADED_CLOSE_ONLY in p.provenance.degraded
    assert p.fifty_two_week_low() == 300.0  # close fallback


def test_price_current_price_present_no_fallback_marker():
    """When the provider gives a real current_price, no fallback marker."""
    hist = [
        {"date": "2025-06-01", "close": 300.0, "high": 305.0, "low": 295.0},
        {"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0},
    ]
    p = normalize_price(_price_result(hist, provider="yfinance", current_price=441.0))
    assert p.current_price == 441.0
    assert DEGRADED_PRICE_FALLBACK_CLOSE not in p.provenance.degraded


def test_price_missing_current_price_falls_back_to_close_with_marker():
    """Provider gave no current_price → we use the latest bar's close, but flag
    it so the UI freshness pill won't claim a stale close is a live quote."""
    hist = [
        {"date": "2025-06-01", "close": 300.0, "high": 305.0, "low": 295.0},
        {"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0},
    ]
    p = normalize_price(_price_result(hist, provider="yfinance"))  # no current_price
    assert p.current_price == 440.0  # latest close
    assert DEGRADED_PRICE_FALLBACK_CLOSE in p.provenance.degraded


def test_price_over_wide_window_is_trimmed():
    # 17-month span (FMP timeseries=365 trading-day bug). The early low must
    # not survive into the 52-week low.
    hist = [
        {"date": "2024-12-10", "close": 221.86, "high": 230.0, "low": 218.0},
        {"date": "2025-06-01", "close": 300.0, "high": 305.0, "low": 284.7},
        {"date": "2026-05-27", "close": 440.36, "high": 450.0, "low": 430.0},
    ]
    p = normalize_price(_price_result(hist))
    dates = [b.date.isoformat() for b in p.bars]
    assert "2024-12-10" not in dates  # trimmed out
    assert p.fifty_two_week_low() == 284.7
    assert p.fifty_two_week_high() == 450.0


def test_financials_adr_currency_override_flags_degraded():
    # FMP says USD but country=Taiwan + ADR ticker → reporting currency TWD.
    fin = normalize_financials(
        _fin_result(
            revenue=1e9,
            market_cap=5e11,
            financial_currency="USD",
            country="Taiwan",
            date="2026-03-31",
        )
    )
    assert fin.reporting_currency == "TWD"
    assert fin.quote_currency == "USD"
    assert DEGRADED_CCY_INFERRED in fin.provenance.degraded


def test_financials_exposes_ttm_lag_and_period_end():
    # TTM ending 2025-09-30, fetched 2026-05-28 → ~2 quarters stale.
    fin = normalize_financials(
        _fin_result(
            revenue=97.879e9,
            market_cap=1.65e12,
            net_income=3.876e9,
            pe_ratio=426.7,
            date="2025-09-30",
            period_basis="ttm",
        )
    )
    assert fin.period_end.isoformat() == "2025-09-30"
    assert fin.pe_ttm_lag_quarters >= 2
    assert DEGRADED_TTM_LAG in fin.provenance.degraded
    assert fin.as_of.date().isoformat() == "2025-09-30"


def test_financials_carries_ebitda_components():
    # operating_income + income_tax_expense must survive normalization so the
    # extractor can recompute both EBITDA calibers (TSLA TTM values).
    fin = normalize_financials(
        _fin_result(
            revenue=97.879e9,
            market_cap=1.65e12,
            net_income=3.876e9,
            operating_income=4.897e9,
            income_tax_expense=1.511e9,
            interest_expense=0.339e9,
            depreciation_amortization=6.291e9,
            date="2026-03-31",
        )
    )
    assert fin.operating_income == 4.897e9
    assert fin.income_tax_expense == 1.511e9
    assert fin.interest_expense == 0.339e9
    assert fin.depreciation_amortization == 6.291e9
