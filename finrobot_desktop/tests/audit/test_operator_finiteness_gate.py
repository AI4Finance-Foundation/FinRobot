"""Audit gate: numeric operators must reject NaN/±Inf at their own boundary.

复发台账 2026-06-10(T4#5 第 2 次复发)的机械闸门。The recurring disease:
"guards None + magnitude but not finiteness" — `x != x` only catches NaN and
lets +Inf through (positive, equal to itself); `<= 0` / range comparisons are
False for NaN; a negative base under a fractional exponent goes complex and
crashes ``float()``. Three same-day instances: fx_normalize ``_validate_rate``,
``calculate_cagr``, ``current_ev_ebitda``.

Contract enforced here, table-driven: for every registered numeric entry point,
injecting NaN / +Inf / −Inf must produce an EXPLICIT rejection — ``None`` or a
raised ``ValueError`` — never a non-finite (or fabricated finite) return.

Adding a numeric operator (or a new float parameter on an existing one) to
``finrobot/engine/compute/operators/`` requires registering its injection cases
below — the development checklist (T4#5) points here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from finrobot.engine.compute.operators.data_processor import calculate_cagr
from finrobot.engine.compute.operators.fx_normalize import (
    normalize_company_to_usd,
    normalize_financialdata_to_usd,
)
from finrobot.engine.compute.operators.multiples import (
    _sanity,
    compute_ttm_fcf,
    current_ev_ebitda,
    fcf_yield,
)
from finrobot.engine.models.financial import (
    BalanceSheet,
    CompanyFinancials,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)

NON_FINITE = [float("nan"), float("inf"), float("-inf")]


def _company(**overrides: Any) -> CompanyFinancials:
    base: dict[str, Any] = dict(
        ticker="TST",
        name="Test Co.",
        market_cap=100e9,
        revenue=10e9,
        reporting_currency="TWD",
        quote_currency="USD",
    )
    base.update(overrides)
    return CompanyFinancials(**base)


def _financial_data() -> FinancialData:
    return FinancialData(
        ticker="TST",
        company_name="Test Co.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=10e9,
            ebitda=4e9,
            net_income=3e9,
            gross_margin=0.6,
            operating_margin=0.4,
            interest_expense=1e6,
        ),
        balance=BalanceSheet(total_debt=1e9, total_cash=2e9),
        market=MarketData(
            market_cap=100e9,
            shares_outstanding=1e9,
            current_price=100.0,
            industry="Tech",
            beta=1.0,
        ),
        valuation=ValuationMetrics(),
        reporting_currency="TWD",
        quote_currency="USD",
    )


# Each row: (case-id, zero-arg callable performing the injection, expectation).
# Expectation "none" → returns None; "raises" → ValueError.
_INJECTIONS: list[tuple[str, Callable[[], Any], str]] = []

for bad in NON_FINITE:
    tag = repr(bad)
    _INJECTIONS.extend(
        [
            (
                f"calculate_cagr-start-{tag}",
                lambda bad=bad: calculate_cagr(bad, 100.0, 3),
                "none",
            ),
            (
                f"calculate_cagr-end-{tag}",
                lambda bad=bad: calculate_cagr(100.0, bad, 3),
                "none",
            ),
            (
                f"fx-company-reporting-rate-{tag}",
                lambda bad=bad: normalize_company_to_usd(_company(), bad, 1.0),
                "raises",
            ),
            (
                f"fx-financialdata-reporting-rate-{tag}",
                lambda bad=bad: normalize_financialdata_to_usd(_financial_data(), bad, 1.0),
                "raises",
            ),
            (
                f"current_ev_ebitda-net_debt-{tag}",
                lambda bad=bad: current_ev_ebitda(_financial_data(), bad),
                "none",
            ),
            (
                f"sanity-value-{tag}",
                lambda bad=bad: _sanity(bad, 0.5, 300.0),
                "none",
            ),
            (
                f"compute_ttm_fcf-ocf-{tag}",
                lambda bad=bad: compute_ttm_fcf(bad, 1e9),
                "none",
            ),
            (
                f"compute_ttm_fcf-capex-{tag}",
                lambda bad=bad: compute_ttm_fcf(1e9, bad),
                "none",
            ),
            (
                f"fcf_yield-fcf-{tag}",
                lambda bad=bad: fcf_yield(bad, 100e9),
                "none",
            ),
            (
                f"fcf_yield-market_cap-{tag}",
                lambda bad=bad: fcf_yield(1e9, bad),
                "none",
            ),
        ]
    )


@pytest.mark.parametrize(
    "call,expectation",
    [pytest.param(call, expectation, id=case_id) for case_id, call, expectation in _INJECTIONS],
)
def test_non_finite_injection_is_explicitly_rejected(
    call: Callable[[], Any], expectation: str
) -> None:
    if expectation == "raises":
        with pytest.raises(ValueError):
            call()
        return
    result = call()
    assert result is None, (
        f"non-finite injection leaked through: got {result!r} instead of an "
        "explicit None rejection — guard the parameter with math.isfinite "
        "(T4#5: `x != x` / range comparisons do NOT catch ±Inf / NaN)"
    )
