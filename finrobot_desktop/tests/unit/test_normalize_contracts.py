"""Contract-model helper tests (ADR-0004 step 1)."""

from datetime import date, datetime, timezone

import pytest

from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
    NormalizedFinancials,
    NormalizedPrice,
    PriceBar,
    Provenance,
    financials_with_display_price,
)


def _prov(**kw) -> Provenance:
    base = dict(
        provider="fmp",
        as_of=datetime(2026, 5, 27, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    base.update(kw)
    return Provenance(**base)


def _price(bars: list[PriceBar], **kw) -> NormalizedPrice:
    base = dict(
        ticker="TSLA",
        bars=bars,
        current_price=bars[-1].close if bars else 0.0,
        provenance=_prov(),
    )
    base.update(kw)
    return NormalizedPrice(**base)


def test_52w_high_low_use_intraday_when_present():
    bars = [
        PriceBar(date=date(2025, 6, 1), close=400.0, high=405.0, low=395.0),
        PriceBar(date=date(2026, 5, 27), close=440.0, high=450.0, low=430.0),
    ]
    p = _price(bars)
    assert p.fifty_two_week_high() == 450.0
    assert p.fifty_two_week_low() == 395.0


def test_52w_high_low_fall_back_to_close_when_ohlc_missing():
    bars = [
        PriceBar(date=date(2025, 6, 1), close=300.0),
        PriceBar(date=date(2026, 5, 27), close=440.0),
    ]
    p = _price(bars, is_ohlc_complete=False, provenance=_prov(degraded=[DEGRADED_CLOSE_ONLY]))
    assert p.fifty_two_week_high() == 440.0
    assert p.fifty_two_week_low() == 300.0
    assert DEGRADED_CLOSE_ONLY in p.provenance.degraded


def test_trailing_1y_return_anchors_to_first_in_window_bar():
    bars = [
        PriceBar(date=date(2025, 5, 27), close=362.89),
        PriceBar(date=date(2025, 12, 16), close=489.88),
        PriceBar(date=date(2026, 5, 27), close=440.36),
    ]
    p = _price(bars)
    # (440.36 - 362.89) / 362.89 * 100 ≈ 21.35
    assert round(p.trailing_1y_return_pct(), 1) == 21.3


def test_latest_session_change_is_last_two_closes():
    bars = [
        PriceBar(date=date(2026, 5, 26), close=433.59),
        PriceBar(date=date(2026, 5, 27), close=440.36),
    ]
    chg, pct = _price(bars).latest_session_change()
    assert round(chg, 2) == 6.77
    assert round(pct, 2) == 1.56


def test_helpers_safe_on_empty_or_single_bar():
    empty = NormalizedPrice(ticker="X", bars=[], current_price=0.0, provenance=_prov())
    assert empty.fifty_two_week_high() is None
    assert empty.trailing_1y_return_pct() is None
    assert empty.latest_session_change() == (None, None)
    one = _price([PriceBar(date=date(2026, 5, 27), close=440.0)])
    assert one.fifty_two_week_high() == 440.0
    assert one.trailing_1y_return_pct() is None


def test_to_prompt_summary_surfaces_most_recent_bars_not_oldest():
    """The LLM-facing PRICE summary must show the TAIL (most-recent) bars, not the
    head of the ascending 52-week series. Regression for the 2026-06-09 TSLA
    report, which narrated the OLDEST 5 bars (a ~year-old window) as 'Recent Price
    History' because the full ascending series was dumped into the prompt."""
    bars = [
        PriceBar(date=date(2025, 6, 9), close=300.0),
        PriceBar(date=date(2025, 9, 1), close=350.0),
        PriceBar(date=date(2025, 12, 1), close=380.0),
        PriceBar(date=date(2026, 3, 1), close=400.0),
        PriceBar(date=date(2026, 5, 26), close=433.59),
        PriceBar(date=date(2026, 5, 27), close=440.36),
    ]
    summary = _price(bars).to_prompt_summary(recent_bars=3)
    dates = [b["date"] for b in summary["most_recent_bars"]]
    # The three MOST-RECENT dates, in order — never the 2025-06-09 head.
    assert dates == ["2026-03-01", "2026-05-26", "2026-05-27"]
    assert "2025-06-09" not in dates
    # Derived metrics ride along so the LLM never recomputes from raw bars.
    assert summary["current_price"] == 440.36
    assert summary["fifty_two_week_high"] == 440.36
    assert summary["fifty_two_week_low"] == 300.0
    assert summary["as_of"] == "2026-05-27T00:00:00+00:00"


def test_to_prompt_summary_safe_on_empty_bars():
    summary = NormalizedPrice(
        ticker="X", bars=[], current_price=0.0, provenance=_prov()
    ).to_prompt_summary()
    assert summary["most_recent_bars"] == []
    assert summary["fifty_two_week_high"] is None


def _fin(**kw) -> NormalizedFinancials:
    base = dict(
        ticker="AAPL",
        current_price=287.98,
        market_cap=4.230e12,
        pe_ratio=34.51,
        shares_outstanding=4.230e12 / 287.98,
        as_of=datetime(2026, 6, 30, 16, 14, tzinfo=timezone.utc),
        provenance=_prov(),
    )
    base.update(kw)
    return NormalizedFinancials(**base)


def test_financials_with_display_price_marks_to_live():
    """The FINANCIALS canonical's stale embedded price/market_cap/P-E are marked to
    the fresh PRICE canonical, scaled by the price move so all three stay mutually
    consistent (market_cap = shares × live price) — the same basis
    extract_financial_data marks the structured market block to. Reproduces the
    AAPL 2026-07-02 numbers: $287.98/$4.230T/34.51 → $294.38/$4.324T/35.28."""
    fin = _fin()
    price = _price([PriceBar(date=date(2026, 7, 1), close=294.38)], current_price=294.38)
    marked = financials_with_display_price(fin, price)
    ratio = 294.38 / 287.98
    assert marked.current_price == 294.38
    assert marked.market_cap == pytest.approx(4.230e12 * ratio)  # ≈ 4.324e12 = shares × live
    assert marked.pe_ratio == pytest.approx(34.51 * ratio)  # ≈ 35.28
    # Pure: the source snapshot is untouched.
    assert fin.current_price == 287.98
    assert fin.market_cap == 4.230e12


def test_financials_with_display_price_noop_when_price_absent():
    """No live price to mark to → the FINANCIALS snapshot is returned unchanged."""
    fin = _fin()
    price = _price([PriceBar(date=date(2026, 7, 1), close=294.38)], current_price=0.0)
    assert financials_with_display_price(fin, price) is fin
