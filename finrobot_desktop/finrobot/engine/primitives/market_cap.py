"""Mark a cached market cap to a live price — zero-I/O primitive.

A provider's ``market_cap`` rides the snapshot's own quote price, which can lag the
live ``current_price`` shown beside it (the FMP profile ``mktCap`` froze at the
prior close while the quote moved). Grafting that absolute cap onto a payload
carrying a fresher live price splices two price epochs: ``market_cap /
current_price`` then ≠ the true share count — the AAPL/MU/NVDA ``/price``-vs-
``/financials`` disagreement (probe 2026-06-09). Any surface that shows a cap next
to a price must recompute the cap from a price-consistent share count so
``market_cap == shares × current_price`` holds at that one instant.

Lives in ``primitives`` (zero I/O) so both the ``/price`` route and the
``extract_financial_data`` compute path can mark to live price through one rule
instead of each re-deriving it (and drifting apart again).
"""

from __future__ import annotations


def market_cap_on_live_price(
    *,
    cached_market_cap: float | None,
    cached_shares: float | None,
    cached_price: float | None,
    live_price: float | None,
) -> float | None:
    """Return ``market_cap`` marked to ``live_price`` (= ``shares × live_price``).

    Share count priority: the reported ``cached_shares``; else derived from
    ``cached_market_cap / cached_price`` (the snapshot's own price basis). When no
    usable ``live_price`` is supplied the cached cap is returned unchanged (there is
    nothing to mark to); when neither a share count nor a usable cap/price pair
    exists, the cached cap (possibly ``None``) is returned rather than fabricating
    one — a missing cap stays missing, never a wrong number.
    """
    if live_price is None or live_price <= 0:
        return cached_market_cap
    shares = cached_shares
    if shares is None or shares <= 0:
        if cached_market_cap is not None and cached_price is not None and cached_price > 0:
            shares = cached_market_cap / cached_price
        else:
            return cached_market_cap
    return shares * live_price
