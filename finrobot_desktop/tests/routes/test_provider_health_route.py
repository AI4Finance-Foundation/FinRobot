"""GET /api/settings/provider-health — the Settings「Data Provider Status」panel
feed (yfinance 路线图 门五②).

The signals come from the REAL ProviderHealth breaker on the live DataLayer —
never mocked health state behind a hardcoded "all green" panel. The route only
shapes (name, availability, breaker snapshot, key presence) into a stable
contract the UI renders.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.interface import DataProvider, DataResult
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType


class _NamedProvider(DataProvider):
    def __init__(self, name_: str, caps: list[str | DataType]) -> None:
        self._name = name_
        self._caps = caps

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> list[str | DataType]:
        return self._caps

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: object) -> DataResult:
        raise NotImplementedError


@pytest_asyncio.fixture
async def client_and_layer(tmp_path) -> AsyncIterator[tuple[AsyncClient, DataLayer]]:
    from finrobot.routes.settings import router

    cache = DataCache(db_path=str(tmp_path / "ph.db"))
    layer = DataLayer(
        [
            _NamedProvider("fmp", [DataType.FINANCIALS]),
            _NamedProvider("yfinance", [DataType.PRICE]),
        ],
        cache,
    )
    app = FastAPI()
    app.include_router(router)
    app.state.deps = SimpleNamespace(
        data_layer=layer,
        settings=SimpleNamespace(fmp_api_key="k-123", finnhub_api_key="", sec_user_agent=""),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c, layer
        finally:
            await cache.close()


@pytest.mark.asyncio
async def test_returns_all_providers_with_key_presence(client_and_layer) -> None:
    client, _ = client_and_layer
    resp = await client.get("/api/settings/provider-health")
    assert resp.status_code == 200
    rows = {p["name"]: p for p in resp.json()["providers"]}
    assert set(rows) == {"fmp", "yfinance"}
    fmp = rows["fmp"]
    assert fmp["key_required"] is True
    assert fmp["key_configured"] is True
    assert fmp["circuit_state"] == "closed"
    assert fmp["available"] is True
    yf = rows["yfinance"]
    assert yf["key_required"] is False
    assert yf["key_configured"] is None  # no key concept — not a fake "configured"


@pytest.mark.asyncio
async def test_rate_limited_provider_reports_open_circuit(client_and_layer) -> None:
    client, layer = client_and_layer
    # A 429 trips the breaker immediately — the panel must show the cooldown,
    # not a hardcoded green dot.
    layer._health.record_failure("yfinance", rate_limited=True)
    resp = await client.get("/api/settings/provider-health")
    rows = {p["name"]: p for p in resp.json()["providers"]}
    yf = rows["yfinance"]
    assert yf["circuit_state"] == "open"
    assert yf["available"] is False
    assert yf["last_rate_limited"] is True
    assert yf["cooldown_until"] is not None
    assert yf["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_recovery_closes_circuit(client_and_layer) -> None:
    client, layer = client_and_layer
    layer._health.record_failure("fmp", rate_limited=True)
    layer._health.record_success("fmp")
    resp = await client.get("/api/settings/provider-health")
    rows = {p["name"]: p for p in resp.json()["providers"]}
    fmp = rows["fmp"]
    assert fmp["circuit_state"] == "closed"
    assert fmp["available"] is True
    assert fmp["last_success"] is not None
    assert fmp["last_rate_limited"] is False
