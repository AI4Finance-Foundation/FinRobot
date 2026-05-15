"""Tests for cross-provider data validator (Track 3 Task 8).

The validator is a deterministic numeric comparator. Tests assert concrete
warning strings and thresholds rather than just "non-empty list".
"""

from datetime import datetime, timezone

from finagent.engine.data.interface import DataResult
from finagent.engine.data.validator import cross_validate


def _result(provider: str, data: dict) -> DataResult:
    return DataResult(
        data=data,
        provider=provider,
        ticker="TEST",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_cross_validate_matching_data_no_warnings():
    """Two results with identical data → empty warnings."""
    payload = {
        "revenue": 100_000_000,
        "ebitda": 20_000_000,
        "net_income": 10_000_000,
        "gross_margin": 0.40,
        "operating_margin": 0.15,
    }
    warnings = cross_validate(_result("fmp", payload), _result("yfinance", payload))
    assert warnings == []


def test_cross_validate_revenue_discrepancy():
    """Revenue differs by 20% → warning mentioning revenue and threshold."""
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("yfinance", {"revenue": 125_000_000})  # 20% diff from 125
    warnings = cross_validate(p, s)
    assert len(warnings) == 1
    assert "revenue" in warnings[0]
    assert "fmp" in warnings[0]
    assert "yfinance" in warnings[0]
    assert "15%" in warnings[0]  # threshold mentioned


def test_cross_validate_margin_discrepancy():
    """Gross margin differs by 15pp → warning generated (> 10pp threshold)."""
    p = _result("fmp", {"gross_margin": 0.40})
    s = _result("yfinance", {"gross_margin": 0.55})
    warnings = cross_validate(p, s)
    assert len(warnings) == 1
    assert "gross_margin" in warnings[0]


def test_cross_validate_within_tolerance():
    """Revenue differs by 10% (< 15% threshold) → no warning."""
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("yfinance", {"revenue": 110_000_000})  # ~9% of 110
    warnings = cross_validate(p, s)
    assert warnings == []


def test_cross_validate_missing_field_no_warning():
    """Field present in only one result → no warning (not a discrepancy)."""
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("yfinance", {"ebitda": 20_000_000})  # no revenue
    warnings = cross_validate(p, s)
    assert warnings == []


def test_cross_validate_zero_values():
    """Both zero → no warning, no division by zero."""
    p = _result("fmp", {"revenue": 0})
    s = _result("yfinance", {"revenue": 0})
    warnings = cross_validate(p, s)
    assert warnings == []


def test_cross_validate_non_numeric_skipped():
    """Non-numeric values in a numeric field are skipped, not crashed."""
    p = _result("fmp", {"revenue": "N/A"})
    s = _result("yfinance", {"revenue": 100_000_000})
    warnings = cross_validate(p, s)
    assert warnings == []


def test_cross_validate_market_cap_tighter_threshold():
    """Market cap uses 5% threshold (tighter than revenue's 15%)."""
    p = _result("fmp", {"market_cap": 100_000_000})
    s = _result("yfinance", {"market_cap": 110_000_000})  # ~9% diff
    warnings = cross_validate(p, s)
    assert len(warnings) == 1
    assert "market_cap" in warnings[0]
    assert "5%" in warnings[0]


def test_cross_validate_empty_secondary_warns():
    """D5: empty secondary data must produce a warning, not silent pass."""
    primary = DataResult(
        provider="p1",
        data={"revenue": 100_000, "ebitda": 50_000},
        ticker="TEST",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    secondary = DataResult(
        provider="p2",
        data={},
        ticker="TEST",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    warnings = cross_validate(primary, secondary)
    assert len(warnings) == 1
    assert "empty data" in warnings[0].lower()
    assert "p2" in warnings[0]
