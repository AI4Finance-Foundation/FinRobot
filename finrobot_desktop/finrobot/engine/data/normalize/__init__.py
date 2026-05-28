"""Provider-output normalization layer.

Sits between raw providers and cache/compute. Providers return best-effort
untyped dicts; this layer presses them into typed canonical results
(``NormalizedPrice`` / ``NormalizedFinancials``) with first-class provenance,
currency, freshness, and degradation markers. See ADR-0004.
"""

from finrobot.engine.data.normalize.contracts import (
    NormalizedFinancials,
    NormalizedPrice,
    PriceBar,
    Provenance,
)
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price

__all__ = [
    "NormalizedFinancials",
    "NormalizedPrice",
    "PriceBar",
    "Provenance",
    "normalize_financials",
    "normalize_price",
]
