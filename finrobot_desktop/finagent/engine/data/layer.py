import logging

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
        2. Find provider that supports this data_type
        3. Try fetch → success → cache → return
        4. If fails → try fallback provider
        5. If all fail → return stale cache with warning
        6. If no cache at all → raise ProviderError
        """
        # 1. Fresh cache hit
        cached = await self._cache.get(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data

        # 2. Select primary provider
        primary = self._select_provider(data_type)
        if primary is not None:
            try:
                result = await primary.fetch(ticker, data_type, **kwargs)
                await self._cache.set(data_type, ticker, result)
                return result
            except ProviderError as e:
                logger.warning(f"Primary provider '{primary.name}' failed for {ticker}/{data_type}: {e}")

        # 4. Fallback provider (different from primary)
        fallback = self._select_fallback(data_type, exclude=primary)
        if fallback is not None:
            try:
                result = await fallback.fetch(ticker, data_type, **kwargs)
                await self._cache.set(data_type, ticker, result)
                return result
            except ProviderError as e:
                logger.warning(f"Fallback provider '{fallback.name}' failed for {ticker}/{data_type}: {e}")

        # 5. All providers failed — return stale cache with warning if available
        if cached is not None:
            stale = cached.data
            stale_copy = stale.model_copy(
                update={"warnings": stale.warnings + ["stale data: all providers failed"]}
            )
            return stale_copy

        # 6. No data anywhere
        raise ProviderError(
            f"No data available for {ticker}/{data_type}: all providers failed and no cache exists."
        )

    def _select_provider(self, data_type: str) -> DataProvider | None:
        for p in self._providers:
            if data_type in p.capabilities():
                return p
        return None

    def _select_fallback(self, data_type: str, exclude: DataProvider | None) -> DataProvider | None:
        for p in self._providers:
            if p is exclude:
                continue
            if data_type in p.capabilities():
                return p
        return None
