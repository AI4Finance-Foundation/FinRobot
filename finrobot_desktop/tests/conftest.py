"""Shared test fixtures for FinRobot test suite."""

import asyncio
import faulthandler
import os
import sys
import weakref
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from finrobot.engine.data.cache import DataCache


_PYTEST_SESSION_TIMEOUT_SECONDS = int(os.environ.get("FINROBOT_PYTEST_TIMEOUT_SECONDS", "600"))
_AIOSQLITE_CLOSE_TIMEOUT_SECONDS = 2.0


def pytest_sessionstart(session: pytest.Session) -> None:
    if _PYTEST_SESSION_TIMEOUT_SECONDS <= 0:
        return
    faulthandler.dump_traceback_later(
        _PYTEST_SESSION_TIMEOUT_SECONDS,
        repeat=False,
        file=sys.__stderr__,
        exit=True,
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    faulthandler.cancel_dump_traceback_later()


@pytest.fixture(autouse=True)
async def _close_leaked_aiosqlite_connections(monkeypatch):
    """Close any aiosqlite connection a test opened but forgot to close.

    Many tests build a sqlite-backed store/cache inline (ArtifactStore,
    DataCache, QuoteCache, SqliteArtifactStore, raw aiosqlite.connect) and
    never call ``.close()``. Each open ``aiosqlite.Connection`` owns a daemon
    worker thread that holds a reference to the event loop it was created on.
    When that connection is later garbage-collected — typically while a *later*
    test's loop is active or at interpreter shutdown — its ``__del__`` enqueues
    a stop task and the worker thread calls ``call_soon_threadsafe`` on the now
    dead loop, raising ``RuntimeError: Event loop is closed`` surfaced as a
    PytestUnhandledThreadExceptionWarning (red-line per AGENTS.md).

    Rather than chase down every inline store across ~20 test files, we wrap
    ``aiosqlite.connect`` to register every connection opened during a test and
    drain the still-open ones here — inside the test's own (still-live) loop —
    so each worker thread exits cleanly against a loop that is still running.
    """
    opened: "weakref.WeakSet[aiosqlite.Connection]" = weakref.WeakSet()
    real_connect = aiosqlite.connect

    def _tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.add(conn)
        return conn

    # Patch both the canonical attribute and the re-export consumers import.
    monkeypatch.setattr(aiosqlite, "connect", _tracking_connect)
    monkeypatch.setattr("aiosqlite.core.connect", _tracking_connect, raising=False)

    yield

    for conn in list(opened):
        # Only connections that actually connected (worker thread started and
        # holds a sqlite3 handle) need draining; unconnected ones are inert.
        if getattr(conn, "_connection", None) is None:
            continue
        try:
            await asyncio.wait_for(conn.close(), timeout=_AIOSQLITE_CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            # A wedged worker/loop must not freeze the whole suite in teardown.
            # ``close()`` runs its own ``finally`` on cancellation; ``stop()`` is a
            # final best-effort nudge for a connection whose worker did not drain.
            conn.stop()
        except Exception:
            # A test may have already closed it, or the underlying handle is
            # gone — nothing left to leak in either case.
            pass


@pytest.fixture(autouse=True)
async def _close_quote_cache_singleton_between_tests():
    """Close the process-wide QuoteCache after every test.

    Without this, any async test that touches ``fetch_quotes_batch_cached``
    leaves the singleton alive past its event loop's teardown. The aiosqlite
    worker thread keeps a reference to that dead loop and tries to signal it
    on the next operation, producing ``RuntimeError: Event loop is closed``
    PytestUnhandledThreadExceptionWarning (red-line per AGENTS.md L200).
    Resetting + closing the connection inside the test's still-live loop
    makes the worker thread exit cleanly.
    """
    yield
    from finrobot.engine.data import quote_batch

    await quote_batch.close_quote_cache_singleton()


@pytest.fixture(autouse=True)
def _reset_fx_cache():
    """Clear the module-global spot-FX cache around every test. The cache is keyed
    by currency with a wall-clock TTL, so without this a rate set by one test (or
    a lock bound to that test's now-dead event loop) would leak into the next —
    e.g. a TWD rate cached as 0.03125 by one case would mask another's expected
    raise. Lazy import so conftest load doesn't pull yfinance unconditionally."""
    from finrobot.engine.data.providers.fx import clear_fx_cache

    clear_fx_cache()
    yield
    clear_fx_cache()


@pytest.fixture
async def app_with_deps(tmp_path):
    """Yield the FastAPI app with a minimal ``state.deps`` set up.

    Routes that touch ``request.app.state.deps.data_layer.cache`` (e.g.
    /price, /historical, /quarterly after the 2026-05 cache wiring) blow up
    when the lifespan handler is bypassed, which is the default in unit tests.
    This fixture installs an isolated DataCache backed by a per-test SQLite
    file under ``tmp_path`` so tests can exercise the cache wrapper end-to-end.
    """
    from finrobot.server import app

    cache = DataCache(str(tmp_path / "test_cache.db"))
    saved_deps = getattr(app.state, "deps", None)
    app.state.deps = SimpleNamespace(data_layer=SimpleNamespace(cache=cache))
    try:
        yield app
    finally:
        # Close the aiosqlite connection inside the test's still-live loop.
        # The fixture is async, so its teardown runs before the loop is torn
        # down — awaiting close() lets aiosqlite's worker thread exit cleanly.
        # Skipping this leaves the worker thread holding a dead loop and it
        # raises "RuntimeError: Event loop is closed" via call_soon_threadsafe
        # at interpreter teardown (PytestUnhandledThreadExceptionWarning).
        await cache.close()
        if saved_deps is None:
            del app.state.deps
        else:
            app.state.deps = saved_deps


@pytest.fixture
def sample_financial_data_dict():
    """Canonical normalized financial data dict (as returned by providers)."""
    return {
        "revenue": 394_328_000_000,
        "ebitda": 130_541_000_000,
        "net_income": 96_995_000_000,
        "market_cap": 2_800_000_000_000,
        "shares_outstanding": 15_550_000_000,
        "current_price": 180.0,
        "gross_margin": 0.438,
        "operating_margin": 0.302,
        "total_debt": 111_088_000_000,
        "total_cash": 29_965_000_000,
        "pe_ratio": 28.87,
        "depreciation_amortization": 11_519_000_000,
        "rd_expense": 29_915_000_000,
        "sga_expense": 24_932_000_000,
        "interest_expense": 3_933_000_000,
    }


@pytest.fixture
def sample_price_data_dict():
    """Canonical price data dict (as returned by providers)."""
    return {
        "current_price": 180.0,
        "price_history": [
            {"close": 170.0},
            {"close": 175.0},
            {"close": 180.0},
            {"close": 195.0},
            {"close": 150.0},
        ],
    }


@pytest.fixture
def now():
    """Deterministic timestamp for tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_sleep(monkeypatch):
    """Patch asyncio.sleep to be instant. For rate-limiter tests that need
    to capture sleep durations, keep the local fixture — do NOT use this one."""
    mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", mock)
    return mock
