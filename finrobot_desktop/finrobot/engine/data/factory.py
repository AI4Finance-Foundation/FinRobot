"""Factory for building a DataLayer from runtime settings.

Lives in ``engine/data/`` because assembling the provider chain is a data-layer
concern. It sits ABOVE ``layer`` / ``cache`` (it imports them) and must never be
imported by them, so moving it here introduces no cycle. ``routes/settings.py``,
``server.py``, ``sdk.py`` and ``cli.py`` import ``build_data_layer`` from here.
"""

from __future__ import annotations

import logging
from typing import Any

from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)


def build_provider_chain(settings: Any) -> list[Any]:
    """Build the ordered provider chain from runtime settings.

    Provider priority (highest first):
      1. FMP (optional — financials, earnings, news, transcripts; appended only when key set)
      2. Finnhub (optional — additional news, company profile)
      3. yfinance (always — price fallback, historical data, financials when no FMP)
      4. **SEC EDGAR (via EdgarTools 5.31) — conditional on valid identity**
         (registered only when ``_is_valid_identity(settings.sec_user_agent)``;
         otherwise SKIPPED and the app starts normally with SEC data unavailable.
         Replaces the hand-rolled ``sec_provider.py``. See spec
         ``specs/research/EdgarTools5集成评估-2026-05-27.md``.)

    FMP gives the most accurate financial statements + D&A + earnings
    surprises + enables cross-validation. Without it, yfinance handles
    financials (DCF uses simplified D&A formula, 10-20% deviation).
    validate_runtime_config() emits a warning when FMP is unset.
    """
    from finrobot.engine.data.providers.edgar_provider import (
        EdgarToolsProvider,
        _is_valid_identity,
    )
    from finrobot.engine.data.providers.news_aggregator import NewsAggregatorProvider
    from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider

    providers: list[Any] = []

    if settings.fmp_api_key:
        from finrobot.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))

    if settings.finnhub_api_key:
        from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))

    # yfinance as fallback for price/historical data + cross-validation
    providers.append(YFinanceProvider())

    # SEC EDGAR provider — conditional registration. The app MUST start
    # cleanly even when identity is missing/invalid; SEC-dependent routes
    # degrade to a "data unavailable" placeholder + landing banner that
    # points the user at Settings → SEC identity. This contract is sealed
    # in spec v4 §1.2 (Settings UX) and §5 (adapter rules).
    if _is_valid_identity(getattr(settings, "sec_user_agent", "")):
        providers.append(EdgarToolsProvider(user_agent=settings.sec_user_agent))
        logger.info(
            "SEC EDGAR provider registered (identity=%r)",
            settings.sec_user_agent,
        )
    else:
        logger.warning(
            "SEC EDGAR provider SKIPPED — invalid identity %r. "
            "Set settings.sec_user_agent to 'Name email@domain' to enable "
            "10-K / 10-Q / 8-K / Form 4 / 13F / DEF 14A data.",
            getattr(settings, "sec_user_agent", ""),
        )

    if settings.adanos_api_key:
        from finrobot.engine.data.providers.adanos_provider import AdanosProvider

        providers.append(AdanosProvider(api_key=settings.adanos_api_key))

    # News aggregator — always registered; uses yfinance Ticker.news (free, no
    # key) as its always-on source, plus Alpha Vantage sentiment when a key is
    # provided. (Its old free source, Yahoo's RSS headline feed, was 404'd by
    # Yahoo — BUG-072 — so it now reads the same headlines via yfinance.)
    av_key = getattr(settings, "alpha_vantage_api_key", "")
    providers.append(NewsAggregatorProvider(alpha_vantage_api_key=av_key))

    return providers


def build_data_layer(settings: Any) -> DataLayer:
    """Assemble the full provider chain + a fresh cache into a DataLayer.

    Used by the CLI / SDK / Settings-rebuild paths. The sidecar boot path instead
    seeds a placeholder DataLayer and calls ``add_providers(build_provider_chain(
    settings))`` on it in a warmup task (see server.lifespan), keeping the ~0.5s of
    provider-module imports off the cold-start critical path.
    """
    cache = DataCache(settings.cache_db_path)
    return DataLayer(providers=build_provider_chain(settings), cache=cache)


async def shutdown_data_layer(data_layer: DataLayer | None = None) -> None:
    """Graceful teardown for a NON-server entrypoint (scripts / one-off tools / SDK
    one-shots) that built a DataLayer via ``build_data_layer``. Closes the layer plus the
    process-level quote-batch and SEC-holdings singletons, so the aiosqlite worker threads
    join and WAL checkpoints — instead of leaking the threads and racing the loop close
    into the "Event loop is closed" hang (observed: _regen / validation scripts blocking
    minutes at exit, 2026-06-24). Mirrors server.py's FastAPI-lifespan teardown for code
    paths that never run that lifespan. Safe when a singleton was never opened (the close
    helpers no-op on an unset singleton)."""
    if data_layer is not None:
        await data_layer.close()
    # Lazy imports keep the cold-import path light and avoid a cycle (both modules sit
    # below factory). Mirror server.py teardown ordering.
    from finrobot.engine.data.quote_batch import close_quote_cache_singleton
    from finrobot.engine.data.sec_holdings_cache import close_singleton as close_sec_holdings

    await close_quote_cache_singleton()
    await close_sec_holdings()
