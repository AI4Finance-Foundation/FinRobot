"""Recent-acquisition / large-secondary transition detection.

A just-closed stock-funded acquisition leaves the TTM snapshot mixing a post-deal
share count with mostly-pre-deal earnings → every per-share metric (DDM g, comps
EPS, ROE) is understated. The detector flags the share-count break so the synthesis
can degrade gracefully (withhold the poisoned point, hold the verdict neutral)
instead of shipping a spurious bearish call. Live-validated: FITB/HBAN read ~1.27×
their pre-deal baseline; every non-merger control reads ≤1.00×.
"""

from __future__ import annotations

from finrobot.engine.primitives.corporate_actions import detect_mna_transition


def test_stock_funded_merger_fires() -> None:
    # current shares 25% above the latest annual weighted-avg diluted baseline.
    assert detect_mna_transition(1000.0, [800.0], [1.0]) is True


def test_organic_company_silent() -> None:
    # current shares slightly BELOW baseline (no issuance) → not a transition.
    assert detect_mna_transition(950.0, [1000.0], [1.0]) is False


def test_heavy_buyback_silent() -> None:
    # buyback shrinks the share count below baseline → never fires (correct).
    assert detect_mna_transition(900.0, [1000.0], [1.0]) is False


def test_loss_year_skipped_for_baseline() -> None:
    # latest annual is a loss (eps<0); baseline must fall back to the prior
    # positive-eps year, not divide by a negative EPS.
    assert detect_mna_transition(1300.0, [1000.0, -50.0], [1.0, -0.05]) is True


def test_threshold_boundary() -> None:
    # 1.15× is the line: just under is organic, just over is a transition.
    assert detect_mna_transition(1149.0, [1000.0], [1.0]) is False
    assert detect_mna_transition(1151.0, [1000.0], [1.0]) is True


def test_no_baseline_or_shares_is_graceful() -> None:
    assert detect_mna_transition(1000.0, [], []) is False
    assert detect_mna_transition(None, [800.0], [1.0]) is False
    # all-loss history → no clean divisor → graceful False (no false gate).
    assert detect_mna_transition(2000.0, [-10.0], [-0.1]) is False


def test_fitb_live_shape() -> None:
    # FITB 2026-06 (Comerica): current 0.906B vs FY2025 implied 2.523B/3.54=0.713B.
    assert detect_mna_transition(0.906e9, [2.523e9], [3.54]) is True
    # JPM control: current 2.680B vs FY2025 57.048B/20.05=2.846B → 0.94× → silent.
    assert detect_mna_transition(2.680e9, [57.048e9], [20.05]) is False
