"""Pure-function tests for the ADR per-ordinary vs per-ADR DPS reconciliation
(``primitives.dividend``) — the single authority shared by the canonical FX normalize
(display DPS) and the DDM seed."""

from finrobot.engine.primitives.dividend import reconcile_per_share_dividend_to_quote_unit


def test_adr_mismatch_rederives_to_yield_times_price():
    # TSM shape: per-ordinary DPS $0.69 beside a per-ADR price $436 / yield 0.89%.
    dps, note = reconcile_per_share_dividend_to_quote_unit(0.69, 0.00892, 436.0)
    assert dps == 436.0 * 0.00892
    assert note is not None and "per-ADR-price" in note


def test_consistent_dps_passes_through_unchanged():
    # US shape: DPS $2.00, price $80, yield 2.5% — DPS/price == yield → no change.
    dps, note = reconcile_per_share_dividend_to_quote_unit(2.0, 0.025, 80.0)
    assert dps == 2.0
    assert note is None


def test_within_tolerance_not_reconciled():
    # DPS/price 2.4% vs yield 2.5% — within the abs/rel tolerance → left alone.
    dps, note = reconcile_per_share_dividend_to_quote_unit(1.92, 0.025, 80.0)
    assert dps == 1.92
    assert note is None


def test_missing_or_nonsensical_yield_passes_through():
    assert reconcile_per_share_dividend_to_quote_unit(0.69, None, 436.0) == (0.69, None)
    assert reconcile_per_share_dividend_to_quote_unit(0.69, 0.0, 436.0) == (0.69, None)
    assert reconcile_per_share_dividend_to_quote_unit(0.69, 1.5, 436.0) == (0.69, None)


def test_missing_price_or_dps_passes_through():
    assert reconcile_per_share_dividend_to_quote_unit(0.69, 0.02, None) == (0.69, None)
    assert reconcile_per_share_dividend_to_quote_unit(0.69, 0.02, 0.0) == (0.69, None)
    # No DPS to reconcile against → nothing to do (yield-only DDM path handles it).
    assert reconcile_per_share_dividend_to_quote_unit(None, 0.02, 100.0) == (None, None)
