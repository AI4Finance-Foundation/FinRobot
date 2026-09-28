"""Book-value-per-share caliber helper (pure, zero-I/O).

Lives in ``primitives/`` so every consumer of the per-share book value shares ONE
authority for the ADR/multi-class per-share reconciliation — the display snapshot
(``extract_financial_data``), the comps anchor (``extract_company_financials`` /
``build_xbrl_aligned_company`` via the target's FinancialData), and the DDM /
residual-income seed (``ddm``). Otherwise they drift the way the DPS caliber did
before the dividend primitive (see ``primitives/dividend``).
"""

from __future__ import annotations

from typing import Final

# Relative gap above which the provider's reported share count is treated as NOT on
# the quoted price's basis (an ADR whose provider count is the ordinary-share basis,
# a multi-class issuer with one class reported, or stale data), so the
# market_cap/price-implied count is used for per-share calibers instead. 10% clears
# normal timestamp drift between the financials and price fetches while catching the
# ~2× single-vs-all-class and N× ADR-ratio mismatches. This is the SAME constant the
# extractor's share-count reconciliation uses — book value per share must move onto
# the price basis in lockstep with the reconciled share count and EPS. Mirrors the
# validator's 0.9–1.1 closing band (engine/data/validator.market_cap_consistency).
SHARES_PRICE_CONSISTENCY_TOL: Final[float] = 0.10


def reconcile_book_value_to_price_basis(
    book_value_per_share: float | None,
    reported_shares: float | None,
    market_cap: float | None,
    current_price: float | None,
    tol: float = SHARES_PRICE_CONSISTENCY_TOL,
) -> tuple[float | None, str | None]:
    """Return ``(bvps, note)`` — book value per share on the quoted price's basis
    (per-ADR), consistent with the price it will be multiplied against.

    The provider divides book equity by its reported share count: ``bvps =
    book_equity / reported_shares``. For US issuers (and any ADR whose provider
    count already sits on the quoted basis) ``reported_shares ==
    market_cap/current_price``, so this is a no-op — the input is returned
    unchanged (byte-identical). But an ADR whose provider count is the
    ordinary-share basis carries a bvps mis-scaled by the ADR ratio: BP's FMP
    ``/shares-float`` count (~437M) is 1/6 of the market_cap/price-implied ADR
    count (~2.62B), so the reported bvps (~$128) is ~6× the per-ADR figure
    (~$21, matching stockanalysis' $21.43). Rescaling by
    ``reported_shares / implied_shares`` re-expresses it as ``book_equity /
    implied_shares`` — book equity is conserved (勾稽, not fabrication), and the
    result lands on the SAME per-ADR basis as ``current_price`` and the reconciled
    per-ADR EPS, so ``comps_pb = peer_median_pb × bvps`` no longer prints a
    6×-inflated implied price.

    No-op (input returned, note ``None``) when there is nothing to reconcile:
    missing/non-positive bvps; missing/non-positive reported_shares (the provider
    then already derived bvps from market_cap/price — already on the price basis);
    no positive market_cap or price; or reported and implied share counts already
    agree within ``tol`` (every US issuer and any already-price-consistent ADR).
    """
    if book_value_per_share is None or book_value_per_share <= 0:
        return book_value_per_share, None
    if not reported_shares or reported_shares <= 0:
        return book_value_per_share, None
    if not market_cap or market_cap <= 0 or not current_price or current_price <= 0:
        return book_value_per_share, None
    implied_shares = market_cap / current_price
    if implied_shares <= 0:
        return book_value_per_share, None
    if abs(reported_shares - implied_shares) / implied_shares <= tol:
        return book_value_per_share, None
    reconciled = book_value_per_share * reported_shares / implied_shares
    note = (
        f"book_value_per_share re-derived to the quoted price (per-ADR) basis: the "
        f"reported share count {reported_shares:,.0f} diverges from the market_cap/"
        f"price-implied {implied_shares:,.0f} (ADR ratio / multi-class single class), "
        f"so bvps was rescaled {book_value_per_share:.2f} → {reconciled:.2f} "
        f"(book equity ÷ price-consistent shares)"
    )
    return reconciled, note
