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
    warnings: list[str] = []  # e.g. "stale data from cache"

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


# Substrings that mark a provider failure as upstream rate-limiting (HTTP 429)
# rather than a bad ticker. Providers wrap the upstream error into ProviderError,
# so message-sniffing is the reliable cross-provider signal.
_RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "429",
    "too many requests",
    "rate limit",
    "rate-limit",
)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True iff ``exc`` looks like an upstream rate-limit (HTTP 429).

    Shared across the data layer: the quote-batch fetcher maps it to
    ``QuoteFetchRateLimited`` (preserve stale, open cooldown), and 批3's
    ProviderHealth circuit-breaker will use the same classifier to decide when
    to trip a provider. Message-based so it works on a wrapped ``ProviderError``
    regardless of the originating provider/library.
    """
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)
