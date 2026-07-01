"""normalize_price / normalize_financials fixtures (ADR-0004 step 3).

Five scenarios: yfinance OHLC price, FMP close-only price (degraded),
over-wide price window (17 months → trimmed), currency-tag pass-through,
TTM lag exposure.
"""

from datetime import date, datetime, timezone

import pytest

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
    DEGRADED_PERIOD_BASIS_UNKNOWN,
    DEGRADED_PRICE_FALLBACK_CLOSE,
    DEGRADED_QUOTE_CURRENCY_MISSING,
    DEGRADED_QUOTE_TS_MISSING,
    DEGRADED_TTM_LAG,
)
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price

FETCH = datetime(2026, 5, 28, 3, 21, tzinfo=timezone.utc)


def _price_result(history, provider="fmp", timestamp=FETCH, **data) -> DataResult:
    base = {"price_history": history, "quote_currency": "USD"}
    base.update(data)
    return DataResult(
        data=base, provider=provider, ticker="TSLA", data_type="price", timestamp=timestamp
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
    # Both providers emit a quote timestamp; as_of binds to that real observation
    # instant (here the 16:00 ET close = 20:00 UTC), not the bar-date midnight.
    quote_ts = int(datetime(2026, 5, 27, 20, 0, tzinfo=timezone.utc).timestamp())
    p = normalize_price(
        _price_result(hist, provider="yfinance", current_price=440.36, quote_timestamp=quote_ts)
    )
    assert p.is_ohlc_complete is True
    assert p.provenance.degraded == []
    assert p.fifty_two_week_high() == 450.0
    assert p.fifty_two_week_low() == 295.0
    assert p.current_price == 440.36
    # as_of is the quote's observation instant, NOT the fetch wall-clock — drives
    # the freshness pill.
    assert p.provenance.as_of == datetime(2026, 5, 27, 20, 0, tzinfo=timezone.utc)
    assert p.provenance.fetched_at == FETCH


def test_price_carries_market_state_from_provider():
    """yfinance marketState is threaded verbatim onto the canonical NormalizedPrice
    (str | None), un-classified — SessionState is derived at read time, not baked
    into the cache. FMP path (no marketState key) reads back None."""
    hist = [{"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0}]
    yf = normalize_price(
        _price_result(hist, provider="yfinance", current_price=440.0, market_state="PRE")
    )
    assert yf.market_state == "PRE"
    fmp = normalize_price(_price_result(hist, provider="fmp", current_price=440.0))
    assert fmp.market_state is None


def test_price_market_state_non_string_coerced_to_none():
    """Defensive: a non-string marketState (provider glitch) → None, never a stray
    type leaking into the str | None field."""
    hist = [{"date": "2026-05-27", "close": 440.0}]
    p = normalize_price(
        _price_result(hist, provider="yfinance", current_price=440.0, market_state=7)
    )
    assert p.market_state is None


def test_price_missing_quote_currency_degrades_to_unknown_not_usd():
    hist = [{"date": "2026-05-27", "close": 640.0}]
    p = normalize_price(
        _price_result(hist, provider="yfinance", current_price=640.0, quote_currency=None)
    )
    assert p.quote_currency == "UNKNOWN"
    assert DEGRADED_QUOTE_CURRENCY_MISSING in p.provenance.degraded


def test_price_as_of_uses_quote_timestamp_not_bar_midnight():
    """External baseline (this session's FMP probe): a Friday close carries a quote
    timestamp of 2026-06-05T20:00:00Z (16:00 ET). The freshness age must read 60h
    at Monday 08:00Z — NOT 80h, which the old bar-date-midnight stamping produced."""
    hist = [
        {"date": "2026-06-04", "close": 415.0, "high": 420.0, "low": 410.0},
        {"date": "2026-06-05", "close": 391.0, "high": 400.0, "low": 388.0},
    ]
    quote_ts = 1780689600  # 2026-06-05T20:00:00Z, the real close instant
    p = normalize_price(
        _price_result(hist, provider="fmp", current_price=391.0, quote_timestamp=quote_ts)
    )
    assert p.provenance.as_of == datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)
    assert DEGRADED_QUOTE_TS_MISSING not in p.provenance.degraded
    now = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)  # Monday pre-market
    age_h = (now - p.provenance.as_of).total_seconds() / 3600
    assert age_h == 60.0  # not 80.0 (the midnight-stamping bug)


def test_price_as_of_falls_back_to_session_close_not_midnight():
    """No quote timestamp → as_of is the bar's SESSION CLOSE (16:00 ET = 20:00Z),
    not its midnight, and the approximation is flagged."""
    hist = [
        {"date": "2026-06-04", "close": 415.0, "high": 420.0, "low": 410.0},
        {"date": "2026-06-05", "close": 391.0, "high": 400.0, "low": 388.0},
    ]
    monday = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)  # fetch after the bar
    p = normalize_price(
        _price_result(hist, provider="fmp", timestamp=monday, current_price=391.0)  # no ts
    )
    assert p.provenance.as_of == datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)
    assert DEGRADED_QUOTE_TS_MISSING in p.provenance.degraded


def test_price_as_of_mode_ab_symmetry():
    """Same quote timestamp via either provider → identical as_of (Mode A/B)."""
    hist = [
        {"date": "2026-06-04", "close": 415.0, "high": 420.0, "low": 410.0},
        {"date": "2026-06-05", "close": 391.0, "high": 400.0, "low": 388.0},
    ]
    quote_ts = 1780689600
    fmp = normalize_price(
        _price_result(hist, provider="fmp", current_price=391.0, quote_timestamp=quote_ts)
    )
    yf = normalize_price(
        _price_result(hist, provider="yfinance", current_price=391.0, quote_timestamp=quote_ts)
    )
    assert (
        fmp.provenance.as_of
        == yf.provenance.as_of
        == datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)
    )


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


def test_price_double_missing_raises_no_zero_fabrication():
    """Bug 21: no current_price AND no usable bars → refuse to normalize.
    The old ``else 0.0`` fallback canonicalized a fabricated $0 quote into the
    versioned PRICE slot, where it read as a real price for the whole TTL."""
    for history in ([], [{"date": "2026-05-27"}]):  # empty, and bars without close
        with pytest.raises(ValueError, match="neither current_price nor any usable price bars"):
            normalize_price(_price_result(history))


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


def test_financials_usd_tag_passes_through_for_foreign_issuer():
    # 2026-06-10 篮子 probe(21 tickers):yfinance financialCurrency 21/21 正确
    # (12 家非 USD 报表外国发行人全部带对本币 tag),而旧 country 启发式把 7/9
    # 真 USD 报表外国发行人改错(LULU→CAD、SHEL→GBP 等,全报表错缩 ~27%)。
    # provider tag 直通;双 USD 外籍发行人的人工复核由族1 验收器
    # audit_foreign_issuer_usd_tags 给 review 横幅,绝不改写数字。
    fin = normalize_financials(
        _fin_result(
            revenue=1e9,
            market_cap=5e11,
            financial_currency="USD",
            country="Canada",
            date="2026-03-31",
        )
    )
    assert fin.reporting_currency == "USD"
    assert fin.quote_currency == "USD"
    assert "ccy_inferred" not in fin.provenance.degraded


def test_financials_is_adr_passes_through():
    # FMP /profile isAdr rides into the snapshot so the family-1 acceptor can
    # suppress its USD/USD review banner for a confirmed ADR (SHEL/TSM class).
    fin = normalize_financials(
        _fin_result(revenue=1e9, country="Taiwan", is_adr=True, date="2026-03-31")
    )
    assert fin.is_adr is True


def test_financials_is_adr_absent_defaults_none():
    # yfinance path (and old cached payloads) carry no is_adr → None = "unknown",
    # which keeps the banner; only a confirmed True suppresses it.
    fin = normalize_financials(_fin_result(revenue=1e9, country="Taiwan", date="2026-03-31"))
    assert fin.is_adr is None


def test_financials_non_usd_tag_passes_through():
    # 正确打 tag 的外国发行人(TSM=TWD 类)不受影响:tag 原样直通,FX 闸照常转换。
    fin = normalize_financials(
        _fin_result(
            revenue=2e12,
            market_cap=5e11,
            financial_currency="TWD",
            country="Taiwan",
            date="2026-03-31",
        )
    )
    assert fin.reporting_currency == "TWD"
    assert fin.quote_currency == "USD"


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
    assert fin.period_end is not None
    assert fin.period_end.isoformat() == "2025-09-30"
    assert fin.pe_ttm_lag_quarters is not None
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


def test_financials_carries_ttm_quarter_ends():
    # The FMP TTM path carries the 4 quarter-end strings; normalize parses them to
    # dates so the family-4 verifier can assert non-overlap. Bad/empty strings drop.
    fin = normalize_financials(
        _fin_result(
            revenue=1e9,
            date="2026-03-31",
            period_basis="ttm",
            ttm_quarter_ends=["2026-03-31", "2025-12-31", "", "2025-06-30"],
        )
    )
    assert fin.ttm_quarter_ends == [date(2026, 3, 31), date(2025, 12, 31), date(2025, 6, 30)]


def test_financials_no_ttm_quarter_ends_defaults_empty():
    # yfinance / annual rows omit the field → empty list (verifier abstains).
    fin = normalize_financials(_fin_result(revenue=1e9, date="2026-03-31"))
    assert fin.ttm_quarter_ends == []


def test_financials_missing_period_basis_is_degraded():
    """Provider omits period_basis (None/empty) → defaults to ttm but stamps
    DEGRADED_PERIOD_BASIS_UNKNOWN so the unknown basis is visible, not silent."""
    fin = normalize_financials(_fin_result(revenue=1e9, date="2026-03-31"))
    assert fin.period_basis == "ttm"
    assert DEGRADED_PERIOD_BASIS_UNKNOWN in fin.provenance.degraded


def test_financials_unrecognized_period_basis_is_degraded():
    """Provider sends a non-standard basis string (e.g. 'fy2024') → defaults to
    ttm and stamps DEGRADED_PERIOD_BASIS_UNKNOWN instead of silently mislabeling."""
    fin = normalize_financials(_fin_result(revenue=1e9, date="2026-03-31", period_basis="fy2024"))
    assert fin.period_basis == "ttm"
    assert DEGRADED_PERIOD_BASIS_UNKNOWN in fin.provenance.degraded


def test_financials_valid_period_basis_no_degraded_marker():
    """Explicit valid basis strings must NOT trigger the unknown marker."""
    for basis in ("ttm", "annual", "quarterly"):
        fin = normalize_financials(_fin_result(revenue=1e9, date="2026-03-31", period_basis=basis))
        assert fin.period_basis == basis
        assert DEGRADED_PERIOD_BASIS_UNKNOWN not in fin.provenance.degraded


def test_financials_missing_revenue_market_cap_stay_none():
    """BUG-038/039/042: when a provider omits revenue/market_cap, normalization
    must leave them None — a missing-data signal — not fabricate 0.0. A
    fabricated 0.0 is a valid-looking number that masks the gap (and a zero
    market_cap silently collapses any downstream EV = market_cap + debt − cash)."""
    fin = normalize_financials(_fin_result(net_income=1.0e9))
    assert fin.revenue is None
    assert fin.market_cap is None


def test_price_nan_close_bar_dropped_not_serialized():
    """yfinance can hand an all-NaN OHLC session row (live 2026-06-11: AAPL
    2026-06-10). A NaN close passes every `is None` gate, serializes to
    close:null and crashes chart consumers — the canonical chokepoint must
    treat non-finite as missing (守 None ≠ 守 finiteness) and drop the bar."""
    hist = [
        {"date": "2026-05-26", "close": 300.0, "high": 305.0, "low": 295.0},
        {"date": "2026-05-27", "close": 440.0, "high": 450.0, "low": 430.0},
        {"date": "2026-05-28", "close": float("nan"), "high": float("nan"), "low": float("nan")},
    ]
    out = normalize_price(_price_result(hist, current_price=441.0, quote_timestamp=FETCH))
    assert [b.date.isoformat() for b in out.bars] == ["2026-05-26", "2026-05-27"]
    assert all(b.close == b.close for b in out.bars)  # no NaN survived


def test_pricebar_construction_invariant_rejects_non_finite_close():
    """机械闸门 (T4#5 二次复发升级): a non-finite close cannot construct a
    PriceBar — producers that forget to filter NaN session rows fail LOUD at
    the contract instead of shipping close:null to the chart."""
    import pytest as _pytest

    from finrobot.engine.data.normalize.contracts import PriceBar

    with _pytest.raises(ValueError, match="finite"):
        PriceBar(date=date(2026, 6, 10), close=float("nan"))
    # Optional OHLCV fields coerce non-finite → None (close-only bar stays legal).
    bar = PriceBar(date=date(2026, 6, 10), close=100.0, open=float("nan"), volume=float("inf"))
    assert bar.open is None and bar.volume is None and bar.close == 100.0
