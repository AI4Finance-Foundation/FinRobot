"""unlever_beta must not crash / sign-flip on a deeply net-cash firm
(W3-B路 · degenerate-state + sign contract).

Hamada: β_U = β_L / [1 + (1−T)·(D/E)]. A net-cash firm has D/E < 0; at
D/E = −1/(1−T) the denominator is exactly 0 (ZeroDivisionError), and below that
it goes negative — flipping a POSITIVE levered beta to a NEGATIVE unlevered beta,
violating the function's own "always positive if levered_beta > 0" contract. Used
inside peer_beta, a single such peer crashes the whole WACC → DCF. When the
denominator is ≤ 0 there is no meaningful leverage to strip, so the asset beta ≈
the equity beta: return the levered beta unchanged.
"""

from __future__ import annotations

import math

import pytest

from finrobot.engine.compute.operators.wacc import peer_beta, unlever_beta


def test_unlever_beta_zero_denominator_no_crash() -> None:
    # D/E = −1/(1−T) → denominator exactly 0 → would ZeroDivisionError.
    de = -1.0 / (1 - 0.21)
    assert unlever_beta(1.2, 0.21, de) == 1.2


def test_unlever_beta_negative_denominator_no_sign_flip() -> None:
    # D/E very negative → denominator < 0 → would flip a positive beta negative.
    result = unlever_beta(1.2, 0.21, -2.0)
    assert result > 0
    assert result == 1.2


def test_unlever_beta_normal_unchanged() -> None:
    assert unlever_beta(1.2, 0.21, 0.5) == pytest.approx(1.2 / (1 + 0.79 * 0.5))


def test_peer_beta_survives_net_cash_peer() -> None:
    # The middle peer is extreme net-cash; the median must still compute.
    result = peer_beta(
        peer_betas=[1.0, 1.2, 1.1],
        peer_tax_rates=[0.21, 0.21, 0.21],
        peer_debt_equity=[0.5, -2.0, 0.3],
        target_tax_rate=0.21,
        target_debt_equity=0.4,
    )
    assert result > 0 and math.isfinite(result)
