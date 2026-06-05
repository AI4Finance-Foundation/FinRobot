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


def test_multi_class_flagged_not_errored() -> None:
    # GOOG: 12.09B implied vs 5.48B reported → ratio≈2.21 → dual/multi-class WARN.
    primary = _fmp("GOOG", 4_466_272_753_096, 369.27)
    secondary = _yf("GOOG", 4_492_672_630_784, 5_481_459_689)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "multi-class" in warns[0].lower() or "class" in warns[0].lower()
    assert "5,481,459,689" in warns[0]  # reported shares surfaced
    assert "2.2" in warns[0]  # ratio surfaced


def test_minor_mismatch_flagged() -> None:
    # META: 2.538B implied vs 2.196B reported → ratio≈1.16 → minor-mismatch WARN
    # (genuinely NOT a clean 2x dual-class; honest "investigate" rather than over-label).
    primary = _fmp("META", 1_593_038_276_492, 627.57)
    secondary = _yf("META", 1_593_038_340_096, 2_196_045_588)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "1.1" in warns[0] or "1.2" in warns[0]


def test_abstains_when_only_derived_shares_available() -> None:
    # THE LINEAGE TRAP: both providers report shares = mc/price (derived). There is
    # no independent share count → the check MUST abstain (return []), NOT emit a
    # spurious "consistent" pass. This is the false-positive it exists to avoid.
    primary = _fmp("XYZ", 1_000_000_000_000, 100.0)
    secondary = _fmp("XYZ", 1_000_000_000_000, 100.0).model_copy(update={"provider": "fmp2"})
    assert market_cap_consistency(primary, secondary) == []


def test_anomaly_band_for_unit_or_adr_mismatch() -> None:
    # implied 10B vs reported 1B → ratio 10 → gross anomaly (ADR ratio / unit error).
    primary = _fmp("ADRX", 1_000_000_000_000, 100.0)  # implied 10B
    secondary = _yf("ADRX", 1_000_000_000_000, 1_000_000_000)  # reported 1B
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "anomal" in warns[0].lower()


def test_triple_class_band() -> None:
    # implied 12B vs reported 4B → ratio 3.0 → triple-class band.
    primary = _fmp("TRPL", 1_200_000_000_000, 100.0)  # implied 12B
    secondary = _yf("TRPL", 1_200_000_000_000, 4_000_000_000)
    warns = market_cap_consistency(primary, secondary)
    assert len(warns) == 1
    assert "triple" in warns[0].lower()


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
