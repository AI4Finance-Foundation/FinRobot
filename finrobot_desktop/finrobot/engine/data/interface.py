from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from finrobot.engine.data.types import DataType


class DataResult(BaseModel):
    """Structured result from any data provider."""

    data: dict[str, Any]  # the actual financial data
    provider: str  # which provider returned this
    ticker: str
    data_type: str | DataType  # use DataType constants; str accepted for backwards-compat
    timestamp: datetime  # when this data was fetched
    warnings: list[str] = []  # e.g. "stale data from cache" — free-text, LLM-facing
    # STRUCTURED (not prose) sibling of warnings: KEY financials fields
    # (revenue / net_income) where two providers diverged beyond tolerance
    # (BUG-007). cross_validate also appends a human-readable warning, but this
    # list lets fetch_canonical stamp Provenance.degraded so dcf_seed / comps can
    # programmatically down-confidence the primary's number instead of parsing prose.
    key_field_divergences: list[str] = []
    # STRUCTURED sibling for PRICE cross-source discrepancies. ``fetch_price``
    # appends a free-text warning for humans and this list for canonical
    # provenance. Field names mirror the normalized price contract
    # (currently ``current_price``).
    price_field_divergences: list[str] = []
    # Providers that were in circuit-breaker cooldown and skipped for this fetch.
    # fetch_canonical translates these to Provenance.degraded markers so research
    # reports can surface which source was absent (parallel to key_field_divergences).
    circuit_open_providers: list[str] = []
    # True when this result is a STALE-CACHE FALLBACK (all providers failed/gated
    # and the layer served the last-known cached row). The canonical normalization
    # 关卡 reads this to refuse re-caching: re-writing a stale row as canonical would
    # bump its cached_at and flip is_stale back to False, laundering a stale price
    # into a "fresh"-reading quote (observed in-market 2026-06-08: a 95-min-old
    # close read as a live intraday quote with no warning). Stays False on every
    # genuine provider fetch — only the two stale-fallback returns set it.
    from_stale_cache: bool = False
    # True when the PRICE result's ``price_history`` bars were grafted from the
    # last cached row because the live provider served a quote WITHOUT history
    # (Finnhub free tier: /quote works, /stock/candle is premium-403). The
    # current_price stays live — only the bars are stale, so ``from_stale_cache``
    # (which means the WHOLE row is a cache fallback) would over-claim. The
    # canonical关卡 treats it like from_stale_cache for caching (refuses to
    # re-cache, keeping the prior bar-carrying row honestly stale so the next
    # read retries the recovered chain) and stamps a price_history_stale
    # degraded marker on the provenance.
    stale_history: bool = False

    def to_context_string(self) -> str:
        """Format data for LLM consumption. Human-readable, includes warnings."""
        lines = [
            f"[{self.provider}] {self.ticker} / {self.data_type} @ {self.timestamp.isoformat()}",
        ]
        for key, value in self.data.items():
            lines.append(f"  {key}: {value}")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        return "\n".join(lines)


class DataProvider(ABC):
    """Every data source implements this."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def capabilities(self) -> list[str | DataType]:
        """Returns list of data_types this provider supports."""

    @abstractmethod
    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult: ...

    @property
    def financials_fields(self) -> set[str]:
        """Fields this provider guarantees to include in financials DataResult.data.

        Used by DataLayer to warn when a provider doesn't cover a needed field.
        Default: empty (no guarantees). Override in subclasses.
        """
        return set()


class ProviderError(Exception):
    """Raised when a provider fails to fetch data."""


class RateLimitedProviderError(ProviderError):
    """A ProviderError that carries rate-limit semantics BY CONSTRUCTION.

    The PRIMARY rate-limit signal across the data layer. Raised in two places:

    1. Provider HTTP wrap points, whenever the upstream failure is structurally
       known to be throttling — an httpx 429 status (FMP / Finnhub / Adanos /
       SEC companyfacts / Alpha Vantage) or yfinance's typed
       ``YFRateLimitError``. ONLY 429 maps here: provider 4xx semantics differ
       (FMP 401 = invalid key, 403 = plan/legacy restriction — neither is
       throttling), so a blanket 4xx mapping would mis-classify auth/plan
       failures as transient.
    2. The data layer itself, where the failure is throttling-shaped and there
       is no wrapped upstream message to sniff — e.g. every capable provider
       sits in an open circuit-breaker cooldown, so no provider was even
       attempted.

    ``is_rate_limit_error`` recognises the type directly (no marker matching),
    so callers preserve stale values (QuoteCache cooldown) instead of
    tomb-stoning the ticker as delisted.
    """


class ProviderPlanError(ProviderError):
    """The key is VALID but the account's plan cannot use this endpoint.

    FMP answers HTTP 403 with a key-free "Exclusive Endpoint" / "Legacy
    Endpoint" body for endpoints outside the subscription tier (e.g. stock
    news / screener / transcripts on the free plan). This is a DETERMINISTIC
    capability gap, not provider ill-health: the data layer must fall through
    to the next provider WITHOUT charging the circuit breaker — otherwise a
    burst of plan-gated calls (3 consecutive) opens the breaker and blocks
    the endpoints the plan CAN serve (financials / profile / price).
    """


# Substrings that mark a provider failure as upstream rate-limiting (HTTP 429)
# rather than a bad ticker. FALLBACK ONLY: wrap points that see a structural 429
# (status code / typed library exception) raise RateLimitedProviderError, which
# is recognised by type before any marker is consulted. Message-sniffing remains
# for failure shapes no wrap point can type — Alpha Vantage's HTTP-200 body
# notes ("rate limit is 25 requests per day"), aggregate multi-source failure
# strings, and any legacy path still wrapping into a plain ProviderError. Union
# of every variant the data layer has seen ("throttl" from yfinance,
# "rate-limit"/"rate limit" from FMP/Finnhub, the bare "429" status) so the
# quote-batch fetcher and the ProviderHealth circuit-breaker classify the same
# 429 text identically.
_RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "429",
    "too many requests",
    "rate limit",
    "rate-limit",
    "throttl",
)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True iff ``exc`` looks like an upstream rate-limit (HTTP 429).

    Shared across the data layer: the quote-batch fetcher maps it to
    ``QuoteFetchRateLimited`` (preserve stale, open cooldown), and the
    ``ProviderHealth`` circuit-breaker uses the same classifier to decide when
    to trip a provider. A typed ``RateLimitedProviderError`` is the PRIMARY
    path — recognised structurally, independent of message wording, so an
    upstream rewording can't break classification. The marker scan is the
    fallback for failures no wrap point could type (HTTP-200 body notes,
    aggregate failure strings, third-party libraries without a typed
    rate-limit exception).
    """
    if isinstance(exc, RateLimitedProviderError):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)
