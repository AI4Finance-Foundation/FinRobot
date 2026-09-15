"""forward_estimates.get_forward_revenue_growth — FY1-N forward YoY growth path.

Feeds the DCF stage-1 growth seed so the model stops projecting trailing CAGR
(backward-looking) when analyst consensus expects a different trajectory. Far-out
rows are dropped (FMP consensus past ~3y is sparse/noisy); empty list = caller
falls back to trailing-CAGR seeding.
"""

from __future__ import annotations

from datetime import date

from finrobot.engine.compute.operators.forward_estimates import get_forward_revenue_growth

AS_OF = date(2026, 6, 9)


def _rows(*pairs: tuple[str, float]) -> dict[str, list[dict[str, object]]]:
    return {"rows": [{"date": d, "revenueAvg": r} for d, r in pairs]}


# AAPL-shaped consensus: FY25 actual then FY26-28 estimates (fiscal year ends Sep).
_AAPL = _rows(
    ("2025-09-27", 415.4e9),
    ("2026-09-27", 477.5e9),
    ("2027-09-27", 517.5e9),
    ("2028-09-27", 554.1e9),
)


def test_returns_fy1_to_fy3_yoy_from_consensus() -> None:
    g = get_forward_revenue_growth(_AAPL, as_of=AS_OF, max_years=3)
    assert len(g) == 3
    assert abs(g[0] - (477.5 / 415.4 - 1)) < 1e-6
    assert abs(g[1] - (517.5 / 477.5 - 1)) < 1e-6
    assert abs(g[2] - (554.1 / 517.5 - 1)) < 1e-6


def test_empty_when_no_estimates() -> None:
    assert get_forward_revenue_growth(None, as_of=AS_OF) == []
    assert get_forward_revenue_growth({"rows": []}, as_of=AS_OF) == []


def test_drops_far_out_noise_beyond_max_years() -> None:
    rows = _rows(
        ("2025-09-27", 415.4e9),
        ("2026-09-27", 477.5e9),
        ("2027-09-27", 517.5e9),
        ("2028-09-27", 554.1e9),
        ("2029-09-27", 483.1e9),  # non-monotonic noise
        ("2030-09-27", 648.9e9),
    )
    assert len(get_forward_revenue_growth(rows, as_of=AS_OF, max_years=3)) == 3


def test_empty_when_no_past_actual_base() -> None:
    # All rows are future → no actual base to anchor FY1 growth → fall back.
    rows = _rows(("2026-09-27", 477.5e9), ("2027-09-27", 517.5e9))
    assert get_forward_revenue_growth(rows, as_of=AS_OF) == []
