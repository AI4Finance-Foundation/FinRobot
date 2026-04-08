import logging
from datetime import datetime, timezone

from finagent.engine.data.cache import DataCache
from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.types import DataType

logger = logging.getLogger(__name__)


class DataLayer:
    def __init__(self, providers: list[DataProvider], cache: DataCache) -> None:
        self._providers = providers
        self._cache = cache

    async def fetch(self, data_type: str | DataType, ticker: str, **kwargs) -> DataResult:
        """
        Flow:
        1. Check cache → if fresh, return
        2. Iterate all providers supporting this data_type (in priority order)
        3. First successful fetch → cache → return
        4. All providers failed → return stale cache with warning
        5. No cache at all → return error DataResult
        """
        # 1. Fresh cache hit
        cached = await self._cache.get(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data

        # 2. Try each provider in order
        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            try:
                result = await provider.fetch(ticker, data_type, **kwargs)
                await self._cache.set(data_type, ticker, result)
                return result
            except ProviderError as e:
                logger.warning(f"Provider '{provider.name}' failed for {ticker}/{data_type}: {e}")
                continue

        # 3. All providers failed — return stale cache with PROMINENT warning
        if cached is not None:
            stale = cached.data
            age_hours = (
                datetime.now(tz=timezone.utc) - cached.cached_at
            ).total_seconds() / 3600
            stale_warning = (
                f"WARNING: Using stale cached data ({age_hours:.0f}h old). "
                f"All live providers failed for {ticker}/{data_type}. "
                f"Financial figures may be outdated — verify before acting on this data."
            )
            logger.warning(stale_warning)
            return stale.model_copy(
                update={"warnings": [stale_warning] + stale.warnings}
            )

        # 4. No data anywhere
        msg = (
            f"Data unavailable for {ticker}/{data_type}: all providers failed and no cache exists."
        )
        logger.error(msg)
        return DataResult(
            data={"error": msg},
            provider="none",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[msg],
        )

    async def fetch_historical(
        self, data_type: str | DataType, ticker: str, years: int = 5, **kwargs
    ) -> list[DataResult]:
        """Fetch multi-year historical data.

        What this code does that raw LLM cannot: deterministic provider chain
        fallback for historical data — iterates providers in priority order,
        passes years kwarg, splits single DataResult into list[DataResult].

        Provider.fetch() always returns DataResult (interface unchanged).
        When years kwarg is passed, providers pack multi-year data inside
        DataResult.data["yearly_data"]. This method splits it into a list.
        """
        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            try:
                result = await provider.fetch(ticker, data_type, years=years, **kwargs)
                return self._split_yearly(result)
            except ProviderError as e:
                logger.warning(
                    f"Provider '{provider.name}' failed for {ticker}/{data_type} "
                    f"(historical, {years}y): {e}"
                )
                continue

        msg = f"Historical data unavailable for {ticker}/{data_type}: all providers failed."
        logger.error(msg)
        return []

    @staticmethod
    def _split_yearly(result: DataResult) -> list[DataResult]:
        """Split a DataResult with yearly_data into list[DataResult].

        If the result has no yearly_data key, return as single-element list.
        """
        yearly = result.data.get("yearly_data")
        if not yearly or not isinstance(yearly, list):
            return [result]

        return [
            DataResult(
                data=year_data,
                provider=result.provider,
                ticker=result.ticker,
                data_type=result.data_type,
                timestamp=result.timestamp,
                warnings=result.warnings,
            )
            for year_data in yearly
        ]
