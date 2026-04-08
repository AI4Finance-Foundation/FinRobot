"""Tests for S1 refactor: FinancialData sub-model split.

Verifies:
- Sub-models construct and validate independently.
- New structured constructor works.
- Flat-kwargs constructor (backwards compat) still works.
- Property getters delegate to sub-models.
- Mutable valuation setters write through to ValuationMetrics.
- Validation constraints are preserved through the model_validator route.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from finagent.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)


def _base_income(**overrides) -> dict:
    defaults = dict(
        revenue=1e9, ebitda=2e8, net_income=1e8,
        gross_margin=0.4, operating_margin=0.15,
    )
    defaults.update(overrides)
    return defaults


def _base_market(**overrides) -> dict:
    defaults = dict(market_cap=5e9, shares_outstanding=1e8, current_price=50.0)
    defaults.update(overrides)
    return defaults


def _make_fd(**overrides) -> FinancialData:
    """Build FinancialData via flat kwargs (backwards-compat path)."""
    defaults = dict(
        ticker="AAPL",
        timestamp=_NOW,
        **_base_income(),
        **_base_market(),
    )
    defaults.update(overrides)
    return FinancialData(**defaults)


# ---------------------------------------------------------------------------
# Sub-model unit tests
# ---------------------------------------------------------------------------


class TestIncomeStatement:
    def test_basic_construction(self):
        stmt = IncomeStatement(**_base_income())
        assert stmt.revenue == 1e9
        assert stmt.ebitda == 2e8
        assert stmt.net_income == 1e8

    def test_optional_fields_default_none(self):
        stmt = IncomeStatement(**_base_income())
        assert stmt.depreciation_amortization is None
        assert stmt.rd_expense is None
        assert stmt.sga_expense is None
        assert stmt.interest_expense is None

    def test_optional_fields_set(self):
        stmt = IncomeStatement(
            **_base_income(),
            depreciation_amortization=1e7,
            rd_expense=5e6,
            sga_expense=3e7,
            interest_expense=2e6,
        )
        assert stmt.depreciation_amortization == 1e7
        assert stmt.rd_expense == 5e6

    def test_rejects_negative_gross_margin(self):
        with pytest.raises(ValidationError):
            IncomeStatement(**_base_income(gross_margin=-0.1))

    def test_rejects_gross_margin_over_1(self):
        with pytest.raises(ValidationError):
            IncomeStatement(**_base_income(gross_margin=1.1))

    def test_allows_negative_operating_margin(self):
        stmt = IncomeStatement(**_base_income(operating_margin=-2.5))
        assert stmt.operating_margin == -2.5

    def test_rejects_operating_margin_below_minus5(self):
        with pytest.raises(ValidationError):
            IncomeStatement(**_base_income(operating_margin=-6.0))


class TestBalanceSheet:
    def test_defaults_to_zero(self):
        bs = BalanceSheet()
        assert bs.total_debt == 0
        assert bs.total_cash == 0

    def test_set_values(self):
        bs = BalanceSheet(total_debt=5e8, total_cash=2e8)
        assert bs.total_debt == 5e8
        assert bs.total_cash == 2e8


class TestMarketData:
    def test_basic_construction(self):
        md = MarketData(**_base_market())
        assert md.market_cap == 5e9
        assert md.current_price == 50.0

    def test_optional_fields_default_none(self):
        md = MarketData(**_base_market())
        assert md.pe_ratio is None
        assert md.price_52w_high is None
        assert md.price_52w_low is None

    def test_rejects_zero_shares(self):
        with pytest.raises(ValidationError):
            MarketData(**_base_market(shares_outstanding=0))

    def test_rejects_zero_price(self):
        with pytest.raises(ValidationError):
            MarketData(**_base_market(current_price=0))

    def test_rejects_negative_price(self):
        with pytest.raises(ValidationError):
            MarketData(**_base_market(current_price=-1.0))


class TestValuationMetrics:
    def test_defaults_all_none(self):
        vm = ValuationMetrics()
        assert vm.enterprise_value is None
        assert vm.ev_ebitda is None
        assert vm.ev_revenue is None

    def test_is_mutable(self):
        vm = ValuationMetrics()
        vm.ev_ebitda = 25.0
        assert vm.ev_ebitda == 25.0

    def test_set_values(self):
        vm = ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5, ev_revenue=5.3)
        assert vm.enterprise_value == 5.3e9


# ---------------------------------------------------------------------------
# FinancialData — new structured constructor
# ---------------------------------------------------------------------------


class TestNewStructuredConstructor:
    def test_full_structured(self):
        fd = FinancialData(
            ticker="AAPL",
            timestamp=_NOW,
            income=IncomeStatement(**_base_income()),
            balance=BalanceSheet(total_debt=5e8, total_cash=2e8),
            market=MarketData(**_base_market()),
            valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5),
        )
        assert fd.ticker == "AAPL"
        assert fd.income.revenue == 1e9
        assert fd.balance.total_debt == 5e8
        assert fd.market.current_price == 50.0
        assert fd.valuation.ev_ebitda == 26.5

    def test_property_getters_read_from_sub_models(self):
        fd = FinancialData(
            ticker="AAPL",
            timestamp=_NOW,
            income=IncomeStatement(**_base_income()),
            balance=BalanceSheet(total_debt=5e8, total_cash=2e8),
            market=MarketData(**_base_market()),
            valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5),
        )
        # Income properties
        assert fd.revenue == 1e9
        assert fd.ebitda == 2e8
        assert fd.net_income == 1e8
        assert fd.gross_margin == 0.4
        assert fd.operating_margin == 0.15
        # Balance properties
        assert fd.total_debt == 5e8
        assert fd.total_cash == 2e8
        # Market properties
        assert fd.market_cap == 5e9
        assert fd.shares_outstanding == 1e8
        assert fd.current_price == 50.0
        # Valuation properties
        assert fd.enterprise_value == 5.3e9
        assert fd.ev_ebitda == 26.5

    def test_balance_and_valuation_optional(self):
        """balance and valuation have defaults so only income+market are required."""
        fd = FinancialData(
            ticker="AAPL",
            timestamp=_NOW,
            income=IncomeStatement(**_base_income()),
            market=MarketData(**_base_market()),
        )
        assert fd.total_debt == 0
        assert fd.enterprise_value is None


# ---------------------------------------------------------------------------
# FinancialData — flat-kwargs backwards compatibility
# ---------------------------------------------------------------------------


class TestFlatKwargsBackwardsCompat:
    def test_flat_constructor_works(self):
        fd = _make_fd()
        assert fd.ticker == "AAPL"
        assert fd.revenue == 1e9

    def test_flat_kwargs_sub_models_populated(self):
        """Flat kwargs must route into sub-model instances."""
        fd = _make_fd(total_debt=5e8, total_cash=2e8)
        assert fd.income.revenue == 1e9
        assert fd.balance.total_debt == 5e8
        assert fd.market.current_price == 50.0

    def test_flat_kwargs_property_access(self):
        fd = _make_fd(total_debt=5e8, enterprise_value=5.3e9, ev_ebitda=26.5)
        assert fd.total_debt == 5e8
        assert fd.enterprise_value == 5.3e9
        assert fd.ev_ebitda == 26.5

    def test_flat_rejects_negative_gross_margin(self):
        with pytest.raises(ValidationError):
            _make_fd(gross_margin=-0.1)

    def test_flat_rejects_zero_shares(self):
        with pytest.raises(ValidationError):
            _make_fd(shares_outstanding=0)

    def test_flat_defaults_debt_cash_to_zero(self):
        fd = _make_fd()
        assert fd.total_debt == 0
        assert fd.total_cash == 0

    def test_flat_da_fields_default_none(self):
        fd = _make_fd()
        assert fd.depreciation_amortization is None
        assert fd.rd_expense is None
        assert fd.sga_expense is None
        assert fd.interest_expense is None

    def test_flat_da_fields_set(self):
        fd = _make_fd(depreciation_amortization=1e7, rd_expense=5e6)
        assert fd.depreciation_amortization == 1e7
        assert fd.rd_expense == 5e6

    def test_flat_allows_negative_operating_margin(self):
        fd = _make_fd(operating_margin=-2.5)
        assert fd.operating_margin == -2.5

    def test_flat_with_all_valuation_fields(self):
        fd = _make_fd(enterprise_value=5.3e9, ev_ebitda=26.5, ev_revenue=5.3)
        assert fd.enterprise_value == 5.3e9
        assert fd.ev_ebitda == 26.5
        assert fd.ev_revenue == 5.3


# ---------------------------------------------------------------------------
# Mutation write-through tests
# ---------------------------------------------------------------------------


class TestMutationWriteThrough:
    def test_ev_ebitda_setter_writes_to_valuation(self):
        fd = _make_fd()
        fd.ev_ebitda = 25.0
        assert fd.ev_ebitda == 25.0
        assert fd.valuation.ev_ebitda == 25.0  # in sync with sub-model

    def test_enterprise_value_setter(self):
        fd = _make_fd()
        fd.enterprise_value = 5.3e9
        assert fd.enterprise_value == 5.3e9
        assert fd.valuation.enterprise_value == 5.3e9

    def test_ev_revenue_setter(self):
        fd = _make_fd()
        fd.ev_revenue = 5.3
        assert fd.ev_revenue == 5.3
        assert fd.valuation.ev_revenue == 5.3

    def test_setter_to_none(self):
        fd = _make_fd(ev_ebitda=26.5)
        assert fd.ev_ebitda == 26.5
        fd.ev_ebitda = None
        assert fd.ev_ebitda is None
        assert fd.valuation.ev_ebitda is None
