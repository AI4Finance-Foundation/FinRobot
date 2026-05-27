"""Shared test fixtures for FinRobot test suite."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from finrobot.engine.data.cache import DataCache


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


@pytest.fixture
def app_with_deps(tmp_path):
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
        # Sync close — the test loop may already be tearing down; aiosqlite's
        # async close would re-enter a closed loop and warn loudly. The OS
        # cleans the per-test sqlite file with tmp_path anyway.
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
