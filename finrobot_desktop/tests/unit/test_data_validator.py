"""Tests for cross-provider data validator (Track 3 Task 8).

The validator is a deterministic numeric comparator. Tests assert concrete
warning strings and thresholds rather than just "non-empty list".
"""

from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.validator import (
    cross_validate,
    has_comparable_financials,
    key_field_divergences,
)


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


def test_cross_validate_ignores_total_debt():
    """total_debt is NOT cross-validated: the two providers mix balance-sheet lease
    conventions (FMP bonds + finance leases vs yfinance + operating leases, e.g.
    MSFT $57B vs $125B) — a caliber gap, not a data error. A large divergence must
    produce NO warning.
    """
    p = _result("fmp", {"total_debt": 56_965_000_000})
    s = _result("yfinance", {"total_debt": 125_432_000_000})
    assert cross_validate(p, s) == []


def test_cross_validate_flags_total_cash_divergence():
    """total_cash IS cross-validated again (re-enabled 2026-06-08).

    FMP now serves cash + short-term investments (cashAndShortTermInvestments) —
    the same caliber as yfinance's ``total_cash`` — so a >10% gap is a genuine
    period/classification signal (one provider's balance sheet lagging a quarter),
    not a caliber artifact, and must surface a warning.
    """
    p = _result("fmp", {"total_cash": 13_237_000_000})
    s = _result("yfinance", {"total_cash": 53_172_000_000})
    warnings = cross_validate(p, s)
    assert len(warnings) == 1
    assert "total_cash" in warnings[0]


def test_cross_validate_total_cash_within_tolerance():
    """Same-caliber total_cash within 10% (MSFT FMP cash+ST vs yfinance) → no
    warning."""
    p = _result("fmp", {"total_cash": 78_270_000_000})
    s = _result("yfinance", {"total_cash": 78_230_000_000})
    assert cross_validate(p, s) == []


def test_cross_validate_ignores_margins():
    """gross_margin / operating_margin are NOT cross-validated (removed 2026-06-08).

    FMP derives margins from its TTM income statement while yfinance uses Yahoo's
    ``info`` ratio on a latest-period convention — a caliber gap, not a data error
    (MU op-margin 48.5% TTM vs 67.6%; JPM gross_margin 0% from yfinance's missing
    COGS line). The FMP value is SEC-confirmed and not arbitrated downstream, so a
    large divergence on either margin must produce NO warning.
    """
    p = _result("fmp", {"gross_margin": 0.40, "operating_margin": 0.485})
    s = _result("yfinance", {"gross_margin": 0.0, "operating_margin": 0.676})
    assert cross_validate(p, s) == []


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


# BUG-007: structured KEY-field divergence channel (revenue / net_income).


def test_key_field_divergences_revenue_over_tolerance():
    """Revenue diverges 33% > 15% → revenue reported as a structured KEY field."""
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("finnhub", {"revenue": 150_000_000})
    assert key_field_divergences(p, s) == ["revenue"]


def test_key_field_divergences_net_income_over_tolerance():
    p = _result("fmp", {"net_income": 10_000_000})
    s = _result("finnhub", {"net_income": 13_000_000})  # 30% > 15%
    assert key_field_divergences(p, s) == ["net_income"]


def test_key_field_divergences_within_tolerance_empty():
    """Revenue within 15% → no structured marker even though it's a key field."""
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("finnhub", {"revenue": 110_000_000})  # ~9%
    assert key_field_divergences(p, s) == []


def test_key_field_divergences_ignores_non_key_fields():
    """A non-key field (market_cap) over its tolerance is NOT reported here —
    that stays prose-only via cross_validate."""
    p = _result("fmp", {"market_cap": 100_000_000, "revenue": 100_000_000})
    s = _result("finnhub", {"market_cap": 150_000_000, "revenue": 101_000_000})
    assert key_field_divergences(p, s) == []


def test_key_field_divergences_empty_secondary():
    p = _result("fmp", {"revenue": 100_000_000})
    s = _result("finnhub", {})
    assert key_field_divergences(p, s) == []


def test_has_comparable_financials_empty_is_false():
    assert has_comparable_financials(_result("p", {})) is False


def test_has_comparable_financials_all_none_is_false():
    """The bug this guards: a non-empty all-None dict that cross_validate would
    silently skip into a phantom "agree"."""
    s = _result("p", {"revenue": None, "net_income": None, "market_cap": None})
    assert has_comparable_financials(s) is False


def test_has_comparable_financials_one_real_number_is_true():
    assert has_comparable_financials(_result("p", {"revenue": None, "market_cap": 5e11})) is True


def test_has_comparable_financials_only_uncompared_field_is_false():
    """ebitda is real but NOT in _RELATIVE_FIELDS, so it gives cross_validate
    nothing to compare — the secondary still contributes no validation signal."""
    assert has_comparable_financials(_result("p", {"ebitda": 1_000_000})) is False
