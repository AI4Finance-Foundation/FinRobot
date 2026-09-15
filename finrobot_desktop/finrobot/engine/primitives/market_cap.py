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

import math


def _valid_cap(cap: float | None) -> float | None:
    """A market cap is valid only if finite and strictly positive.

    A negative / NaN / Inf / zero cap is data corruption, not a real cap — return
    None rather than letting it through (the module's "never a wrong number"
    contract). Used on every return path so neither a corrupt cached cap nor a
    non-finite live price can mint a junk cap.
    """
    return cap if (cap is not None and math.isfinite(cap) and cap > 0) else None


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
    valid_cached = _valid_cap(cached_market_cap)
    # NaN/Inf live_price passes ``<= 0`` (both comparisons are False for NaN), so
    # finiteness is checked explicitly — an unusable live price returns the cached
    # cap, never a non-finite mark-to value.
    if live_price is None or not math.isfinite(live_price) or live_price <= 0:
        return valid_cached
    shares = cached_shares
    if shares is None or not math.isfinite(shares) or shares <= 0:
        # Derive shares from the snapshot's own cap/price basis only when the cap
        # is a valid positive number — else a negative/NaN cached cap would mint a
        # negative/NaN share count and a junk live cap.
        if (
            valid_cached is not None
            and cached_price is not None
            and math.isfinite(cached_price)
            and cached_price > 0
        ):
            shares = valid_cached / cached_price
        else:
            return valid_cached
    return _valid_cap(shares * live_price)
