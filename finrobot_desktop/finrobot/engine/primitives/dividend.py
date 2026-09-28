"""Dividend caliber helpers (pure, zero-I/O).

Lives in ``primitives/`` so BOTH the data layer (canonical FX normalize, which
fixes the DISPLAYED per-share DPS) and the compute layer (the DDM seed) share ONE
authority for the ADR per-share/per-ADR reconciliation — otherwise the two drift
(the DDM had the guard; the display did not, so a non-bank ADR like TSM showed a
per-ordinary-share DPS beside a per-ADR price/yield).
"""

from __future__ import annotations

from typing import Final

# An ADR's provider per-share DPS (FMP ``dividendPerShareTTM``) is per-ORDINARY-share
# in the reporting currency, while ``current_price`` is per-ADR in the quote currency
# (a 1:N ADR ratio the per-share field misses but the dimensionless ``dividend_yield``
# carries). So DPS/price implies a yield that disagrees with the provider's own
# ``dividend_yield``. Live-verified: TSM per-ordinary DPS ≈ $0.69 (22 TWD ÷ FX) vs
# yield 0.89% × per-ADR price ≈ $3.8 (the two differ by the ADR ratio); LYG DPS/price
# implied 0.64% vs provider yield 3.35% (2026-06-24, Bug-3).
_ADR_YIELD_DISAGREE_ABS: Final[float] = 0.005  # 0.5pp absolute
_ADR_YIELD_DISAGREE_REL: Final[float] = 0.25  # or 25% relative


def reconcile_per_share_dividend_to_quote_unit(
    dividend_per_share: float | None,
    dividend_yield: float | None,
    current_price: float | None,
) -> tuple[float | None, str | None]:
    """Return ``(dps, note)`` — a per-quote-unit (per-ADR) DPS consistent with the
    per-ADR price and the dimensionless dividend yield.

    When the provider per-share DPS implies a yield that materially disagrees with the
    provider's own ``dividend_yield`` (the per-ordinary vs per-ADR caliber mismatch),
    the DPS is re-derived as ``dividend_yield × current_price`` — the caliber-consistent
    figure, with no double-FX (yield is dimensionless, price is the quote-currency
    per-ADR price). This is 勾稽, not fabrication: two authoritative per-ADR fields
    (yield, price) reconcile a third that the provider reported on the wrong unit.

    Returns the input DPS unchanged (note ``None``) when there is nothing to reconcile:
    no yield, a nonsensical yield (≤0 or ≥100%), no positive price, or the implied and
    reported yields already agree within tolerance (every US issuer — same unit both
    sides — and any ADR whose provider happened to report a per-ADR DPS).
    """
    if (
        dividend_yield is None
        or not (0 < dividend_yield < 1)
        or current_price is None
        or current_price <= 0
    ):
        return dividend_per_share, None
    implied_yield = (
        dividend_per_share / current_price
        if (dividend_per_share is not None and dividend_per_share > 0)
        else None
    )
    if implied_yield is None:
        return dividend_per_share, None
    tol = max(_ADR_YIELD_DISAGREE_ABS, _ADR_YIELD_DISAGREE_REL * dividend_yield)
    if abs(implied_yield - dividend_yield) <= tol:
        return dividend_per_share, None
    reconciled = dividend_yield * current_price
    note = (
        f"dividend_per_share re-derived to the quote unit: dividend_yield "
        f"{dividend_yield:.2%} × price {current_price:.2f} = {reconciled:.2f} "
        f"(the provider per-share DPS implied a {implied_yield:.2%} yield — a "
        f"per-ordinary-share vs per-ADR-price caliber mismatch)"
    )
    return reconciled, note
