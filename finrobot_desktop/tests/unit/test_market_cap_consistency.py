"""Tests for the lineage-aware market-cap consistency check.

Anchored on REAL 2026-06-05 numbers (FMP /quote + yfinance .info) so the test
proves the validator reclassifies the genuine GOOG/META share-class mismatch as
a *structure* warning instead of a data error — and, critically, ABSTAINS (no
false-positive "consistent" signal) when the only available share count is
itself derived as market_cap/price (the FMP lineage trap).

External anchors (verified 2026-06-05):
- AAPL  mc=4,571,145,807,880  px=311.23  yf_shares=14,687,356,000  → ratio≈1.00 (single class)
- GOOG  mc=4,466,272,753,096  px=369.27  yf_shares= 5,481,459,689  → ratio≈2.21 (multi-class)
- META  mc=1,593,038,276,492  px=627.57  yf_shares= 2,196,045,588  → ratio≈1.16 (minor mismatch)
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.engine.data.validator import market_cap_consistency


def _fmp(ticker: str, mc: float, price: float) -> DataResult:
    """FMP financials result — shares is DERIVED as int(mc/price) (fmp_provider.py:378)."""
    return DataResult(
        data={
            "market_cap": mc,
            "current_price": price,
            "shares_outstanding": int(mc / price),
        },
        provider="fmp",
        ticker=ticker,
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _yf(ticker: str, mc: float, shares: int) -> DataResult:
    """yfinance financials result — shares is RAW from filings, NO price field."""
    return DataResult(
        data={"market_cap": mc, "shares_outstanding": shares},
        provider="yfinance",
        ticker=ticker,
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_single_class_consistent_no_warning() -> None:
    # AAPL: implied (mc/price) ≈ yfinance raw shares → ratio≈1.0 → silent.
    primary = _fmp("AAPL", 4_571_145_807_880, 311.23)
    secondary = _yf("AAPL", 4_571_145_807_880, 14_687_356_000)
    assert market_cap_consistency(primary, secondary) == []


def test_reported_below_implied_flagged_not_errored() -> None:
    # GOOG: 12.09B implied vs 5.48B reported → ratio≈2.21 → "below market-cap-implied".
    primary = _fmp("GOOG", 4_466_272_753_096, 369.27)
    secondary = _yf("GOOG", 4_492_672_630_784, 5_481_459_689)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "below market-cap-implied" in warns[0]
    assert "5,481,459,689" in warns[0]  # reported shares surfaced
    assert "2.2" in warns[0]  # ratio surfaced


def test_genuine_dual_class_below_2x_still_flagged() -> None:
    # META (genuinely dual-class) lands at ratio≈1.16 — the S&P500 study proved
    # ratio does NOT map to class count, so this MUST still flag (the old 1.8–2.5
    # "dual" band would have mislabeled it "minor"). Direction is what matters.
    primary = _fmp("META", 1_593_038_276_492, 627.57)
    secondary = _yf("META", 1_593_038_340_096, 2_196_045_588)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "below market-cap-implied" in warns[0]
    assert "1.16" in warns[0]


def test_reported_exceeds_implied_flags_stale_count() -> None:
    # DVN-like (S&P500 study): implied 621M vs yfinance reported 1.15B → ratio≈0.54.
    # reported > implied → stale/rounded share data, a distinct diagnosis.
    primary = _fmp("DVN", 60_000_000_000, 96.55)  # implied ≈ 621.4M
    secondary = _yf("DVN", 60_000_000_000, 1_153_403_107)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "EXCEED market-cap-implied" in warns[0]
    assert "stale or rounded" in warns[0]


def test_abstains_when_only_derived_shares_available() -> None:
    # THE LINEAGE TRAP: both providers report shares = mc/price (derived). There is
    # no independent share count → the check MUST abstain (return []), NOT emit a
    # spurious "consistent" pass. This is the false-positive it exists to avoid.
    primary = _fmp("XYZ", 1_000_000_000_000, 100.0)
    secondary = _fmp("XYZ", 1_000_000_000_000, 100.0).model_copy(update={"provider": "fmp2"})
    assert market_cap_consistency(primary, secondary) == []


def test_large_below_ratio_flagged_without_class_count_claim() -> None:
    # implied 10B vs reported 1B → ratio 10 (ADR ratio / extreme). Flagged by
    # direction; we deliberately do NOT claim a class count.
    primary = _fmp("ADRX", 1_000_000_000_000, 100.0)  # implied 10B
    secondary = _yf("ADRX", 1_000_000_000_000, 1_000_000_000)  # reported 1B
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "below market-cap-implied" in warns[0]
    assert "10.00" in warns[0]
    assert "triple" not in warns[0].lower()  # no false-precision class-count label


def test_empty_secondary_does_not_crash() -> None:
    primary = _fmp("AAPL", 4_571_145_807_880, 311.23)
    empty = DataResult(
        data={},
        provider="yfinance",
        ticker="AAPL",
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
    )
    # Only derived shares (primary FMP) available → abstain.
    assert market_cap_consistency(primary, empty) == []
