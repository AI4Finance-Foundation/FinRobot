"""class B: FinancialData structural invariant — a cross-currency EV/multiple
cannot be constructed.

The safety net behind the canonical FX gate (class A). If FX normalization was
skipped or failed for a foreign ADR (reporting_currency ≠ quote_currency), an
EV-based ratio mixes a quote-currency market_cap with reporting-currency net debt
— the meaningless -75B TSM EV / -0.026 EV/EBITDA (probe 2026-06-09). This invariant
withholds those fields at construction time, so no consumer (the /financials route,
Coverage, the AI orchestrator) can ever surface the garbage — the currency mismatch
reads as "withheld" rather than a wrong number. Single-currency snapshots (the
common case after the FX gate) are untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)

_NOW = datetime(2026, 6, 9, tzinfo=timezone.utc)


def _fd(*, reporting: str, quote: str, ev: float | None, pe: float | None) -> FinancialData:
    return FinancialData(
        ticker="TSM",
        timestamp=_NOW,
        income=IncomeStatement(revenue=4_113_789_591_000, ebitda=2_500_000_000_000),
        balance=BalanceSheet(total_debt=1_094_130_170_000, total_cash=3_382_860_143_000),
        market=MarketData(
            market_cap=2_213_589_664_000,
            shares_outstanding=5_186_000_000,
            current_price=427.0,
            pe_ratio=pe,
        ),
        valuation=ValuationMetrics(
            enterprise_value=ev,
            ev_ebitda=(ev / 2.5e12 if ev is not None else None),
            ev_ebitda_reported=(ev / 2.5e12 if ev is not None else None),
            ev_revenue=(ev / 4.11e12 if ev is not None else None),
        ),
        reporting_currency=reporting,
        quote_currency=quote,
    )


def test_cross_currency_withholds_ev_and_pe():
    """reporting≠quote with a (negative, mixed) EV → all EV-derived fields + P/E
    are nulled at construction, with a row warning and a per-field code."""
    fd = _fd(reporting="TWD", quote="USD", ev=-75_140_309_000, pe=12.0)
    assert fd.valuation.enterprise_value is None
    assert fd.valuation.ev_ebitda is None
    assert fd.valuation.ev_ebitda_reported is None
    assert fd.valuation.ev_revenue is None
    assert fd.market.pe_ratio is None
    assert any("withheld" in w.lower() for w in fd.warnings)
    assert "ev_cross_currency" in fd.field_warnings.get("ev_ebitda", [])


def test_single_currency_keeps_ev_and_pe():
    """reporting == quote (the common case after the canonical FX gate) → an exact
    no-op: EV, the multiples and P/E pass through, no warning added."""
    fd = _fd(reporting="USD", quote="USD", ev=2_140_000_000_000, pe=23.0)
    assert fd.valuation.enterprise_value == 2_140_000_000_000
    assert fd.valuation.ev_ebitda is not None
    assert fd.market.pe_ratio == 23.0
    assert not any("withheld" in w.lower() for w in fd.warnings)
    assert "ev_ebitda" not in fd.field_warnings


def test_cross_currency_with_already_none_ev_adds_no_warning():
    """A mixed snapshot that already lacks an EV (nothing to withhold) doesn't
    invent a warning — the invariant only fires when it actually nulls a value."""
    fd = _fd(reporting="TWD", quote="USD", ev=None, pe=None)
    assert fd.valuation.enterprise_value is None
    assert not any("withheld" in w.lower() for w in fd.warnings)
    assert "ev_ebitda" not in fd.field_warnings
