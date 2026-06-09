"""Tests for S1 refactor: FinancialData sub-model split.

Verifies:
- Sub-models construct and validate independently.
- Structured constructor works with sub-model instances.
- Field access goes through sub-models (fd.income.revenue, fd.market.market_cap, etc.).
- Valuation metrics are mutable via sub-model.
- Validation constraints are preserved.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from finrobot.engine.models.financial import (
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
        revenue=1e9,
        ebitda=2e8,
        net_income=1e8,
        gross_margin=0.4,
        operating_margin=0.15,
    )
    defaults.update(overrides)
    return defaults


def _base_market(**overrides) -> dict:
    defaults = dict(market_cap=5e9, shares_outstanding=1e8, current_price=50.0)
    defaults.update(overrides)
    return defaults


def _make_fd(
    income_overrides: dict | None = None,
    market_overrides: dict | None = None,
    balance: BalanceSheet | None = None,
    valuation: ValuationMetrics | None = None,
) -> FinancialData:
    """Build FinancialData via sub-model construction."""
    inc_kw = _base_income()
    if income_overrides:
        inc_kw.update(income_overrides)
    mkt_kw = _base_market()
    if market_overrides:
        mkt_kw.update(market_overrides)
    return FinancialData(
        ticker="AAPL",
        timestamp=_NOW,
        income=IncomeStatement(**inc_kw),
        balance=balance or BalanceSheet(),
        market=MarketData(**mkt_kw),
        valuation=valuation or ValuationMetrics(),
    )


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

    def test_allows_negative_gross_margin(self):
        # Loss-maker selling below cost (RIVN-class) → gross_margin < 0; symmetric
        # with operating_margin's negative allowance.
        stmt = IncomeStatement(**_base_income(gross_margin=-0.0172))
        assert stmt.gross_margin == -0.0172

    def test_rejects_gross_margin_below_minus5(self):
        with pytest.raises(ValidationError):
            IncomeStatement(**_base_income(gross_margin=-6.0))

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
    def test_defaults_to_none_not_zero(self):
        # None ≠ 0: an unset component is "not reported", not real zero debt/cash.
        bs = BalanceSheet()
        assert bs.total_debt is None
        assert bs.total_cash is None

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

    def test_sub_model_field_access(self):
        fd = FinancialData(
            ticker="AAPL",
            timestamp=_NOW,
            income=IncomeStatement(**_base_income()),
            balance=BalanceSheet(total_debt=5e8, total_cash=2e8),
            market=MarketData(**_base_market()),
            valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5),
        )
        # Income fields via sub-model
        assert fd.income.revenue == 1e9
        assert fd.income.ebitda == 2e8
        assert fd.income.net_income == 1e8
        assert fd.income.gross_margin == 0.4
        assert fd.income.operating_margin == 0.15
        # Balance fields via sub-model
        assert fd.balance.total_debt == 5e8
        assert fd.balance.total_cash == 2e8
        # Market fields via sub-model
        assert fd.market.market_cap == 5e9
        assert fd.market.shares_outstanding == 1e8
        assert fd.market.current_price == 50.0
        # Valuation fields via sub-model
        assert fd.valuation.enterprise_value == 5.3e9
        assert fd.valuation.ev_ebitda == 26.5

    def test_balance_and_valuation_optional(self):
        """balance and valuation have defaults so only income+market are required."""
        fd = FinancialData(
            ticker="AAPL",
            timestamp=_NOW,
            income=IncomeStatement(**_base_income()),
            market=MarketData(**_base_market()),
        )
        # None ≠ 0: a missing balance component is "not reported", never a real
        # zero debt/cash (which would silently fabricate EV = market_cap).
        assert fd.balance.total_debt is None
        assert fd.valuation.enterprise_value is None


# ---------------------------------------------------------------------------
# FinancialData — sub-model construction tests
# ---------------------------------------------------------------------------


class TestSubModelConstruction:
    def test_basic_construction(self):
        fd = _make_fd()
        assert fd.ticker == "AAPL"
        assert fd.income.revenue == 1e9

    def test_sub_models_populated(self):
        fd = _make_fd(balance=BalanceSheet(total_debt=5e8, total_cash=2e8))
        assert fd.income.revenue == 1e9
        assert fd.balance.total_debt == 5e8
        assert fd.market.current_price == 50.0

    def test_sub_model_field_access(self):
        fd = _make_fd(
            balance=BalanceSheet(total_debt=5e8),
            valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5),
        )
        assert fd.balance.total_debt == 5e8
        assert fd.valuation.enterprise_value == 5.3e9
        assert fd.valuation.ev_ebitda == 26.5

    def test_allows_negative_gross_margin(self):
        # RIVN-class loss-maker → gross_margin < 0 must construct (was a 500).
        fd = _make_fd(income_overrides={"gross_margin": -0.0172})
        assert fd.income.gross_margin == -0.0172

    def test_rejects_zero_shares(self):
        with pytest.raises(ValidationError):
            _make_fd(market_overrides={"shares_outstanding": 0})

    def test_defaults_debt_cash_to_none(self):
        # None ≠ 0: unset balance components are "not reported", not real zero.
        fd = _make_fd()
        assert fd.balance.total_debt is None
        assert fd.balance.total_cash is None

    def test_da_fields_default_none(self):
        fd = _make_fd()
        assert fd.income.depreciation_amortization is None
        assert fd.income.rd_expense is None
        assert fd.income.sga_expense is None
        assert fd.income.interest_expense is None

    def test_da_fields_set(self):
        fd = _make_fd(income_overrides={"depreciation_amortization": 1e7, "rd_expense": 5e6})
        assert fd.income.depreciation_amortization == 1e7
        assert fd.income.rd_expense == 5e6

    def test_allows_negative_operating_margin(self):
        fd = _make_fd(income_overrides={"operating_margin": -2.5})
        assert fd.income.operating_margin == -2.5

    def test_all_valuation_fields(self):
        fd = _make_fd(
            valuation=ValuationMetrics(enterprise_value=5.3e9, ev_ebitda=26.5, ev_revenue=5.3)
        )
        assert fd.valuation.enterprise_value == 5.3e9
        assert fd.valuation.ev_ebitda == 26.5
        assert fd.valuation.ev_revenue == 5.3


# ---------------------------------------------------------------------------
# Mutation via sub-model tests
# ---------------------------------------------------------------------------


class TestMutationViaSubModel:
    def test_ev_ebitda_mutation(self):
        fd = _make_fd()
        fd.valuation.ev_ebitda = 25.0
        assert fd.valuation.ev_ebitda == 25.0

    def test_enterprise_value_mutation(self):
        fd = _make_fd()
        fd.valuation.enterprise_value = 5.3e9
        assert fd.valuation.enterprise_value == 5.3e9

    def test_ev_revenue_mutation(self):
        fd = _make_fd()
        fd.valuation.ev_revenue = 5.3
        assert fd.valuation.ev_revenue == 5.3

    def test_set_to_none(self):
        fd = _make_fd(valuation=ValuationMetrics(ev_ebitda=26.5))
        assert fd.valuation.ev_ebitda == 26.5
        fd.valuation.ev_ebitda = None
        assert fd.valuation.ev_ebitda is None
