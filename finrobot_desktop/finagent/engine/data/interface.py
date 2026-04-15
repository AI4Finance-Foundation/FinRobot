from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from finagent.engine.data.types import DataType


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
