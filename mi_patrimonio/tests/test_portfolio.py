"""
Unit tests for portfolio.py module.

Tests cover InvestorProfile, Position, and Portfolio classes.
"""
import pytest
from datetime import datetime


class TestInvestorProfile:
    """Tests for the InvestorProfile dataclass."""

    def test_create_investor_profile(self, sample_investor_profile_data):
        """Test creating an InvestorProfile from valid data."""
        from portfolio import InvestorProfile

        profile = InvestorProfile(**sample_investor_profile_data)

        assert profile.name == "Test Investor"
        assert profile.age == 45
        assert profile.investment_horizon_years == 15
        assert profile.risk_tolerance == "moderate"
        assert profile.objective == "moderate_growth"
        assert profile.monthly_contribution == 1000.0
        assert profile.restrictions == []

    def test_get_target_allocation_moderate(self, investor_profile):
        """Test getting target allocation for moderate risk profile."""
        allocation = investor_profile.get_target_allocation()

        assert "equities" in allocation
        assert "fixed_income" in allocation
        assert "gold" in allocation
        assert "crypto" in allocation
        assert "cash" in allocation
        # Moderate profile should have balanced allocation
        assert allocation["equities"] == 0.50
        assert allocation["fixed_income"] == 0.30

    def test_get_target_allocation_conservative(self, conservative_profile_data):
        """Test getting target allocation for conservative risk profile."""
        from portfolio import InvestorProfile

        profile = InvestorProfile(**conservative_profile_data)
        allocation = profile.get_target_allocation()

        # Conservative should have lower equities
        assert allocation["equities"] == 0.30
        assert allocation["fixed_income"] == 0.50

    def test_get_target_allocation_aggressive(self, aggressive_profile_data):
        """Test getting target allocation for aggressive risk profile."""
        from portfolio import InvestorProfile

        profile = InvestorProfile(**aggressive_profile_data)
        allocation = profile.get_target_allocation()

        # Aggressive should have higher equities
        assert allocation["equities"] == 0.70
        assert allocation["fixed_income"] == 0.15

    def test_to_dict(self, investor_profile):
        """Test converting InvestorProfile to dictionary."""
        data = investor_profile.to_dict()

        assert isinstance(data, dict)
        assert data["name"] == "Test Investor"
        assert data["age"] == 45
        assert data["investment_horizon_years"] == 15
        assert data["risk_tolerance"] == "moderate"

    def test_from_dict(self, sample_investor_profile_data):
        """Test creating InvestorProfile from dictionary."""
        from portfolio import InvestorProfile

        profile = InvestorProfile.from_dict(sample_investor_profile_data)

        assert profile.name == sample_investor_profile_data["name"]
        assert profile.age == sample_investor_profile_data["age"]

    def test_legacy_alias_perfilinversor(self):
        """Test that legacy PerfilInversor alias works."""
        from portfolio import PerfilInversor, InvestorProfile

        assert PerfilInversor is InvestorProfile


class TestPosition:
    """Tests for the Position dataclass."""

    def test_create_position(self, sample_position_data):
        """Test creating a Position from valid data."""
        from portfolio import Position

        position = Position(**sample_position_data)

        assert position.id == "pos_001"
        assert position.name == "iShares MSCI World"
        assert position.ticker == "IWDA.AS"
        assert position.asset_type == "ETF"
        assert position.category == "equities"
        assert position.current_value == 50000.0
        assert position.cost_basis == 45000.0
        assert position.shares == 100.0

    def test_pnl_positive(self, position):
        """Test PnL calculation for profitable position."""
        assert position.pnl == 5000.0  # 50000 - 45000

    def test_pnl_pct_positive(self, position):
        """Test PnL percentage for profitable position."""
        expected_pct = ((50000.0 / 45000.0) - 1) * 100
        assert abs(position.pnl_pct - expected_pct) < 0.01

    def test_pnl_negative(self):
        """Test PnL calculation for losing position."""
        from portfolio import Position

        position = Position(
            id="losing",
            name="Losing Position",
            ticker="LOSE",
            asset_type="ETF",
            category="equities",
            current_value=8000.0,
            cost_basis=10000.0,
            shares=100.0,
        )

        assert position.pnl == -2000.0
        assert position.pnl_pct < 0

    def test_pnl_zero_cost(self):
        """Test PnL percentage when cost is zero."""
        from portfolio import Position

        position = Position(
            id="free",
            name="Gift Position",
            ticker="GIFT",
            asset_type="Stock",
            category="equities",
            current_value=1000.0,
            cost_basis=0.0,
            shares=10.0,
        )

        assert position.pnl_pct == 0

    def test_to_dict(self, position):
        """Test converting Position to dictionary."""
        data = position.to_dict()

        assert isinstance(data, dict)
        assert data["id"] == "pos_001"
        assert data["name"] == "iShares MSCI World"
        assert data["current_value"] == 50000.0
        assert data["cost_basis"] == 45000.0

    def test_from_dict(self, sample_position_data):
        """Test creating Position from dictionary."""
        from portfolio import Position

        position = Position.from_dict(sample_position_data)

        assert position.id == sample_position_data["id"]
        assert position.ticker == sample_position_data["ticker"]

    def test_legacy_alias_posicion(self):
        """Test that legacy Posicion alias works."""
        from portfolio import Posicion, Position

        assert Posicion is Position


class TestPortfolio:
    """Tests for the Portfolio class."""

    def test_create_portfolio(self, investor_profile, patch_data_provider):
        """Test creating an empty Portfolio."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="test_001",
            name="Test Portfolio",
            profile=investor_profile,
        )

        assert portfolio.id == "test_001"
        assert portfolio.name == "Test Portfolio"
        assert portfolio.profile == investor_profile
        assert len(portfolio.positions) == 0

    def test_add_position(self, investor_profile, position, patch_data_provider):
        """Test adding a position to portfolio."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="test_001",
            name="Test Portfolio",
            profile=investor_profile,
        )

        portfolio.add_position(position)

        assert len(portfolio.positions) == 1
        assert "pos_001" in portfolio.positions
        assert portfolio.positions["pos_001"] == position

    def test_remove_position(self, investor_profile, position, patch_data_provider):
        """Test removing a position from portfolio."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="test_001",
            name="Test Portfolio",
            profile=investor_profile,
        )

        portfolio.add_position(position)
        portfolio.remove_position("pos_001")

        assert len(portfolio.positions) == 0

    def test_remove_nonexistent_position(self, investor_profile, patch_data_provider):
        """Test removing a position that doesn't exist."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="test_001",
            name="Test Portfolio",
            profile=investor_profile,
        )

        # Should not raise an error
        portfolio.remove_position("nonexistent")
        assert len(portfolio.positions) == 0

    def test_total_value(self, portfolio_with_positions):
        """Test calculating total portfolio value."""
        # Sum of all positions: 100000 + 50000 + 20000 + 15000 + 15000 = 200000
        assert portfolio_with_positions.total_value == 200000.0

    def test_total_cost(self, portfolio_with_positions):
        """Test calculating total portfolio cost."""
        # Sum of all costs: 85000 + 52000 + 18000 + 10000 + 15000 = 180000
        assert portfolio_with_positions.total_cost == 180000.0

    def test_total_pnl(self, portfolio_with_positions):
        """Test calculating total PnL."""
        # 200000 - 180000 = 20000
        assert portfolio_with_positions.total_pnl == 20000.0

    def test_total_pnl_pct(self, portfolio_with_positions):
        """Test calculating total PnL percentage."""
        expected_pct = ((200000.0 / 180000.0) - 1) * 100
        assert abs(portfolio_with_positions.total_pnl_pct - expected_pct) < 0.01

    def test_calculate_distribution(self, portfolio_with_positions):
        """Test calculating asset distribution."""
        distribution = portfolio_with_positions.calculate_distribution()

        # Total value = 200000
        # equities: 100000 = 50%
        # fixed_income: 50000 = 25%
        # gold: 20000 = 10%
        # crypto: 15000 = 7.5%
        # cash: 15000 = 7.5%

        assert "equities" in distribution
        assert distribution["equities"]["value"] == 100000.0
        assert distribution["equities"]["pct"] == 50.0

        assert distribution["fixed_income"]["value"] == 50000.0
        assert distribution["fixed_income"]["pct"] == 25.0

        assert distribution["gold"]["value"] == 20000.0
        assert distribution["gold"]["pct"] == 10.0

    def test_calculate_distribution_with_mixed_fund(
        self, investor_profile, mixed_fund_position, patch_data_provider
    ):
        """Test distribution calculation for mixed funds."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="test_mixed",
            name="Test Mixed Portfolio",
            profile=investor_profile,
        )
        portfolio.add_position(mixed_fund_position)

        distribution = portfolio.calculate_distribution()

        # Mixed fund: 100000 total, 75% equities, 25% fixed_income
        assert distribution["equities"]["value"] == 75000.0
        assert distribution["equities"]["pct"] == 75.0
        assert distribution["fixed_income"]["value"] == 25000.0
        assert distribution["fixed_income"]["pct"] == 25.0

    def test_calculate_deviations(self, portfolio_with_positions):
        """Test calculating deviations from target allocation."""
        deviations = portfolio_with_positions.calculate_deviations()

        # Moderate profile targets:
        # equities: 50%, fixed_income: 30%, gold: 8%, crypto: 2%, cash: 10%
        # Actual:
        # equities: 50%, fixed_income: 25%, gold: 10%, crypto: 7.5%, cash: 7.5%

        assert "equities" in deviations
        assert deviations["equities"]["actual"] == 50.0
        assert deviations["equities"]["target"] == 50.0
        assert deviations["equities"]["deviation"] == 0.0

        # Fixed income deviation: 25 - 30 = -5
        assert abs(deviations["fixed_income"]["deviation"] - (-5.0)) < 0.1

    def test_needs_rebalancing_true(self, portfolio_with_positions):
        """Test detecting when rebalancing is needed."""
        # Crypto is 7.5% vs target 2% = 5.5% deviation > 5% threshold
        assert portfolio_with_positions.needs_rebalancing(threshold_pct=5.0) is True

    def test_needs_rebalancing_false(self, investor_profile, patch_data_provider):
        """Test detecting when rebalancing is not needed."""
        from portfolio import Portfolio, Position

        portfolio = Portfolio(
            id="balanced",
            name="Balanced Portfolio",
            profile=investor_profile,
        )

        # Create perfectly balanced portfolio for moderate profile
        # equities: 50%, fixed_income: 30%, gold: 8%, crypto: 2%, cash: 10%
        positions = [
            ("eq", "Equities", "equities", 50000.0),
            ("fi", "Fixed Income", "fixed_income", 30000.0),
            ("gold", "Gold", "gold", 8000.0),
            ("crypto", "Crypto", "crypto", 2000.0),
            ("cash", "Cash", "cash", 10000.0),
        ]

        for pos_id, name, category, value in positions:
            portfolio.add_position(Position(
                id=pos_id,
                name=name,
                ticker=None,
                asset_type="ETF",
                category=category,
                current_value=value,
                cost_basis=value,
            ))

        assert portfolio.needs_rebalancing(threshold_pct=5.0) is False

    def test_generate_summary(self, portfolio_with_positions):
        """Test generating portfolio summary."""
        summary = portfolio_with_positions.generate_summary()

        assert summary["id"] == "test_portfolio"
        assert summary["name"] == "Test Portfolio"
        assert summary["total_value"] == 200000.0
        assert summary["total_cost"] == 180000.0
        assert summary["pnl"] == 20000.0
        assert summary["num_positions"] == 5
        assert "distribution" in summary
        assert "deviations" in summary
        assert "profile" in summary
        assert "positions" in summary

    def test_empty_portfolio_distribution(self, investor_profile, patch_data_provider):
        """Test distribution for empty portfolio."""
        from portfolio import Portfolio

        portfolio = Portfolio(
            id="empty",
            name="Empty Portfolio",
            profile=investor_profile,
        )

        distribution = portfolio.calculate_distribution()

        # All categories should have 0 value and 0 percentage
        for category in distribution:
            assert distribution[category]["value"] == 0
            assert distribution[category]["pct"] == 0

    def test_legacy_method_aliases(self, portfolio_with_positions):
        """Test that legacy method aliases work."""
        # calcular_distribucion should work
        dist_legacy = portfolio_with_positions.calcular_distribucion()
        dist_new = portfolio_with_positions.calculate_distribution()
        assert dist_legacy == dist_new

        # necesita_rebalanceo should work
        assert portfolio_with_positions.necesita_rebalanceo() == portfolio_with_positions.needs_rebalancing()

    def test_legacy_property_aliases(self, portfolio_with_positions):
        """Test that legacy property aliases work."""
        assert portfolio_with_positions.valor_total == portfolio_with_positions.total_value
        assert portfolio_with_positions.coste_total == portfolio_with_positions.total_cost
        assert portfolio_with_positions.pnl_total == portfolio_with_positions.total_pnl


class TestListPortfolios:
    """Tests for the list_portfolios function."""

    def test_list_portfolios_empty(self, tmp_path, monkeypatch):
        """Test listing portfolios when none exist."""
        import os
        from portfolio import list_portfolios
        import config

        # Create empty data directory
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setattr(config, "DATA_DIR", str(data_dir))

        # Also patch the module-level DATA_DIR in portfolio
        import portfolio
        monkeypatch.setattr(portfolio, "DATA_DIR", str(data_dir))

        # Create fresh import
        portfolios = list_portfolios()
        assert portfolios == []

    def test_legacy_alias_listar_portfolios(self):
        """Test that legacy listar_portfolios alias works."""
        from portfolio import listar_portfolios, list_portfolios

        assert listar_portfolios is list_portfolios
