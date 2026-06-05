import logging
from datetime import datetime, timezone
from typing import Any, Literal, overload

from finrobot.engine.data.cache import DataCache, cached_fetch
from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.provider_health import ProviderHealth
from finrobot.engine.data.normalize import (
    NormalizedFinancials,
    NormalizedPrice,
    PriceBar,
    normalize_financials,
    normalize_price,
)
from finrobot.engine.data.types import DataType
from finrobot.engine.data.normalize.contracts import (
    degraded_circuit_open,
    degraded_provider_divergence,
)
from finrobot.engine.data.validator import (
    cross_validate,
    cross_validate_price,
    key_field_divergences,
    market_cap_consistency,
)

logger = logging.getLogger(__name__)


class DataLayer:
    def __init__(
        self,
        providers: list[DataProvider],
        cache: DataCache,
        health: ProviderHealth | None = None,
    ) -> None:
        self._providers = providers
        self._cache = cache
        # Per-provider circuit breaker (BUG-045). A provider that rate-limits
        # us or fails repeatedly enters a cooldown window; every provider loop
        # below skips it via ``is_available`` for the duration so a slow/429
        # provider stops costing the full _TIMEOUT on each subsequent call.
        # Shared across all fetch_* methods so a trip in one path protects them
        # all. Defaults to a fresh breaker; injectable for tests.
        self._health = health if health is not None else ProviderHealth()

    def _health_gated(self, provider: DataProvider) -> bool:
        """True if ``provider`` is in an open cooldown window and should be skipped.

        Logs once at skip-time so a tripped provider is visible in logs without
        being silently absent from the chain.
        """
        if self._health.is_available(provider.name):
            return False
        logger.info("Provider '%s' in cooldown (circuit open) — skipping", provider.name)
        return True

    @property
    def cache(self) -> DataCache:
        """Public accessor for the shared SQLite cache.

        Route handlers that bypass the provider chain (e.g. /price, /historical,
        /quarterly — yfinance-only deep data) use this with ``cached_fetch``
        to participate in the same caching layer as Provider-backed data.
        """
        return self._cache

    async def close(self) -> None:
        """Close the underlying cache and any provider-owned resources.

        Providers with shared httpx.AsyncClient instances expose a
        ``close()`` coroutine — call it here so TCP/TLS sessions and
        connection pools shut down cleanly during lifespan teardown.
        Safe to call multiple times.
        """
        for provider in self._providers:
            close_fn = getattr(provider, "close", None)
            if callable(close_fn):
                import inspect

                try:
                    result = close_fn()
                    if inspect.iscoroutine(result):
                        await result
                except (OSError, RuntimeError) as exc:
                    # Best-effort cleanup — connection-level errors during
                    # shutdown shouldn't mask the more important cache close
                    # below. Concrete types only (CLAUDE.md / P3 D1 red-line).
                    logger.warning("Provider %s close() failed: %s", provider.name, exc)
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
        # I7: normalise to DataType enum so all downstream comparisons and
        # cache keys use the canonical enum value, not a raw string literal.
        data_type = DataType(data_type)

        # 1. Fresh cache hit — raw slot; staleness is by TTL only. Canonical
        # slots use version-tagged keys (ADR-0006 C1) that auto-invalidate on
        # schema bumps, so a fresh hit needs no contract-shape check.
        cached = await self._cache.get(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data

        # 2. Try each provider in order
        primary_result: DataResult | None = None
        secondary_count = 0
        circuit_open: list[str] = []
        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            if self._health_gated(provider):
                circuit_open.append(provider.name)
                continue
            try:
                result = await provider.fetch(ticker, data_type, **kwargs)
            except ProviderError as e:
                self._health.record_failure(provider.name, rate_limited=is_rate_limit_error(e))
                logger.warning(f"Provider '{provider.name}' failed for {ticker}/{data_type}: {e}")
                continue
            self._health.record_success(provider.name)

            if primary_result is None:
                primary_result = result
                # For financials we keep looking so we can cross-validate the
                # numbers with a second provider. For every other data_type
                # (price, news, etc.) the first success is enough.
                if data_type == DataType.FINANCIALS:
                    continue
                break
            else:
                # D5: skip empty secondary, add warning, try next provider
                if not result.data:
                    empty_warn = (
                        f"Secondary provider {provider.name} returned empty data "
                        f"— cross-validation skipped"
                    )
                    logger.warning(empty_warn)
                    if empty_warn not in primary_result.warnings:
                        updated_warns = list(primary_result.warnings) + [empty_warn]
                        primary_result = primary_result.model_copy(
                            update={"warnings": updated_warns}
                        )
                    # Don't count toward secondary_count — keep trying
                    continue

                # Second provider succeeded → cross-validate numeric fields,
                # then merge: primary's own warnings + secondary's own
                # warnings + any new discrepancies. Dropping secondary's
                # warnings here would hide e.g. "FMP data delayed 15min"
                # from the user (P3 audit I4). dict.fromkeys preserves
                # insertion order while de-duping so the same warning text
                # isn't shown twice.
                discrepancies = cross_validate(primary_result, result)
                # Lineage-aware market_cap ≈ price × shares check. Skipped inside
                # when the only share count is FMP's rederived mc/price (a False
                # Validation); fires a share-structure WARNING for multi-class /
                # ADR / unit mismatches (e.g. GOOG/META) without hardcoding names.
                discrepancies += market_cap_consistency(primary_result, result)
                for w in discrepancies:
                    logger.warning(w)
                merged = list(
                    dict.fromkeys([*primary_result.warnings, *result.warnings, *discrepancies])
                )
                # BUG-007: in ADDITION to the prose warnings, carry a STRUCTURED
                # list of KEY fields (revenue / net_income) the two providers
                # disagree on, so fetch_canonical can stamp Provenance.degraded.
                # The primary value still wins and flows — this only flags it.
                merged_divergences = list(
                    dict.fromkeys(
                        [
                            *primary_result.key_field_divergences,
                            *key_field_divergences(primary_result, result),
                        ]
                    )
                )
                if merged != list(primary_result.warnings) or merged_divergences != list(
                    primary_result.key_field_divergences
                ):
                    primary_result = primary_result.model_copy(
                        update={
                            "warnings": merged,
                            "key_field_divergences": merged_divergences,
                        }
                    )
                secondary_count += 1
                if data_type != DataType.FINANCIALS or secondary_count >= 2:
                    break

        if primary_result is not None:
            if circuit_open:
                primary_result = primary_result.model_copy(
                    update={"circuit_open_providers": circuit_open}
                )
            await self._cache.set(data_type, ticker, primary_result)
            return primary_result

        # 3. All providers failed — return stale cache with PROMINENT warning
        if cached is not None:
            stale = cached.data
            age_hours = (datetime.now(tz=timezone.utc) - cached.cached_at).total_seconds() / 3600
            # Provider/data layer emits neutral English (BUG-046): this string
            # flows verbatim into format_summary's "Data Source Notes" and the
            # report Disclaimer, so a hardcoded Chinese string would leak into an
            # English `--lang en` report. Localization belongs in the display/UI
            # layer keyed on meta.language, not in the data layer. The "source"/
            # "stale"/"cache" tokens here are also what base.py's disclaimer
            # filter matches on, so English wording fixes the prior miss where
            # the Chinese warning never reached the Disclaimer's Data Sources.
            stale_warning = (
                f"All data sources failed; showing cached data from {age_hours:.0f}h ago "
                f"({ticker} / {data_type}). Retry later for fresh data."
            )
            logger.warning(stale_warning)
            return stale.model_copy(update={"warnings": [stale_warning] + stale.warnings})

        # 4. No data anywhere
        msg = (
            f"Data unavailable ({ticker} / {data_type}): all data sources failed "
            f"and no cache is available."
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

    @overload
    async def fetch_canonical(
        self, data_type: Literal[DataType.FINANCIALS], ticker: str, **kwargs: Any
    ) -> NormalizedFinancials: ...
    @overload
    async def fetch_canonical(
        self, data_type: Literal[DataType.PRICE], ticker: str, **kwargs: Any
    ) -> NormalizedPrice: ...
    @overload
    async def fetch_canonical(
        self, data_type: str | DataType, ticker: str, **kwargs: Any
    ) -> NormalizedPrice | NormalizedFinancials: ...

    async def fetch_canonical(
        self, data_type: str | DataType, ticker: str, **kwargs: Any
    ) -> NormalizedPrice | NormalizedFinancials:
        """Return the normalized (canonical) PRICE / FINANCIALS for a ticker.

        Typed via ``@overload`` on the ``DataType`` literal so callers passing
        ``DataType.FINANCIALS`` / ``DataType.PRICE`` get the precise contract
        type directly — no ``assert isinstance`` narrowing at the call site. The
        str / non-literal fallback overload still returns the union.

        The one true normalization关卡 (ADR-0006): versioned canonical cache →
        on miss, raw provider fetch (FINANCIALS runs its double-provider
        ``cross_validate`` inside ``fetch()``) → ``normalize_*`` AFTER validation
        (so the validator still sees raw cross-provider口径 divergence) → cache.
        Consumers get a typed, provenance-stamped contract instead of a raw
        provider dict. Only PRICE / FINANCIALS have canonical contracts; other
        data_types must use raw ``fetch()``.
        """
        data_type = DataType(data_type)
        if data_type not in (DataType.PRICE, DataType.FINANCIALS):
            raise ValueError(
                f"fetch_canonical supports only PRICE / FINANCIALS, got {data_type}. "
                "Other types have no canonical contract — use fetch()."
            )

        cached = await self._cache.get_canonical(data_type, ticker)
        if cached is not None and not cached.is_stale:
            return self._deserialize_canonical(data_type, cached.payload_json, from_cache=True)

        raw = await self.fetch(data_type, ticker, **kwargs)
        if raw.provider == "none":
            # All providers failed and no cache — never normalize+cache an
            # all-zero fabrication (报错一个数字砸招牌). Surface like fetch_price.
            raise ProviderError(
                f"Cannot fetch canonical {data_type} for {ticker}: "
                f"all providers failed and no cache is available."
            )

        normalized: NormalizedPrice | NormalizedFinancials = (
            normalize_price(raw) if data_type == DataType.PRICE else normalize_financials(raw)
        )
        # Carry the raw fetch's warnings (incl. cross_validate discrepancies)
        # onto the canonical object so they survive the normalization boundary.
        if raw.warnings:
            normalized.warnings = list(raw.warnings)
        # BUG-007: promote the STRUCTURED key-field divergences to
        # Provenance.degraded (in addition to the prose warning above) so
        # dcf_seed / comps can programmatically down-confidence or tag [金融待核]
        # the primary's number instead of parsing the free-text warning. The
        # number still flows — this only flags it. Only meaningful for FINANCIALS;
        # PRICE never populates key_field_divergences.
        for field in raw.key_field_divergences:
            marker = degraded_provider_divergence(field)
            if marker not in normalized.provenance.degraded:
                normalized.provenance.degraded.append(marker)
        for provider_name in raw.circuit_open_providers:
            marker = degraded_circuit_open(provider_name)
            if marker not in normalized.provenance.degraded:
                normalized.provenance.degraded.append(marker)
        await self._cache.set_canonical(data_type, ticker, normalized.model_dump_json())
        return normalized

    @staticmethod
    def _deserialize_canonical(
        data_type: DataType, payload_json: str, *, from_cache: bool
    ) -> NormalizedPrice | NormalizedFinancials:
        obj: NormalizedPrice | NormalizedFinancials = (
            NormalizedPrice.model_validate_json(payload_json)
            if data_type == DataType.PRICE
            else NormalizedFinancials.model_validate_json(payload_json)
        )
        obj.provenance.from_cache = from_cache
        return obj

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
        # I7: same normalisation as fetch() — canonical enum for all
        # downstream comparisons and provider capability lookups.
        data_type = DataType(data_type)

        for provider in self._providers:
            if data_type not in provider.capabilities():
                continue
            if self._health_gated(provider):
                continue
            try:
                result = await provider.fetch(ticker, data_type, years=years, **kwargs)
            except ProviderError as e:
                self._health.record_failure(provider.name, rate_limited=is_rate_limit_error(e))
                logger.warning(
                    f"Provider '{provider.name}' failed for {ticker}/{data_type} "
                    f"(historical, {years}y): {e}"
                )
                continue
            self._health.record_success(provider.name)
            return self._split_yearly(result)

        msg = f"Historical data unavailable for {ticker}/{data_type}: all providers failed."
        logger.error(msg)
        return []

    async def fetch_quote(self, ticker: str) -> DataResult:
        """Lightweight current-price fetch that PROPAGATES provider failure.

        Unlike :meth:`fetch`, which swallows ``ProviderError`` and returns a
        stale/error DataResult, ``fetch_quote`` raises the last provider error
        when every QUOTE-capable provider fails. The quote-batch layer relies on
        that to distinguish an upstream rate-limit (→ preserve stale + open the
        cooldown window) from a delisted ticker (→ None tombstone) — a
        distinction the swallowing path destroys. Quotes are cached by
        ``QuoteCache`` (60s + cooldown), so this deliberately bypasses the
        DataLayer cache and just walks the provider chain (FMP → yfinance).
        """
        last_error: ProviderError | None = None
        for provider in self._providers:
            if DataType.QUOTE not in provider.capabilities():
                continue
            if self._health_gated(provider):
                continue
            try:
                result = await provider.fetch(ticker, DataType.QUOTE)
            except ProviderError as e:
                self._health.record_failure(provider.name, rate_limited=is_rate_limit_error(e))
                logger.warning(f"Provider '{provider.name}' QUOTE failed for {ticker}: {e}")
                last_error = e
                continue
            self._health.record_success(provider.name)
            return result
        if last_error is not None:
            raise last_error
        raise ProviderError(f"No QUOTE-capable provider available for {ticker}")

    async def fetch_price_range(
        self, ticker: str, start: str, end: str, interval: str = "1d"
    ) -> list[PriceBar]:
        """Fetch arbitrary-range split/dividend-adjusted daily OHLCV as typed bars.

        The one door for caller-chosen price windows (BUG-022): walks the provider
        chain (FMP → yfinance) like :meth:`fetch`, but the cache slot is keyed by
        ``(ticker, start, end, interval)`` so distinct windows never overwrite each
        other. Bars are ascending and on a single adjusted basis (FMP adjClose /
        yfinance ``auto_adjust``), so a multi-year backtest reads one consistent
        price series instead of a split-broken one. Raises ``ProviderError`` when
        every capable provider fails (no silent empty series).

        ``start``/``end`` are ISO dates (``YYYY-MM-DD``); ``end`` is exclusive per
        the underlying providers' conventions.
        """

        async def _fetch() -> dict[str, Any]:
            last_error: ProviderError | None = None
            for provider in self._providers:
                if DataType.PRICE_RANGE not in provider.capabilities():
                    continue
                if self._health_gated(provider):
                    continue
                try:
                    result = await provider.fetch(
                        ticker, DataType.PRICE_RANGE, start=start, end=end, interval=interval
                    )
                except ProviderError as e:
                    self._health.record_failure(provider.name, rate_limited=is_rate_limit_error(e))
                    logger.warning(
                        f"Provider '{provider.name}' PRICE_RANGE failed for "
                        f"{ticker} {start}..{end}: {e}"
                    )
                    last_error = e
                    continue
                self._health.record_success(provider.name)
                return result.data
            if last_error is not None:
                raise last_error
            raise ProviderError(f"No PRICE_RANGE-capable provider available for {ticker}")

        data = await cached_fetch(
            self._cache,
            DataType.PRICE_RANGE,
            ticker.upper(),
            _fetch,
            cache_key_suffix=f":{start}:{end}:{interval}",
        )
        raw_bars = data.get("bars", []) if isinstance(data, dict) else []
        return [PriceBar.model_validate(b) for b in raw_bars]

    async def fetch_price(self, ticker: str) -> DataResult:
        """Fetch PRICE (current price + ~1y OHLC), caching success and RAISING
        the last provider error on total failure.

        Unlike :meth:`fetch`, which swallows ``ProviderError`` into a generic
        error DataResult, this propagates the originating provider error so the
        /price route can classify bad-ticker (→422) vs upstream-down (→502) via
        ``_is_yfinance_service_down``. Fresh cache is served first; if all
        providers fail but a stale row exists, the stale row is returned (the
        route surfaces its own stale warning) rather than raising.
        """
        cached = await self._cache.get(DataType.PRICE, ticker)
        if cached is not None and not cached.is_stale:
            return cached.data
        last_error: ProviderError | None = None
        for provider in self._providers:
            if DataType.PRICE not in provider.capabilities():
                continue
            if self._health_gated(provider):
                continue
            try:
                result = await provider.fetch(ticker, DataType.PRICE)
            except ProviderError as e:
                self._health.record_failure(provider.name, rate_limited=is_rate_limit_error(e))
                logger.warning(f"Provider '{provider.name}' PRICE failed for {ticker}: {e}")
                last_error = e
                continue
            self._health.record_success(provider.name)
            # Cross-source price tripwire (ADR-0004 §6 open question H): confirm
            # the current price against a SECOND provider's lightweight QUOTE
            # before caching it as authoritative. Best-effort — a secondary
            # failure never blocks the primary price. Only the cheap QUOTE is
            # pulled (not a second year of OHLC), preserving the QUOTE/PRICE
            # perf split. Runs only on cache-miss, like FINANCIALS cross_validate.
            price_warns = await self._cross_source_price_warnings(
                ticker, primary=result, skip_provider=provider.name
            )
            if price_warns:
                for w in price_warns:
                    logger.warning(w)
                result = result.model_copy(update={"warnings": list(result.warnings) + price_warns})
            await self._cache.set(DataType.PRICE, ticker, result)
            return result
        if cached is not None:
            return cached.data  # stale beats nothing; route adds its own warning
        if last_error is not None:
            raise last_error
        raise ProviderError(f"No PRICE-capable provider available for {ticker}")

    async def _cross_source_price_warnings(
        self, ticker: str, *, primary: DataResult, skip_provider: str
    ) -> list[str]:
        """Confirm ``primary``'s current price against a second provider's QUOTE.

        Walks the provider chain for the first QUOTE-capable provider that is NOT
        the one that served ``primary``, and cross-validates the two prices. Pure
        best-effort: a secondary ProviderError is swallowed (this is a validation
        probe, not a data dependency) and does NOT touch the health breaker, which
        governs real fetches. Returns ``[]`` when no second provider answers.
        """
        for provider in self._providers:
            if provider.name == skip_provider:
                continue
            if DataType.QUOTE not in provider.capabilities():
                continue
            if self._health_gated(provider):
                continue
            try:
                secondary = await provider.fetch(ticker, DataType.QUOTE)
            except ProviderError as e:
                logger.debug(
                    "Price cross-check probe skipped: %s QUOTE failed for %s: %s",
                    provider.name,
                    ticker,
                    e,
                )
                continue
            return cross_validate_price(primary, secondary)
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
