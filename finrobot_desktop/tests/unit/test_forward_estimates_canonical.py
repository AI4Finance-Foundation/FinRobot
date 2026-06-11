"""FORWARD_ESTIMATES through the canonical gate (hard single-source).

Before this change every seed entry fetched the analyst-consensus payload via
raw ``fetch()`` — five best-effort fetches that could transiently diverge when
a provider flaked between two calls (one surface seeds from consensus, another
falls back to trailing CAGR for the SAME ticker). Routing the payload through
``fetch_canonical`` buys the canonical guarantees: a versioned cache slot, a
single-flight per (data_type, ticker), provenance stamping, and a shared
failure semantic (ProviderError raised to every caller instead of a private
error-dict).

The contract is a typed ENVELOPE: rows stay raw FMP dicts because spec §6.4.1
makes ``compute.operators.forward_estimates`` the only module allowed to
interpret a forward row — normalize/ must not re-derive FY1 or growth here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.normalize import (
    NormalizedForwardEstimates,
    normalize_forward_estimates,
)
from finrobot.engine.data.types import DataType

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)

_ROWS = [
    {"date": "2025-09-27", "revenueAvg": 400e9},
    {"date": "2026-09-27", "revenueAvg": 450e9},
    {"date": "2027-09-27", "revenueAvg": 504e9},
]


def _result(
    rows: object = None, *, provider: str = "fmp", warnings: list[str] | None = None
) -> DataResult:
    return DataResult(
        data={"rows": _ROWS if rows is None else rows},
        provider=provider,
        ticker="AAPL",
        data_type=DataType.FORWARD_ESTIMATES,
        timestamp=NOW,
        warnings=warnings or [],
    )


class _Provider(DataProvider):
    def __init__(self, result: DataResult | None = None, raises: Exception | None = None):
        self._result = result
        self._raises = raises
        self.fetch_called = 0

    @property
    def name(self) -> str:
        return "fmp"

    def capabilities(self) -> list[str]:
        return [DataType.FORWARD_ESTIMATES]

    async def fetch(self, ticker: str, data_type: str, **kwargs: object) -> DataResult:
        self.fetch_called += 1
        if self._raises:
            raise self._raises
        assert self._result is not None
        return self._result


@pytest.fixture
async def cache(tmp_path):
    c = DataCache(db_path=str(tmp_path / "fwd_canonical_test.db"))
    try:
        yield c
    finally:
        await c.close()


class TestNormalizeForwardEstimates:
    def test_rows_preserved_verbatim_with_provenance(self) -> None:
        nf = normalize_forward_estimates(_result(warnings=["FMP data delayed 15min"]))
        assert isinstance(nf, NormalizedForwardEstimates)
        assert nf.ticker == "AAPL"
        assert nf.rows == _ROWS  # raw dicts untouched — §6.4.1 leaf interprets them
        assert nf.provenance.provider == "fmp"
        assert nf.provenance.fetched_at == NOW
        assert nf.warnings == ["FMP data delayed 15min"]

    def test_payload_matches_red_line_leaf_shape(self) -> None:
        nf = normalize_forward_estimates(_result())
        assert nf.payload() == {"rows": _ROWS}

    def test_non_dict_rows_dropped(self) -> None:
        nf = normalize_forward_estimates(_result(rows=[_ROWS[0], "garbage", None, 42]))
        assert nf.rows == [_ROWS[0]]

    @pytest.mark.parametrize("bad", [None, "garbage", {"rows": "garbage"}, {}])
    def test_unusable_payload_normalizes_to_empty_rows(self, bad: object) -> None:
        result = DataResult(
            data=bad if isinstance(bad, dict) else {"data": bad},
            provider="fmp",
            ticker="AAPL",
            data_type=DataType.FORWARD_ESTIMATES,
            timestamp=NOW,
        )
        assert normalize_forward_estimates(result).rows == []


class TestFetchCanonicalForwardEstimates:
    async def test_miss_fetches_normalizes_and_caches(self, cache) -> None:
        provider = _Provider(result=_result())
        layer = DataLayer([provider], cache)
        nf = await layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL")
        assert isinstance(nf, NormalizedForwardEstimates)
        assert nf.rows == _ROWS
        assert provider.fetch_called == 1
        # second read is served from the canonical slot, not the provider
        again = await layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL")
        assert provider.fetch_called == 1
        assert again.rows == _ROWS
        assert again.provenance.from_cache is True

    async def test_all_providers_failed_raises_provider_error(self, cache) -> None:
        provider = _Provider(raises=ProviderError("FMP down"))
        layer = DataLayer([provider], cache)
        with pytest.raises(ProviderError):
            await layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL")

    async def test_no_capable_provider_raises_provider_error(self, cache) -> None:
        layer = DataLayer([], cache)  # yfinance-only installs have no FMP capability
        with pytest.raises(ProviderError):
            await layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL")

    async def test_concurrent_callers_share_one_provider_fetch(self, cache) -> None:
        provider = _Provider(result=_result())
        layer = DataLayer([provider], cache)
        a, b = await asyncio.gather(
            layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL"),
            layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL"),
        )
        assert provider.fetch_called == 1
        assert a.rows == b.rows == _ROWS

    async def test_read_canonical_cached_returns_primed_snapshot(self, cache) -> None:
        provider = _Provider(result=_result())
        layer = DataLayer([provider], cache)
        await layer.fetch_canonical(DataType.FORWARD_ESTIMATES, "AAPL")
        hit = await layer.read_canonical_cached(DataType.FORWARD_ESTIMATES, "AAPL")
        assert hit is not None
        snapshot, is_stale = hit
        assert isinstance(snapshot, NormalizedForwardEstimates)
        assert snapshot.rows == _ROWS
        assert is_stale is False
