"""Residual-income (justified-P/B) valuation — the bank's ROE-coherent anchor.

A bank's intrinsic value is its book value plus the present value of the excess
return it earns over its cost of equity:

    V = BVPS × [1 + (ROE − CoE)/(CoE − g)]   (single-stage Gordon residual income)

This is the textbook justified price-to-book — the standard intrinsic anchor for a
deposit-funded balance sheet (Damodaran, "Investment Valuation" 3rd Ed. Ch. 19;
CFA RI framework), NOT a retail simplification. It is preferred over the DDM as the
bank anchor for three reasons the live basket forced:

1. **ROE-coherent.** Comps value book (P/B) and earnings (P/E) independently, so a
   bank whose ROE differs from its peers' looks cheap-on-book and dear-on-earnings
   at once — the two rows diverge and the dial anchors whichever is lower (PNC:
   comps_pb $303 vs comps_pe $193, anchored the low $193). RI collapses book,
   earnings and ROE into one number (PNC → ~$275, in the sell-side range).
2. **Buyback-invariant.** It anchors on hard book value and the ROE spread, not a
   projected dividend, so it does not under-price a bank that returns capital via
   buybacks the way a dividend-only DDM does (BAC).
3. **Bearish when earned.** ROE < CoE → value below book — the correct, defensible
   read for a chronic underperformer (Citi at ROE ~7.4% < CoE ~8.9%), not an
   artifact to paper over to consensus.

The terminal growth ``g`` is the long-run nominal-GDP rate (≈3%), NOT the
sustainable book-growth ROE×(1−payout): a high-ROE bank's near-term book growth can
exceed CoE, which would make (CoE − g) ≤ 0 and explode the perpetuity. Anchoring g
at the macro terminal keeps the spread positive and the value finite (a mild,
deliberate conservatism on high-ROE names, which are already well-anchored by the
corroborating methods).
"""

from __future__ import annotations

from finrobot.engine.models.financial import DDMInputs, RIResult
from finrobot.engine.models.valuation_thresholds import MIN_GORDON_SPREAD


def _ri_value(bvps: float, roe: float, cost_of_equity: float, g: float) -> float:
    """Justified-P/B value at one ROE, or NaN if the franchise is worth ≤ 0 (ROE so
    far below CoE that book × (1 + spread) goes negative — refuse, never emit a
    negative per-share value, symmetric with the DDM implied-price ≤ 0 guard)."""
    v = bvps * (1 + (roe - cost_of_equity) / (cost_of_equity - g))
    return v if v > 0 else float("nan")


def calculate_residual_income(inputs: DDMInputs, *, forward_roe: float | None = None) -> RIResult:
    """Single-stage Gordon residual income (justified-P/B) from CAPM + book + ROE.

    Reuses ``DDMInputs`` — it already carries book_value_per_share, return_on_equity
    and the CAPM trio (rf / beta / ERP) the bank DDM seed minted, so RI needs no new
    seed; cost of equity is computed identically (same beta the DDM and DCF use).

    ``equity_value_per_share`` is RI at the TRAILING ROE — the independent low end (our
    own realized return). When ``forward_roe`` (the FY1 consensus ROE) is supplied,
    ``forward_value`` is RI at that ROE — the recovery high end. The two bracket the
    trough→normalized uncertainty; the synthesis rates price-vs-band, never extrapolating
    a single perpetuity ROE to a confident point. A cyclical metric at one point in the
    cycle is not the perpetuity value, so we refuse to give one — the band IS that refusal.

    Raises:
        ValueError: ROE or book value per share missing; CoE−g below the Gordon
            spread floor (perpetuity blowup region, shared with DDM/DCF); or the
            TRAILING value ≤ 0 (ROE so far below CoE that book × (1 + spread) goes
            negative). A degenerate forward end is left as None (the trailing band
            still stands), not raised.
    """
    if inputs.return_on_equity is None:
        raise ValueError("Residual income requires return_on_equity (None supplied).")
    bvps = inputs.book_value_per_share
    if bvps is None or bvps <= 0:
        raise ValueError(
            "Residual income requires a positive book_value_per_share "
            f"(got {bvps}); use relative valuation instead."
        )

    cost_of_equity = inputs.risk_free_rate + inputs.beta * inputs.equity_risk_premium
    g = inputs.terminal_growth_rate
    if cost_of_equity - g < MIN_GORDON_SPREAD:
        # Same forward-Gordon floor as the DDM/DCF: a sub-floor spread puts a 200×+
        # multiplier on the excess return — a blowup, not a valuation.
        raise ValueError(
            f"CoE−terminal growth spread {cost_of_equity - g:.2%} is below the "
            f"{MIN_GORDON_SPREAD:.1%} minimum — residual income is not applicable; "
            "use relative valuation instead."
        )

    excess_return = inputs.return_on_equity - cost_of_equity
    justified_pb = 1 + excess_return / (cost_of_equity - g)
    equity_value_per_share = bvps * justified_pb
    if equity_value_per_share <= 0:
        raise ValueError(
            f"Residual income value ${equity_value_per_share:.2f} ≤ 0 (ROE "
            f"{inputs.return_on_equity:.1%} far below CoE {cost_of_equity:.1%}); "
            "use relative valuation instead."
        )

    forward_value: float | None = None
    if forward_roe is not None:
        fv = _ri_value(bvps, forward_roe, cost_of_equity, g)
        forward_value = fv if fv == fv else None  # drop a degenerate (NaN) forward end

    return RIResult(
        cost_of_equity=cost_of_equity,
        book_value_per_share=bvps,
        return_on_equity=inputs.return_on_equity,
        excess_return=excess_return,
        terminal_growth_rate=g,
        justified_pb=justified_pb,
        equity_value_per_share=equity_value_per_share,
        forward_return_on_equity=forward_roe,
        forward_value=forward_value,
        inputs=inputs,
    )
