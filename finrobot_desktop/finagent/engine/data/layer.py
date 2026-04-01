import logging
from datetime import datetime, timezone

from finagent.engine.data.cache import DataCache
from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

logger = logging.getLogger(__name__)


class DataLayer:
    def __init__(self, providers: list[DataProvider], cache: DataCache) -> None:
        self._providers = providers
        self._cache = cache

    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
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

        # 3. All providers failed — return stale cache with warning if available
        if cached is not None:
            stale = cached.data
            return stale.model_copy(
                update={"warnings": stale.warnings + ["stale data: all providers failed"]}
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
