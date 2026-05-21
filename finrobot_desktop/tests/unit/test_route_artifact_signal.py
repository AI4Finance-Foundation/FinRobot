"""attach_signals adapter (routes/_artifact_signal.py) — v5 ADR-0001 wiring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finagent.artifact.models import ArtifactSummary
from finagent.engine.data.interface import DataResult, ProviderError
from finagent.engine.data.types import DataType
from finagent.routes._artifact_signal import attach_signals

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
        self, quotes: dict[str, float | None] | None = None, raise_for: set[str] | None = None
    ) -> None:
        self._quotes = quotes or {}
        self._raise_for = raise_for or set()
        self.fetched: list[str] = []

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


@pytest.mark.asyncio
async def test_signals_populated_when_quote_available() -> None:
    layer = _StubDataLayer(quotes={"NVDA": 115.0})
    out = await attach_signals([_summary()], layer, now=NOW)  # type: ignore[arg-type]
    assert out[0].signal == "hit"  # 115 within ±10% of 120
    assert layer.fetched == ["NVDA"]


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
