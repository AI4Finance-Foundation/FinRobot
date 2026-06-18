"""Cold-start warming-window contract (server.lifespan + routes/_ready.py).

During the post-yield warmup window — ``app.state.engine_ready`` / ``agents_ready``
still False, ``deps.data_layer`` holding no providers — live-data and AI routes MUST
return a clean 503 "starting" (a *pending* signal the desktop retries), never a
fabricated number nor a 500 from dereferencing the empty provider chain. The instant
the warmup task flips the flag, the same route serves.

Local-SQLite routes (artifacts / dashboard recent-research / coverage) carry NO
``Depends(ensure_engine_ready)`` — their absence here is deliberate; serving them
during the window is the whole point of the split, and their own suites cover them.

This locks the no-fabricate-during-warming guarantee so a future edit can't silently
let a warming route fetch against the empty chain.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

_MISSING = object()
_STATE_KEYS = ("engine_ready", "agents_ready", "agent", "deps", "startup_error")


@pytest.fixture
def warming_app():
    """The real FastAPI app forced into the cold-start warming state, then restored.

    ``app.state`` is module-global (one app object shared across the suite), so every
    key this test mutates is saved and restored to keep it hermetic.
    """
    from finrobot.server import app

    saved = {k: getattr(app.state, k, _MISSING) for k in _STATE_KEYS}
    app.state.engine_ready = False
    app.state.agents_ready = False
    app.state.agent = None
    app.state.startup_error = None
    # Model IS configured so the AI routes reach the WARMING guard rather than the
    # "no model configured" one. data_layer is a bare placeholder: the gate must
    # fire BEFORE any handler dereferences it.
    app.state.deps = SimpleNamespace(
        data_layer=SimpleNamespace(),
        settings=SimpleNamespace(is_model_configured=True, model_name="anthropic:claude-x"),
    )
    try:
        yield app
    finally:
        for key, value in saved.items():
            if value is _MISSING:
                if hasattr(app.state, key):
                    delattr(app.state, key)
            else:
                setattr(app.state, key, value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/data/AAPL/price",
        "/api/data/AAPL/financials",
        "/api/data/AAPL/historical",
        "/api/data/AAPL/earnings-calls",
        # Valuation live-data routes: both deref the (empty during warming)
        # provider chain. Ungated they don't 503 — `aggregate` returns a 200 with
        # an empty/stale football field, and `historical-bands` returns a 200 empty
        # band that `cached_fetch` then writes to the 12h HISTORICAL_BANDS slot,
        # so the warming-window blank persists for half a day after the engine is
        # ready. They must 503 "starting" like every other live-data route.
        "/api/valuation/aggregate/AAPL",
        "/api/valuation/historical-bands/AAPL",
    ],
)
async def test_live_data_routes_503_starting_during_warming(warming_app, path: str) -> None:
    transport = ASGITransport(app=warming_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(path)
    # 503 pending — NOT a fabricated 200 and NOT a 500 from the empty chain.
    assert resp.status_code == 503, f"{path}: expected 503 during warming, got {resp.status_code}"
    assert "starting" in resp.text.lower(), f"{path}: 503 must read as 'starting', got {resp.text}"


@pytest.mark.asyncio
async def test_chat_503_starting_during_agent_warming(warming_app) -> None:
    # Model configured + agent not yet built (agents_ready False) => 'starting',
    # distinct from the "No AI model configured" onboarding 503.
    transport = ASGITransport(app=warming_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat", json={"messages": []})
    assert resp.status_code == 503
    assert "starting" in resp.text.lower()


def test_ensure_engine_ready_gate_logic() -> None:
    """Unit proof of the gate both ways (the route tests above prove it's *wired*).

    The instant the warmup task flips engine_ready True the gate stops firing — so a
    just-warmed box serves rather than 503ing forever. An ABSENT flag defaults ready
    so test harnesses that wire app.state without a lifespan keep working.
    """
    from fastapi import HTTPException

    from finrobot.routes._ready import ensure_engine_ready, is_engine_ready

    ready = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine_ready=True)))
    assert is_engine_ready(ready) is True
    ensure_engine_ready(ready)  # must NOT raise once warmed

    warming = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine_ready=False)))
    assert is_engine_ready(warming) is False
    with pytest.raises(HTTPException) as exc:
        ensure_engine_ready(warming)
    assert exc.value.status_code == 503

    bare = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert is_engine_ready(bare) is True
    ensure_engine_ready(bare)  # absent flag → default ready → must NOT raise
