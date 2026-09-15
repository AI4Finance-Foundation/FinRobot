"""Tests for engine/data/factory.py — graceful shutdown for non-server entrypoints."""

from __future__ import annotations

import pytest

from finrobot.engine.data import factory


@pytest.mark.asyncio
async def test_shutdown_data_layer_closes_process_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shutdown_data_layer (non-server teardown) closes the process-level quote-batch
    and SEC-holdings singletons so a script's aiosqlite workers join + WAL checkpoints,
    avoiding the 'Event loop is closed' hang. A None data_layer must be safe (nothing
    was built) and still close the singletons. Bug-4-adjacent teardown, 2026-06-24."""
    calls: list[str] = []

    async def _fake_quote() -> None:
        calls.append("quote")

    async def _fake_sec() -> None:
        calls.append("sec")

    monkeypatch.setattr("finrobot.engine.data.quote_batch.close_quote_cache_singleton", _fake_quote)
    monkeypatch.setattr("finrobot.engine.data.sec_holdings_cache.close_singleton", _fake_sec)

    await factory.shutdown_data_layer(None)
    assert calls == ["quote", "sec"]


@pytest.mark.asyncio
async def test_shutdown_data_layer_closes_layer_before_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-built DataLayer is closed first, then the process singletons."""
    order: list[str] = []

    class _StubLayer:
        async def close(self) -> None:
            order.append("layer")

    async def _noop() -> None:
        order.append("singleton")

    monkeypatch.setattr("finrobot.engine.data.quote_batch.close_quote_cache_singleton", _noop)
    monkeypatch.setattr("finrobot.engine.data.sec_holdings_cache.close_singleton", _noop)

    await factory.shutdown_data_layer(_StubLayer())  # type: ignore[arg-type]
    assert order[0] == "layer"  # layer closed before the singletons
    assert order.count("singleton") == 2
