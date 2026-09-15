"""Family-3 verifier: EV bridge completeness. ``calculate_ev`` now folds preferred
equity and noncontrolling (minority) interest into EV, so a REPORTED component is no
longer dropped. The residual gap is an UNREPORTED component (None): the extractor
assumes 0, which is usually right but unverifiable — if the issuer carries it, EV
(and EV/EBITDA, EV/Revenue) is understated, invisible to the identity that still
"balances". Probe 2026-06-06: FMP returns preferredStock (BAC 26B) and
minorityInterest (KO 2.1B, CMCSA 0.47B) — those reported values now ride in EV.
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


def test_reported_preferred_now_in_ev_not_flagged():
    # BAC preferred 26B is REPORTED → calculate_ev folds it in → nothing to flag.
    f = audit_ev_bridge(_fd(ticker="BAC", preferred_stock=26e9, noncontrolling_interest=0.0))
    assert f == []


def test_reported_nci_now_in_ev_not_flagged():
    # KO NCI 2.1B reported → in EV → no flag.
    f = audit_ev_bridge(_fd(ticker="KO", preferred_stock=0.0, noncontrolling_interest=2.1e9))
    assert f == []


def test_unreported_preferred_flagged():
    # preferred None → EV assumed 0, completeness unverifiable → review finding.
    f = audit_ev_bridge(_fd(preferred_stock=None, noncontrolling_interest=0.0))
    assert any(
        x.field_key == "enterprise_value"
        and x.check == "ev_bridge_unverified"
        and x.severity == "review"
        for x in f
    )


def test_both_unreported_two_findings():
    f = audit_ev_bridge(_fd(preferred_stock=None, noncontrolling_interest=None))
    assert len([x for x in f if x.check == "ev_bridge_unverified"]) == 2


def test_both_reported_clean():
    # Both components reported (values) → folded into EV → no flag.
    f = audit_ev_bridge(_fd(preferred_stock=10e9, noncontrolling_interest=5e9))
    assert f == []


def test_no_ev_nothing_to_check():
    # EV was withheld upstream → no EV to verify, even with an unreported component.
    f = audit_ev_bridge(_fd(enterprise_value=None, preferred_stock=None))
    assert f == []
