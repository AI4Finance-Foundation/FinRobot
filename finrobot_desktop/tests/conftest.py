"""Shared test fixtures for FinAgent test suite."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest


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
            {"close": 170.0}, {"close": 175.0}, {"close": 180.0},
            {"close": 195.0}, {"close": 150.0},
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
