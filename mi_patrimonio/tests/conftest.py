"""
Pytest configuration and fixtures for mi_patrimonio tests.

This module provides shared fixtures for testing portfolio management functionality.
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import pytest

# Add mi_patrimonio to path
MI_PATRIMONIO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(MI_PATRIMONIO_DIR))


# =============================================================================
# Mock Data Fixtures
# =============================================================================

@pytest.fixture
def sample_investor_profile_data() -> Dict[str, Any]:
    """Sample investor profile data for testing."""
    return {
        "name": "Test Investor",
        "age": 45,
        "investment_horizon_years": 15,
        "risk_tolerance": "moderate",
        "objective": "moderate_growth",
        "monthly_contribution": 1000.0,
        "restrictions": [],
    }


@pytest.fixture
def sample_position_data() -> Dict[str, Any]:
    """Sample position data for testing."""
    return {
        "id": "pos_001",
        "name": "iShares MSCI World",
        "ticker": "IWDA.AS",
        "asset_type": "ETF",
        "category": "equities",
        "current_value": 50000.0,
        "cost_basis": 45000.0,
        "shares": 100.0,
        "currency": "EUR",
        "account": "Broker A",
        "composition": None,
    }


@pytest.fixture
def sample_mixed_fund_position_data() -> Dict[str, Any]:
    """Sample mixed fund position data for testing."""
    return {
        "id": "pos_002",
        "name": "Indexa Capital Growth",
        "ticker": None,
        "asset_type": "Index Fund",
        "category": "equities",
        "current_value": 100000.0,
        "cost_basis": 90000.0,
        "shares": 1.0,
        "currency": "EUR",
        "account": "Indexa",
        "composition": {"equities": 0.75, "fixed_income": 0.25},
    }


@pytest.fixture
def sample_portfolio_positions() -> list[Dict[str, Any]]:
    """Multiple sample positions for portfolio testing."""
    return [
        {
            "id": "equities_1",
            "name": "iShares MSCI World",
            "ticker": "IWDA.AS",
            "asset_type": "ETF",
            "category": "equities",
            "current_value": 100000.0,
            "cost_basis": 85000.0,
            "shares": 200.0,
            "currency": "EUR",
            "account": "Broker A",
            "composition": None,
        },
        {
            "id": "fixed_income_1",
            "name": "Vanguard EUR Bond",
            "ticker": "VGEA.DE",
            "asset_type": "Bond ETF",
            "category": "fixed_income",
            "current_value": 50000.0,
            "cost_basis": 52000.0,
            "shares": 100.0,
            "currency": "EUR",
            "account": "Broker A",
            "composition": None,
        },
        {
            "id": "gold_1",
            "name": "Physical Gold ETC",
            "ticker": "SGLD.AS",
            "asset_type": "Gold ETF",
            "category": "gold",
            "current_value": 20000.0,
            "cost_basis": 18000.0,
            "shares": 50.0,
            "currency": "EUR",
            "account": "Broker A",
            "composition": None,
        },
        {
            "id": "crypto_1",
            "name": "Bitcoin",
            "ticker": "BTC-USD",
            "asset_type": "Crypto",
            "category": "crypto",
            "current_value": 15000.0,
            "cost_basis": 10000.0,
            "shares": 0.15,
            "currency": "EUR",
            "account": "Exchange",
            "composition": None,
        },
        {
            "id": "cash_1",
            "name": "Emergency Fund",
            "ticker": None,
            "asset_type": "Cash",
            "category": "cash",
            "current_value": 15000.0,
            "cost_basis": 15000.0,
            "shares": 15000.0,
            "currency": "EUR",
            "account": "Bank",
            "composition": None,
        },
    ]


# =============================================================================
# Mock Services Fixtures
# =============================================================================

@pytest.fixture
def mock_quote():
    """Create a mock Quote object."""
    from data_provider import Quote
    return Quote(
        ticker="IWDA.AS",
        price=85.50,
        change_pct=1.25,
        currency="EUR",
        timestamp=datetime.now(),
        name="iShares MSCI World",
    )


@pytest.fixture
def mock_data_provider(mock_quote):
    """Create a mock DataProvider."""
    mock_provider = MagicMock()
    mock_provider.get_quote.return_value = mock_quote
    mock_provider.get_exchange_rate.return_value = 0.92
    mock_provider.eur_usd_rate = 0.92
    mock_provider.convert_to_eur.side_effect = lambda x: x * 0.92
    return mock_provider


@pytest.fixture
def patch_data_provider(mock_data_provider):
    """Patch the get_data_provider function to return a mock."""
    with patch("portfolio.get_data_provider", return_value=mock_data_provider):
        yield mock_data_provider


# =============================================================================
# Domain Object Fixtures
# =============================================================================

@pytest.fixture
def investor_profile(sample_investor_profile_data):
    """Create an InvestorProfile instance."""
    from portfolio import InvestorProfile
    return InvestorProfile(**sample_investor_profile_data)


@pytest.fixture
def position(sample_position_data):
    """Create a Position instance."""
    from portfolio import Position
    return Position(**sample_position_data)


@pytest.fixture
def mixed_fund_position(sample_mixed_fund_position_data):
    """Create a mixed fund Position instance."""
    from portfolio import Position
    return Position(**sample_mixed_fund_position_data)


@pytest.fixture
def portfolio_with_positions(investor_profile, sample_portfolio_positions, patch_data_provider):
    """Create a Portfolio with multiple positions."""
    from portfolio import Portfolio, Position

    portfolio = Portfolio(
        id="test_portfolio",
        name="Test Portfolio",
        profile=investor_profile,
    )

    for pos_data in sample_portfolio_positions:
        position = Position(**pos_data)
        portfolio.add_position(position)

    return portfolio


# =============================================================================
# Risk Profile Fixtures
# =============================================================================

@pytest.fixture
def conservative_profile_data() -> Dict[str, Any]:
    """Conservative investor profile data."""
    return {
        "name": "Conservative Investor",
        "age": 60,
        "investment_horizon_years": 5,
        "risk_tolerance": "conservative",
        "objective": "preservation",
        "monthly_contribution": 500.0,
        "restrictions": ["no_crypto"],
    }


@pytest.fixture
def aggressive_profile_data() -> Dict[str, Any]:
    """Aggressive investor profile data."""
    return {
        "name": "Aggressive Investor",
        "age": 30,
        "investment_horizon_years": 30,
        "risk_tolerance": "aggressive",
        "objective": "aggressive_growth",
        "monthly_contribution": 2000.0,
        "restrictions": [],
    }
