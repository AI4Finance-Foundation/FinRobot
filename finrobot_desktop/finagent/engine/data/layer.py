import logging
from datetime import datetime, timezone
from typing import Any

from finagent.engine.data.cache import DataCache
from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.data.validator import cross_validate

logger = logging.getLogger(__name__)


class DataLayer:
    def __init__(self, providers: list[DataProvider], cache: DataCache) -> None:
        self._providers = providers
        self._cache = cache

    async def close(self) -> None:
        """Close the underlying cache connection.

        Safe to call multiple times. Exposed as a public method so SDK
        consumers can release resources via ``DataLayer.close()`` instead
        of reaching into ``_cache``.
        """
        await self._cache.close()

    async def fetch(self, data_type: str | DataType, ticker: str, **kwargs: Any) -> DataResult:
        """
        Flow:
        1. Check cache → if fresh, return
        2. Iterate all providers supporting this data_type (in priority order)
        3. For non-financials: first successful fetch → cache → return
           For financials: first success is kept, then a second provider is
           tried so ``cross_validate`` can flag discrepancies (15% revenue,
           5% market_cap, 10pp margin). Any warnings are appended to the
           primary result before it's cached and returned.
        4. All providers failed → return stale cache with warning
        5. No cache at all → return error DataResult
        """
        # 1. Fresh cache hit
        cached = await self._cache.get(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data

        # 2. Try each provider in order
        primary_result: DataResult | None = None
        secondary_count = 0
        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            try:
                result = await provider.fetch(ticker, data_type, **kwargs)
            except ProviderError as e:
                logger.warning(
                    f"Provider '{provider.name}' failed for {ticker}/{data_type}: {e}"
                )
                continue

            if primary_result is None:
                primary_result = result
                # For financials we keep looking so we can cross-validate the
                # numbers with a second provider. For every other data_type
                # (price, news, etc.) the first success is enough.
                if data_type == DataType.FINANCIALS:
                    continue
                break
            else:
                # Second provider succeeded → cross-validate numeric fields,
                # then merge: primary's own warnings + secondary's own
                # warnings + any new discrepancies. Dropping secondary's
                # warnings here would hide e.g. "FMP data delayed 15min"
                # from the user (P3 audit I4). Order is preserved while
                # de-duping so the same warning text isn't shown twice.
                discrepancies = cross_validate(primary_result, result)
                if discrepancies:
                    for w in discrepancies:
                        logger.warning(w)
                merged: list[str] = []
                seen: set[str] = set()
                for w in (
                    list(primary_result.warnings)
                    + list(result.warnings)
                    + discrepancies
                ):
                    if w in seen:
                        continue
                    seen.add(w)
                    merged.append(w)
                if merged != list(primary_result.warnings):
                    primary_result = primary_result.model_copy(
                        update={"warnings": merged}
                    )
                secondary_count += 1
                if data_type != DataType.FINANCIALS or secondary_count >= 2:
                    break

        if primary_result is not None:
            await self._cache.set(data_type, ticker, primary_result)
            return primary_result

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
        self, data_type: str | DataType, ticker: str, years: int = 5, **kwargs: Any
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
