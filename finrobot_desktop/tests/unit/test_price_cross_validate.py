"""Tests for cross-source current-price validation (ADR-0004 §6 open question H).

Pure-function band tests plus an integration test proving ``fetch_price`` pulls a
SECOND provider's QUOTE on cache-miss and surfaces a divergence warning — while a
secondary failure never blocks the primary price.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.interface import DataProvider, DataResult
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.normalize.contracts import degraded_price_divergence
from finrobot.engine.data.types import DataType
from finrobot.engine.data.validator import cross_validate_price


def _price_result(
    provider: str, *, current: float | None = None, quote: float | None = None
) -> DataResult:
    data: dict[str, float] = {}
    if current is not None:
        data["current_price"] = current
    if quote is not None:
        data["price"] = quote
    return DataResult(
        data=data,
        provider=provider,
        ticker="AAPL",
        data_type=DataType.PRICE,
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_agreeing_prices_no_warning() -> None:
    # FMP PRICE (current_price) vs yfinance QUOTE (price), within 5%.
    primary = _price_result("fmp", current=311.23)
    secondary = _price_result("yfinance", quote=311.20)
    assert cross_validate_price(primary, secondary) == []


def test_split_unadjusted_divergence_flagged() -> None:
    # ~2× mismatch (one side missed a 2:1 split) → must warn.
    primary = _price_result("fmp", current=311.23)
    secondary = _price_result("yfinance", quote=155.60)
    warns = cross_validate_price(primary, secondary)
    assert len(warns) == 1
    assert "Price discrepancy" in warns[0]
    assert "311.23" in warns[0] and "155.60" in warns[0]


def test_just_within_tolerance_silent() -> None:
    # 4% gap — under the 5% band, tolerate (delayed feed on a volatile session).
    primary = _price_result("fmp", current=100.0)
    secondary = _price_result("yfinance", quote=96.0)
    assert cross_validate_price(primary, secondary) == []


def test_just_over_tolerance_flagged() -> None:
    primary = _price_result("fmp", current=100.0)
    secondary = _price_result("yfinance", quote=93.0)  # 7% gap
    assert len(cross_validate_price(primary, secondary)) == 1


def test_missing_secondary_price_abstains() -> None:
    primary = _price_result("fmp", current=311.23)
    empty = _price_result("yfinance")
    assert cross_validate_price(primary, empty) == []


def test_nonpositive_price_abstains() -> None:
    primary = _price_result("fmp", current=311.23)
    zero = _price_result("yfinance", quote=0.0)
    assert cross_validate_price(primary, zero) == []


# --- integration: fetch_price wiring ----------------------------------------


class _StubProvider(DataProvider):
    def __init__(
        self, name_: str, caps: list[str], price_val: float, *, quote_raises: bool = False
    ):
        self._name = name_
        self._caps = caps
        self._price = price_val
        self._quote_raises = quote_raises
        self.quote_calls = 0

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> list[str]:
        return self._caps

    async def fetch(self, ticker: str, data_type: str, **kwargs: object) -> DataResult:
        if data_type == DataType.QUOTE:
            self.quote_calls += 1
            if self._quote_raises:
                from finrobot.engine.data.interface import ProviderError

                raise ProviderError("quote down")
            return DataResult(
                data={"price": self._price},
                provider=self._name,
                ticker=ticker,
                data_type=DataType.QUOTE,
                timestamp=datetime.now(tz=timezone.utc),
            )
        return DataResult(
            data={"current_price": self._price, "price_history": []},
            provider=self._name,
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=datetime.now(tz=timezone.utc),
        )


@pytest.fixture
async def cache(tmp_path):
    c = DataCache(db_path=str(tmp_path / "price_xval.db"))
    try:
        yield c
    finally:
        await c.close()


async def test_fetch_price_flags_cross_source_divergence(cache) -> None:
    primary = _StubProvider("fmp", [DataType.PRICE, DataType.QUOTE], 311.23)
    secondary = _StubProvider("yfinance", [DataType.PRICE, DataType.QUOTE], 155.60)  # ~2× off
    layer = DataLayer([primary, secondary], cache)
    result = await layer.fetch_price("AAPL")
    assert result.provider == "fmp"  # primary still wins
    assert secondary.quote_calls == 1  # second provider probed via QUOTE only
    assert any("Price discrepancy" in w for w in result.warnings)
    assert result.price_field_divergences == ["current_price"]


async def test_fetch_price_silent_when_sources_agree(cache) -> None:
    primary = _StubProvider("fmp", [DataType.PRICE, DataType.QUOTE], 311.23)
    secondary = _StubProvider("yfinance", [DataType.PRICE, DataType.QUOTE], 311.10)
    layer = DataLayer([primary, secondary], cache)
    result = await layer.fetch_price("AAPL")
    assert not any("Price discrepancy" in w for w in result.warnings)


async def test_fetch_price_survives_secondary_quote_failure(cache) -> None:
    primary = _StubProvider("fmp", [DataType.PRICE, DataType.QUOTE], 311.23)
    secondary = _StubProvider(
        "yfinance", [DataType.PRICE, DataType.QUOTE], 155.60, quote_raises=True
    )
    layer = DataLayer([primary, secondary], cache)
    result = await layer.fetch_price("AAPL")  # must not raise
    assert result.data["current_price"] == 311.23
    assert not any("Price discrepancy" in w for w in result.warnings)


async def test_fetch_canonical_price_uses_validated_price_path(cache) -> None:
    primary = _StubProvider("fmp", [DataType.PRICE, DataType.QUOTE], 311.23)
    secondary = _StubProvider("yfinance", [DataType.PRICE, DataType.QUOTE], 155.60)
    layer = DataLayer([primary, secondary], cache)

    result = await layer.fetch_canonical(DataType.PRICE, "AAPL")

    assert result.provenance.provider == "fmp"
    assert secondary.quote_calls == 1
    assert any("Price discrepancy" in w for w in result.warnings)
    assert degraded_price_divergence("current_price") in result.provenance.degraded
