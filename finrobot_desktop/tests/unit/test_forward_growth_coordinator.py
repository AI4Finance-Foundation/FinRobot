"""fetch_forward_growth — the shared fetch-path producer behind every non-report
DCF seed entry (REST /dcf-seed + chat Monte-Carlo via seed_dcf_inputs_for_ticker,
and the IC-memo pipeline).

It must (1) turn a FORWARD_ESTIMATES payload into the same consensus growth list
the report path produces (single authoritative seed), and (2) degrade to [] on any
provider failure so a forward gap falls back to trailing CAGR instead of crashing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from finrobot.engine.compute.coordinators.dcf_seed import fetch_forward_growth
from finrobot.engine.compute.operators.forward_estimates import get_forward_revenue_growth
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType

NOW = datetime.now(tz=timezone.utc)


def _forward_rows() -> dict[str, list[dict[str, object]]]:
    """One past actual + three future estimates, ~12.5% YoY, anchored to today."""
    y = NOW.year
    revs = {y - 1: 400e9, y: 450e9, y + 1: 504e9, y + 2: 564e9}
    return {
        "rows": [{"date": f"{yr}-09-27", "estimatedRevenueAvg": rev} for yr, rev in revs.items()]
    }


class _FakeLayer:
    def __init__(self, *, data: Any = None, raise_exc: Exception | None = None) -> None:
        self._data = data
        self._raise = raise_exc
        self.calls: list[tuple[Any, str]] = []

    async def fetch(self, data_type: Any, ticker: str, **_k: Any) -> Any:
        self.calls.append((data_type, ticker))
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(data=self._data)


async def test_returns_consensus_growth_from_payload() -> None:
    payload = _forward_rows()
    dl = _FakeLayer(data=payload)
    growth = await fetch_forward_growth(dl, "AAPL")  # type: ignore[arg-type]
    assert growth  # non-empty
    assert all(0.10 < g < 0.15 for g in growth)  # ~12.5% YoY
    # single authoritative seed: helper == the leaf producer on the same payload
    assert growth == get_forward_revenue_growth(payload)
    assert dl.calls == [(DataType.FORWARD_ESTIMATES, "AAPL")]


async def test_provider_error_degrades_to_empty() -> None:
    dl = _FakeLayer(raise_exc=ProviderError("FMP network error"))
    assert await fetch_forward_growth(dl, "AAPL") == []  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, {}, {"rows": []}, {"rows": "garbage"}])
async def test_unusable_payload_degrades_to_empty(bad: Any) -> None:
    dl = _FakeLayer(data=bad)
    assert await fetch_forward_growth(dl, "AAPL") == []  # type: ignore[arg-type]
