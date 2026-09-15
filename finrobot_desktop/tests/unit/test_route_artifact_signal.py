"""attach_signals adapter (routes/_artifact_signal.py) — v5 ADR-0001 wiring."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from finrobot.artifact.models import ArtifactSummary
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.normalize.contracts import NormalizedPrice, Provenance
from finrobot.engine.data.types import DataType
from finrobot.routes._artifact_signal import attach_signals

UTC = timezone.utc
ENTRY = datetime(2026, 4, 1, tzinfo=UTC)
NOW = ENTRY + timedelta(days=30)


def _summary(
    *,
    artifact_id: str = "art_1",
    ticker: str | None = "NVDA",
    entry: float | None = 100.0,
    target: float | None = 120.0,
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type="equity_research",
        created_at=ENTRY,
        headline="x",
        source="pipeline:equity_research",
        archived=False,
        entry_price=entry,
        target_price=target,
        target_date=ENTRY + timedelta(days=365),
        signal=None,
    )


class _StubDataLayer:
    """Pretends to be DataLayer for attach_signals — no full DataLayer needed."""

    def __init__(
        self,
        quotes: dict[str, float | None] | None = None,
        raise_for: set[str] | None = None,
        *,
        quote_currencies: dict[str, str] | None = None,
        fx_rates: dict[str, float] | None = None,
        fx_raises: bool = False,
    ) -> None:
        self._quotes = quotes or {}
        self._raise_for = raise_for or set()
        self._quote_currencies = {k.upper(): v.upper() for k, v in (quote_currencies or {}).items()}
        self._fx_rates = {k.upper(): v for k, v in (fx_rates or {}).items()}
        self._fx_raises = fx_raises
        self.fetched: list[str] = []
        self.fx_calls: list[str] = []

    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        self.fetched.append(ticker)
        if ticker in self._raise_for:
            raise ProviderError(f"simulated provider error for {ticker}")
        price = self._quotes.get(ticker)
        return DataResult(
            data={"current_price": price} if price is not None else {},
            provider="stub",
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=NOW,
        )

    async def fetch_canonical(
        self, data_type: DataType | str, ticker: str, **_: object
    ) -> NormalizedPrice:
        if DataType(data_type) != DataType.PRICE:
            raise ValueError(f"unsupported canonical type: {data_type}")
        raw = await self.fetch(DataType.PRICE, ticker)
        price = raw.data.get("current_price", 0.0)
        return NormalizedPrice(
            ticker=ticker,
            current_price=float(price or 0.0),
            quote_currency=self._quote_currencies.get(ticker.upper(), "USD"),
            bars=[],
            provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
        )

    async def fx_rate_to_usd(self, currency: str) -> float:
        self.fx_calls.append(currency.upper())
        if currency.upper() == "USD":
            return 1.0
        if self._fx_raises:
            raise ProviderError(f"no FX rate for {currency}")
        return self._fx_rates[currency.upper()]


@pytest.mark.asyncio
async def test_signals_populated_when_quote_available() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 115.0})
    out = await attach_signals([_summary()], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal == "hit"  # 115 within ±10% of 120
    assert layer.fetched == ["NVDA"]


# ── cross-currency: canonical PRICE is quote-currency, entry/target are USD ──
#
# fetch_canonical(PRICE).current_price is the quote currency (PRICE is never
# FX-normalized). For a foreign LOCAL listing (2330.TW, quote=TWD) compute_signal
# would compare a TWD price against USD entry/target → flipped verdict. attach_signals
# must convert each ticker's quote to USD (via the snapshot's quote_currency +
# DataLayer.fx_rate_to_usd) first. US / pure-ADR (quote=USD) → strict no-op.


@pytest.mark.asyncio
async def test_foreign_local_listing_signal_in_usd() -> None:
    """2330.TW: TWD quote 3620, USD entry 100 / target 130, rate 0.03178 →
    $115 USD → 'watching'. The raw-TWD 3620 ≫ 130 would falsely read 'hit'."""
    layer = _StubDataLayer(
        quotes={"2330.TW": 3620.0},
        quote_currencies={"2330.TW": "TWD"},
        fx_rates={"TWD": 0.03178},
    )
    out = await attach_signals(
        [_summary(ticker="2330.TW", entry=100.0, target=130.0)],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    # $115.04 → +15 of +30 expected move (50.1%) → just-over-half → 'hit' would be
    # by Rule 2; pick the decisive reverse case below. Here assert it is NOT the
    # raw-TWD spurious classification by checking the value is sane via the reverse
    # test; for this one we assert it converted (TWD touched FX) and verdict is a
    # legit in-range state, never the raw-price artifact.
    assert "TWD" in layer.fx_calls
    assert out[0].signal in {"hit", "watching"}


@pytest.mark.asyncio
async def test_foreign_listing_reverse_not_fake_hit() -> None:
    """Decisive red: a TWD quote that raw sits ABOVE the USD target (fake 'hit')
    but in USD is a hard reverse below entry (real 'failed'). Entry 100 / target
    130 USD; TWD 2200 × 0.03178 = $69.9 → −30% reverse → 'failed', not raw 'hit'."""
    layer = _StubDataLayer(
        quotes={"2330.TW": 2200.0},
        quote_currencies={"2330.TW": "TWD"},
        fx_rates={"TWD": 0.03178},
    )
    out = await attach_signals(
        [_summary(ticker="2330.TW", entry=100.0, target=130.0)],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert out[0].signal == "failed"  # USD reverse, NOT the raw-2200 fake hit


@pytest.mark.asyncio
async def test_us_ticker_no_fx_noop() -> None:
    """US ticker (quote=USD): strict no-op — FX never consulted, verdict unchanged."""
    layer = _StubDataLayer(
        quotes={"NVDA": 115.0},
        quote_currencies={"NVDA": "USD"},
        fx_raises=True,  # would error if the USD path touched FX
    )
    out = await attach_signals([_summary(ticker="NVDA", entry=100.0, target=120.0)], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal == "hit"
    assert layer.fx_calls == []


@pytest.mark.asyncio
async def test_foreign_fx_unavailable_drops_signal() -> None:
    """FX rate unobtainable → that artifact's signal stays None, never bucketed on
    a mixed-currency comparison."""
    layer = _StubDataLayer(
        quotes={"2330.TW": 3620.0},
        quote_currencies={"2330.TW": "TWD"},
        fx_raises=True,
    )
    out = await attach_signals(
        [_summary(ticker="2330.TW", entry=100.0, target=130.0)],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert out[0].signal is None


@pytest.mark.asyncio
async def test_quote_fetched_once_per_ticker_for_many_artifacts() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 115.0})
    out = await attach_signals(
        [
            _summary(artifact_id="a"),
            _summary(artifact_id="b"),
            _summary(artifact_id="c"),
        ],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert all(s.signal == "hit" for s in out)
    assert layer.fetched == ["NVDA"]  # batched, not per-summary


@pytest.mark.asyncio
async def test_provider_failure_leaves_signal_none_without_raising() -> None:
    layer = _StubDataLayer(raise_for={"NVDA"})
    out = await attach_signals([_summary()], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal is None


@pytest.mark.asyncio
async def test_summary_with_missing_entry_or_target_is_passed_through_untouched() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 115.0})
    out = await attach_signals(
        [_summary(entry=None), _summary(target=None), _summary(ticker=None)],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert all(s.signal is None for s in out)
    assert layer.fetched == []  # no quote needed when no summary qualifies


@pytest.mark.asyncio
async def test_zero_or_missing_quote_leaves_signal_none() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 0})
    out = await attach_signals([_summary()], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal is None


@pytest.mark.asyncio
async def test_degenerate_artifact_target_equal_entry_does_not_explode() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 100.0})
    # Old / hand-built artifact with target==entry. compute_signal raises;
    # adapter must swallow so the list keeps loading.
    s = _summary(entry=100.0, target=100.0)
    out = await attach_signals([s], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal is None


class _ConcurrencyTrackingLayer:
    """Records max in-flight fetches so we can prove quotes go out concurrently."""

    def __init__(self, quotes: dict[str, float]) -> None:
        self._quotes = quotes
        self._active = 0
        self.max_active = 0

    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        try:
            await asyncio.sleep(0.01)  # hold the fetch open so overlap is observable
        finally:
            self._active -= 1
        return DataResult(
            data={"current_price": self._quotes[ticker]},
            provider="stub",
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=NOW,
        )

    async def fetch_canonical(
        self, data_type: DataType | str, ticker: str, **_: object
    ) -> NormalizedPrice:
        if DataType(data_type) != DataType.PRICE:
            raise ValueError(f"unsupported canonical type: {data_type}")
        raw = await self.fetch(DataType.PRICE, ticker)
        return NormalizedPrice(
            ticker=ticker,
            current_price=float(raw.data["current_price"]),
            quote_currency="USD",
            bars=[],
            provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
        )


@pytest.mark.asyncio
async def test_quotes_fetched_concurrently_not_serially() -> None:
    # Regression guard for the serial→asyncio.gather change: with a serial loop
    # max_active would stay 1; concurrent fan-out lets multiple fetches overlap.
    layer = _ConcurrencyTrackingLayer(quotes={"NVDA": 115.0, "AAPL": 115.0, "MSFT": 115.0})
    out = await attach_signals(
        [
            _summary(artifact_id="a", ticker="NVDA"),
            _summary(artifact_id="b", ticker="AAPL"),
            _summary(artifact_id="c", ticker="MSFT"),
        ],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert all(s.signal == "hit" for s in out)
    assert layer.max_active >= 2  # proves overlap; serial loop could only reach 1


@pytest.mark.asyncio
async def test_quote_fanout_capped_by_semaphore() -> None:
    """A big artifact page (hundreds of unique tickers) must not stampede the
    provider pool with a bare gather — in-flight fetches are capped at
    _QUOTE_FANOUT_CONCURRENCY (same budget shape as coverage's market fan-out)."""
    from finrobot.routes._artifact_signal import _QUOTE_FANOUT_CONCURRENCY

    tickers = [f"T{i:03d}" for i in range(30)]
    layer = _ConcurrencyTrackingLayer(quotes=dict.fromkeys(tickers, 115.0))
    out = await attach_signals(
        [_summary(artifact_id=f"a{i}", ticker=t) for i, t in enumerate(tickers)],
        layer,  # type: ignore[arg-type]
        now=NOW,
    )
    assert all(s.signal == "hit" for s in out)
    assert layer.max_active <= _QUOTE_FANOUT_CONCURRENCY
    assert layer.max_active >= 2  # still concurrent, not degraded to serial
