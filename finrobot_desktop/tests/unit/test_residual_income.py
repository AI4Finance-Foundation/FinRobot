"""Residual-income (justified-P/B) valuation — the bank's ROE-coherent anchor.

V = BVPS × [1 + (ROE − CoE)/(CoE − g)]. Single-stage Gordon residual income: a
bank is worth its book plus the present value of the excess return it earns over
its cost of equity. ROE-coherent (collapses the P/B-vs-P/E comps divergence that
mis-anchors PNC), buyback-invariant, and bearish-when-earned (ROE < CoE → below
book, the correct read for chronic underperformers like Citi). Validated against
the live reverse-derivation (PNC ~$275, CFG ~$47, JPM ~$310).
"""

from __future__ import annotations

import pytest
from finrobot.engine.compute.operators.residual_income import calculate_residual_income
from finrobot.engine.models.financial import DDMInputs

# CoE = rf + beta×ERP with the seed's macro defaults (rf 4.3%, ERP 4.2%): beta 1.0 → 8.5%.
_RF = 0.043
_ERP = 0.042


def _inputs(*, bvps: float, roe: float, beta: float, tg: float = 0.03) -> DDMInputs:
    return DDMInputs(
        dividend_per_share=1.0,  # unused by RI; DDMInputs requires a positive dividend
        dividend_growth_rates=[0.03] * 10,
        payout_ratio=0.45,
        risk_free_rate=_RF,
        beta=beta,
        equity_risk_premium=_ERP,
        terminal_growth_rate=tg,
        terminal_payout_ratio=None,
        shares_outstanding=1.0e9,
        current_price=100.0,
        book_value_per_share=bvps,
        return_on_equity=roe,
        assumption_provenance={},
    )


def test_pnc_shape_resolves_comps_divergence() -> None:
    # PNC live: BVPS 158.4, ROE 12.0%, CoE 8.2% (beta 0.929) → ~$274 (vs the bad
    # comps_pe anchor $193; in the sell-side 206–277 range).
    r = calculate_residual_income(_inputs(bvps=158.4, roe=0.12, beta=0.929))
    assert r.equity_value_per_share == pytest.approx(274.2, abs=1.0)
    assert r.cost_of_equity == pytest.approx(0.082, abs=0.001)
    assert r.excess_return == pytest.approx(0.038, abs=0.001)


def test_below_cost_of_capital_prices_below_book() -> None:
    # CFG: ROE 7.6% < CoE 8.6% → worth LESS than book (~0.82× = $47). The correct
    # bearish read; RI must not floor it at book.
    r = calculate_residual_income(_inputs(bvps=56.9, roe=0.076, beta=1.024))
    assert r.equity_value_per_share == pytest.approx(46.7, abs=1.0)
    assert r.equity_value_per_share < r.book_value_per_share
    assert r.excess_return < 0


def test_high_roe_does_not_blow_up_terminal() -> None:
    # JPM: ROE 16.3%, CoE 8.5% — terminal g (3%) keeps CoE−g well above the floor,
    # so a high excess return compounds to a finite ~$310 (NOT an exploding value).
    r = calculate_residual_income(_inputs(bvps=128.4, roe=0.163, beta=1.0))
    assert r.equity_value_per_share == pytest.approx(310.5, abs=2.0)


def test_roe_equals_coe_is_worth_book() -> None:
    r = calculate_residual_income(_inputs(bvps=50.0, roe=0.085, beta=1.0))
    assert r.equity_value_per_share == pytest.approx(50.0, abs=0.01)


def test_missing_roe_or_book_raises() -> None:
    with pytest.raises(ValueError):
        calculate_residual_income(
            _inputs(bvps=50.0, roe=0.10, beta=1.0).model_copy(update={"return_on_equity": None})
        )
    with pytest.raises(ValueError):
        calculate_residual_income(
            _inputs(bvps=50.0, roe=0.10, beta=1.0).model_copy(update={"book_value_per_share": None})
        )


def test_sub_floor_spread_raises() -> None:
    # A very low-beta payer can push CoE within a hair of the 5%-capped tg; the
    # CoE−g spread floor must refuse the blowup region (same guard as DDM/DCF).
    with pytest.raises(ValueError):
        calculate_residual_income(_inputs(bvps=50.0, roe=0.10, beta=0.30, tg=0.05))


def test_catastrophic_roe_withholds_not_negative() -> None:
    # ROE so far below CoE that book × (1 + neg) would go negative → refuse (no
    # negative equity value), same discipline as DDM implied-price ≤ 0.
    with pytest.raises(ValueError):
        calculate_residual_income(_inputs(bvps=50.0, roe=0.01, beta=1.2))
