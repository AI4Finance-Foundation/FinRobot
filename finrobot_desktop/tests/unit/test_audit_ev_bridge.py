"""Family-3 verifier: EV bridge completeness. The textbook EV = market_cap + debt
− cash OMITS preferred equity and noncontrolling (minority) interest, so an issuer
carrying either has its EV (and EV/EBITDA, EV/Revenue) understated — invisible to
the market_cap+debt−cash identity, which still "balances". Probe 2026-06-06: FMP
returns preferredStock (BAC 26B) and minorityInterest (KO 2.1B, CMCSA 0.47B).
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit.ev_bridge import audit_ev_bridge
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


def _fd(
    *,
    ticker: str = "X",
    enterprise_value: float | None = 4.0e11,
    preferred_stock: float | None = None,
    noncontrolling_interest: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(2026, 6, 6, tzinfo=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=20e9),
        balance=BalanceSheet(
            total_debt=50e9,
            total_cash=10e9,
            preferred_stock=preferred_stock,
            noncontrolling_interest=noncontrolling_interest,
        ),
        market=MarketData(market_cap=360e9, shares_outstanding=5e9, current_price=72.0),
        valuation=ValuationMetrics(enterprise_value=enterprise_value),
    )


def _checks(findings) -> set[str]:
    return {f.check for f in findings}


def test_preferred_omitted_from_ev_flagged():
    f = audit_ev_bridge(_fd(ticker="BAC", preferred_stock=26e9))
    assert any(
        x.field_key == "enterprise_value"
        and x.check == "ev_bridge_incomplete"
        and x.severity == "review"
        for x in f
    )


def test_nci_omitted_from_ev_flagged():
    f = audit_ev_bridge(_fd(ticker="KO", noncontrolling_interest=2.1e9))
    assert "ev_bridge_incomplete" in _checks(f)


def test_both_preferred_and_nci_two_findings():
    f = audit_ev_bridge(_fd(preferred_stock=10e9, noncontrolling_interest=5e9))
    assert len([x for x in f if x.check == "ev_bridge_incomplete"]) == 2


def test_no_preferred_no_nci_clean():
    assert audit_ev_bridge(_fd(preferred_stock=None, noncontrolling_interest=0.0)) == []


def test_no_ev_nothing_to_check():
    # EV was withheld upstream → no EV to call incomplete.
    f = audit_ev_bridge(_fd(enterprise_value=None, preferred_stock=26e9))
    assert f == []
