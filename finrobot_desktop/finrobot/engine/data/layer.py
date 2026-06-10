import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal, overload

from pydantic import ValidationError

from finrobot.engine.data.cache import DataCache, cached_fetch
from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.provider_health import ProviderHealth, ProviderState
from finrobot.engine.data.normalize import (
    NormalizedFinancials,
    NormalizedForwardEstimates,
    NormalizedPrice,
    PriceBar,
    normalize_financials,
    normalize_forward_estimates,
    normalize_price,
)
from finrobot.engine.data.types import DataType
from finrobot.engine.data.normalize.currency import normalize_canonical_financials_currency
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_FX_NORMALIZED,
    DEGRADED_FX_UNAVAILABLE,
    degraded_circuit_open,
    degraded_price_divergence,
    degraded_provider_divergence,
)
from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd
from finrobot.engine.data.validator import (
    cross_validate,
    cross_validate_price,
    key_field_divergences,
    market_cap_consistency,
)

logger = logging.getLogger(__name__)

# Union of the typed contracts the canonical gate can serve. FORWARD_ESTIMATES
# joined PRICE / FINANCIALS in 2026-06 (hard single-source for the DCF-seed
# entries); every other data_type remains raw-fetch only.
CanonicalSnapshot = NormalizedPrice | NormalizedFinancials | NormalizedForwardEstimates
_CANONICAL_TYPES = (DataType.PRICE, DataType.FINANCIALS, DataType.FORWARD_ESTIMATES)


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
        # Single-flight registry for the canonical slow path: at most one
        # in-flight provider fetch per (data_type, ticker). Concurrent callers
        # ride the same Task instead of each hitting the provider — the
        # rate-limit shield for an open-market refresh fan-out (see
        # ``fetch_canonical``). Lives for one process; entries self-evict on
        # completion.
        self._inflight_canonical: dict[tuple[DataType, str], asyncio.Future[CanonicalSnapshot]] = {}

    def _health_gated(self, provider: DataProvider) -> bool:
        """True if ``provider`` is in an open cooldown window and should be skipped.

        Logs once at skip-time so a tripped provider is visible in logs without
        being silently absent from the chain.
        """
        if self._health.is_available(provider.name):
            return False
        logger.info("Provider '%s' in cooldown (circuit open) — skipping", provider.name)
        return True

    def provider_status(self) -> list[tuple[str, bool, ProviderState]]:
        """(name, available_now, breaker snapshot) per configured provider, in
        chain priority order — the Settings「Data Provider Status」panel feed.
        Read-only view over the live ProviderHealth breaker (never a mock)."""
        return [
            (p.name, self._health.is_available(p.name), self._health.snapshot(p.name))
            for p in self._providers
        ]

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

        # Cache identity must include every kwarg that varies the provider
        # payload (sentiment days_back=7 vs 30 collided in one ticker slot and
        # served the wrong window until TTL). Sorted for call-order stability;
        # kwarg-less calls keep the bare ticker key, so existing slots stay
        # reachable.
        cache_key = ticker + "".join(f":{k}={v}" for k, v in sorted(kwargs.items()))

        # 1. Fresh cache hit — raw slot; staleness is by TTL only. Canonical
        # slots use version-tagged keys (ADR-0006 C1) that auto-invalidate on
        # schema bumps, so a fresh hit needs no contract-shape check.
        cached = await self._cache.get(data_type, cache_key)
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
            await self._cache.set(data_type, cache_key, primary_result)
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
            return stale.model_copy(
                update={
                    "warnings": [stale_warning] + stale.warnings,
                    "from_stale_cache": True,
                }
            )

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
        self, data_type: Literal[DataType.FORWARD_ESTIMATES], ticker: str, **kwargs: Any
    ) -> NormalizedForwardEstimates: ...
    @overload
    async def fetch_canonical(
        self, data_type: str | DataType, ticker: str, **kwargs: Any
    ) -> CanonicalSnapshot: ...

    async def fetch_canonical(
        self, data_type: str | DataType, ticker: str, **kwargs: Any
    ) -> CanonicalSnapshot:
        """Return the normalized (canonical) PRICE / FINANCIALS /
        FORWARD_ESTIMATES for a ticker.

        Typed via ``@overload`` on the ``DataType`` literal so callers passing
        ``DataType.FINANCIALS`` / ``DataType.PRICE`` /
        ``DataType.FORWARD_ESTIMATES`` get the precise contract type directly —
        no ``assert isinstance`` narrowing at the call site. The str /
        non-literal fallback overload still returns the union.

        The one true normalization关卡 (ADR-0006): versioned canonical cache →
        on miss, raw provider fetch (FINANCIALS runs its double-provider
        ``cross_validate`` inside ``fetch()``) → ``normalize_*`` AFTER validation
        (so the validator still sees raw cross-provider口径 divergence) → cache.
        Consumers get a typed, provenance-stamped contract instead of a raw
        provider dict. Only these three types have canonical contracts; other
        data_types must use raw ``fetch()``.
        """
        data_type = DataType(data_type)
        if data_type not in _CANONICAL_TYPES:
            raise ValueError(
                f"fetch_canonical supports only PRICE / FINANCIALS / FORWARD_ESTIMATES, "
                f"got {data_type}. Other types have no canonical contract — use fetch()."
            )

        cached = await self._cache.get_canonical(data_type, ticker)
        if cached is not None and not cached.is_stale:
            try:
                return self._deserialize_canonical(data_type, cached.payload_json, from_cache=True)
            except ValidationError:
                # Corrupt canonical row (mangled JSON / contract drift without a
                # version bump). Delete it and fall through to the provider path
                # (self-heal) — re-raising here would block the slot until the
                # 30-day evict, since this read precedes every provider fetch.
                logger.warning(
                    "Corrupt canonical cache row for %s/%s — deleting and refetching (self-heal)",
                    ticker,
                    data_type,
                )
                await self._cache.delete_canonical(data_type, ticker)

        # Cache miss/stale → single-flight the provider fetch: exactly one
        # in-flight call per (data_type, ticker); concurrent callers ride the
        # same Task. This collapses a refresh fan-out (N tickers, or a mashed
        # refresh button) and any other canonical consumer (research pipeline,
        # /price route) onto one network call — the open-market refresh path's
        # rate-limit shield. Safe under asyncio's single thread: there is no
        # await between the miss check and the registry insert, so two coroutines
        # can never both create the in-flight Task.
        key = (data_type, ticker)
        existing = self._inflight_canonical.get(key)
        if existing is not None:
            return await existing
        task: asyncio.Future[CanonicalSnapshot] = asyncio.ensure_future(
            self._fetch_canonical_uncached(data_type, ticker, **kwargs)
        )
        self._inflight_canonical[key] = task
        try:
            return await task
        finally:
            self._inflight_canonical.pop(key, None)

    async def _fetch_canonical_uncached(
        self, data_type: DataType, ticker: str, **kwargs: Any
    ) -> CanonicalSnapshot:
        """The cache-miss path of :meth:`fetch_canonical` — raw provider fetch →
        normalize (AFTER cross_validate) → cache. Wrapped by ``fetch_canonical``
        in a single-flight so concurrent callers for one (data_type, ticker)
        share a single execution.
        """
        raw = (
            await self.fetch_price(ticker)
            if data_type == DataType.PRICE
            else await self.fetch(data_type, ticker, **kwargs)
        )
        if raw.provider == "none":
            # All providers failed and no cache — never normalize+cache an
            # all-zero fabrication (报错一个数字砸招牌). Surface like fetch_price.
            raise ProviderError(
                f"Cannot fetch canonical {data_type} for {ticker}: "
                f"all providers failed and no cache is available."
            )

        normalized: CanonicalSnapshot
        if data_type == DataType.PRICE:
            normalized = normalize_price(raw)
        elif data_type == DataType.FORWARD_ESTIMATES:
            normalized = normalize_forward_estimates(raw)
        else:
            normalized = normalize_financials(raw)
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
        for field in raw.price_field_divergences:
            marker = degraded_price_divergence(field)
            if marker not in normalized.provenance.degraded:
                normalized.provenance.degraded.append(marker)
        for provider_name in raw.circuit_open_providers:
            marker = degraded_circuit_open(provider_name)
            if marker not in normalized.provenance.degraded:
                normalized.provenance.degraded.append(marker)
        # FX关卡 (ADR-0006): a foreign ADR's FINANCIALS carries reporting-currency
        # IS/BS line items beside a quote-currency market_cap. Convert them to one
        # currency HERE — the sole normalization chokepoint — so every downstream
        # consumer (extractor → /financials route, Coverage, AI orchestrator) sees
        # a single-currency snapshot and can't form the cross-currency EV that went
        # negative for TSM (-75.1B, probe 2026-06-09). No-op for single-currency
        # issuers; PRICE is unaffected.
        if data_type == DataType.FINANCIALS and isinstance(normalized, NormalizedFinancials):
            normalized = await self._apply_canonical_fx(normalized)
        # Stale-fallback (all providers failed → fetch served the last-known cached
        # row): serve it to THIS caller, but do NOT re-cache. Writing it would bump
        # cached_at and flip the canonical is_stale back to False, laundering a stale
        # price into a "fresh"-reading quote (the 2026-06-08 in-market bug). Leaving
        # the prior canonical row untouched keeps it honestly is_stale=True, so the
        # next read retries the (hopefully recovered) provider chain.
        if raw.from_stale_cache:
            return normalized
        await self._cache.set_canonical(data_type, ticker, normalized.model_dump_json())
        return normalized

    def _fmp_api_key(self) -> str | None:
        """FMP key from the configured providers, for the FX-rate FMP fallback.

        yfinance is the primary FX source (no key); FMP is only consulted when a
        shared-budget yfinance 429 storm strands the rate (see fetch_fx_rate_to_usd).
        Best-effort: returns None when no FMP provider is wired, leaving the FX read
        yfinance-only.
        """
        for provider in self._providers:
            if getattr(provider, "name", "") == "fmp":
                return getattr(provider, "_api_key", None)
        return None

    async def reporting_to_quote_rate(self, reporting_ccy: str, quote_ccy: str) -> float:
        """Factor expressing one unit of ``reporting_ccy`` in ``quote_ccy``.

        Quote is USD in the overwhelmingly common ADR case (TSM/SAP/TM), so this is
        just the reporting→USD spot. Otherwise reporting→USD ÷ quote→USD.

        Public because two surfaces need the same FX chokepoint: the canonical
        snapshot (``_apply_canonical_fx``) and the historical-band loader
        (``historical_loaders.load_yearly_financials``), which must put native
        yearly EBITDA / net-debt in the quote currency before mixing them with the
        USD ADR price.
        """
        fmp_key = self._fmp_api_key()
        reporting_to_usd = await fetch_fx_rate_to_usd(reporting_ccy, fmp_api_key=fmp_key)
        if quote_ccy.upper() == "USD":
            return reporting_to_usd
        quote_to_usd = await fetch_fx_rate_to_usd(quote_ccy, fmp_api_key=fmp_key)
        return reporting_to_usd / quote_to_usd

    async def _apply_canonical_fx(self, nf: NormalizedFinancials) -> NormalizedFinancials:
        """Make a foreign-ADR snapshot single-currency before it is cached.

        No-op when reporting_currency == quote_currency (US issuers, local
        listings). On FX-fetch failure the snapshot ships un-converted but flagged
        ``fx_unavailable`` — the FinancialData model invariant (class B) then
        withholds the EV rather than emitting the negative cross-currency value.
        Never fails the canonical fetch over a missing FX quote (a missing rate
        must not take down an otherwise-complete fundamentals fetch).
        """
        if nf.reporting_currency.upper() == nf.quote_currency.upper():
            return nf
        try:
            rate = await self.reporting_to_quote_rate(nf.reporting_currency, nf.quote_currency)
        except ProviderError as exc:
            logger.warning(
                "FX %s→%s unavailable for %s — canonical ships un-normalized; "
                "EV/cross-currency multiples withheld downstream: %s",
                nf.reporting_currency,
                nf.quote_currency,
                nf.ticker,
                exc,
            )
            if DEGRADED_FX_UNAVAILABLE not in nf.provenance.degraded:
                nf.provenance.degraded.append(DEGRADED_FX_UNAVAILABLE)
            return nf
        converted = normalize_canonical_financials_currency(nf, rate)
        if DEGRADED_FX_NORMALIZED not in converted.provenance.degraded:
            converted.provenance.degraded.append(DEGRADED_FX_NORMALIZED)
        return converted

    @overload
    async def read_canonical_cached(
        self, data_type: Literal[DataType.FINANCIALS], ticker: str
    ) -> tuple[NormalizedFinancials, bool] | None: ...
    @overload
    async def read_canonical_cached(
        self, data_type: Literal[DataType.PRICE], ticker: str
    ) -> tuple[NormalizedPrice, bool] | None: ...
    @overload
    async def read_canonical_cached(
        self, data_type: Literal[DataType.FORWARD_ESTIMATES], ticker: str
    ) -> tuple[NormalizedForwardEstimates, bool] | None: ...
    @overload
    async def read_canonical_cached(
        self, data_type: str | DataType, ticker: str
    ) -> tuple[CanonicalSnapshot, bool] | None: ...

    async def read_canonical_cached(
        self, data_type: str | DataType, ticker: str
    ) -> tuple[CanonicalSnapshot, bool] | None:
        """Read canonical PRICE/FINANCIALS from cache WITHOUT ever fetching.

        Returns ``(normalized, is_stale)`` — the last-known snapshot even when
        past its freshness TTL (``is_stale=True``) — or ``None`` on a true cache
        miss. This is the stale-while-revalidate read: the Coverage overview
        paints instantly from the last snapshot (no network, ~ms at any N), then
        a separate ``refresh`` pass revalidates. Contrast ``fetch_canonical``,
        which goes to the provider chain on a stale/missing entry (the 6.6s-for-6,
        >180s-for-100 cold fan-out that made the desk "load every open").
        """
        data_type = DataType(data_type)
        if data_type not in _CANONICAL_TYPES:
            raise ValueError(
                f"read_canonical_cached supports only PRICE / FINANCIALS / FORWARD_ESTIMATES, "
                f"got {data_type}."
            )
        cached = await self._cache.get_canonical(data_type, ticker)
        if cached is None:
            return None
        try:
            normalized = self._deserialize_canonical(
                data_type, cached.payload_json, from_cache=True
            )
        except ValidationError:
            # Same self-heal as fetch_canonical: a corrupt row reads as a miss
            # and is deleted, so the next fetch_canonical repopulates the slot.
            logger.warning(
                "Corrupt canonical cache row for %s/%s — deleting (self-heal)",
                ticker,
                data_type,
            )
            await self._cache.delete_canonical(data_type, ticker)
            return None
        return normalized, cached.is_stale

    @staticmethod
    def _deserialize_canonical(
        data_type: DataType, payload_json: str, *, from_cache: bool
    ) -> CanonicalSnapshot:
        obj: CanonicalSnapshot
        if data_type == DataType.PRICE:
            obj = NormalizedPrice.model_validate_json(payload_json)
        elif data_type == DataType.FORWARD_ESTIMATES:
            obj = NormalizedForwardEstimates.model_validate_json(payload_json)
        else:
            obj = NormalizedFinancials.model_validate_json(payload_json)
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
        cache_key = f"{ticker}:historical:{data_type.value}:{years}"
        cached = await self._cache.get(DataType.HISTORICAL, cache_key)
        if cached is not None and not cached.is_stale:
            return self._split_yearly(cached.data)

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
            await self._cache.set(DataType.HISTORICAL, cache_key, result)
            return self._split_yearly(result)

        if cached is not None:
            stale_warning = (
                f"Historical data sources failed; showing cached {years}y data "
                f"for {ticker}/{data_type}."
            )
            logger.warning(stale_warning)
            stale = cached.data.model_copy(
                update={"warnings": [stale_warning, *cached.data.warnings]}
            )
            return self._split_yearly(stale)

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
        gated_capable: list[str] = []
        for provider in self._providers:
            if DataType.QUOTE not in provider.capabilities():
                continue
            if self._health_gated(provider):
                gated_capable.append(provider.name)
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
        if gated_capable:
            # Transient exhaustion: QUOTE-capable providers exist but ALL sit in
            # an open circuit-breaker cooldown, so nothing was even attempted.
            # This must carry rate-limit semantics — a plain ProviderError here
            # is not recognised by is_rate_limit_error, so quote_batch would
            # return None and get_batch would overwrite every stale price with
            # a fresh None tombstone (the 429 disaster, back via the breaker).
            raise RateLimitedProviderError(
                f"All QUOTE-capable providers for {ticker} are in circuit-breaker "
                f"cooldown ({', '.join(gated_capable)}); serving stale until it closes."
            )
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
        circuit_open: list[str] = []
        for provider in self._providers:
            if DataType.PRICE not in provider.capabilities():
                continue
            if self._health_gated(provider):
                circuit_open.append(provider.name)
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
                result = result.model_copy(
                    update={
                        "warnings": list(result.warnings) + price_warns,
                        "price_field_divergences": [
                            *result.price_field_divergences,
                            "current_price",
                        ],
                    }
                )
            if circuit_open:
                result = result.model_copy(update={"circuit_open_providers": circuit_open})
            await self._cache.set(DataType.PRICE, ticker, result)
            return result
        if cached is not None:
            # Stale beats nothing — but FLAG it. The old comment ("route adds its
            # own warning") only held for the /price route; the canonical path
            # (_fetch_canonical_uncached) is not a route and would otherwise
            # launder this stale row into a fresh-reading canonical entry. Mirror
            # fetch()'s neutral-English stale warning (the "stale"/"cache" tokens
            # base.py's disclaimer filter matches) AND set from_stale_cache so the
            # canonical关卡 refuses to reset the freshness clock.
            stale = cached.data
            age_hours = (datetime.now(tz=timezone.utc) - cached.cached_at).total_seconds() / 3600
            stale_warning = (
                f"All data sources failed; showing cached price from {age_hours:.0f}h ago "
                f"({ticker} / PRICE). Retry later for fresh data."
            )
            logger.warning(stale_warning)
            return stale.model_copy(
                update={
                    "warnings": [stale_warning] + stale.warnings,
                    "from_stale_cache": True,
                }
            )
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
