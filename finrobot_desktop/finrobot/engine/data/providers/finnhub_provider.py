from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
)
from finrobot.engine.data.types import DataType

_BASE_URL = "https://finnhub.io/api/v1"
# Finnhub serves PRICE / NEWS only. It does NOT serve FINANCIALS:
# its /stock/financials-reported parser matched bare us-gaap concept names
# ("Revenues", "NetIncomeLoss") while the API returns them namespace-prefixed
# ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", ...), so it
# produced all-None fundamentals for every issuer — it never once worked.
# Fundamentals are owned by FMP (primary, normalised TTM) + yfinance (secondary,
# same TTM caliber for cross-validation). Finnhub's SEC-annual caliber would also
# mismatch FMP's TTM and inject false cross-validation divergences. Removed
# 2026-06-08 (option B). Authoritative SEC-XBRL fundamentals belong to
# EdgarToolsProvider (real XBRL concept resolution), not a hand-rolled matcher.
# PROFILE removed 2026-06-10: it was a DEAD capability (nothing in the codebase
# ever fetches DataType.PROFILE — only Finnhub advertised it) AND a fabrication
# landmine — _fetch_profile coerced a missing marketCapitalization/shareOutstanding
# to 0*1M = 0, a fake $0 market cap / 0 shares instead of an honest None (the
# /quote path already treats Finnhub's 0 as "no data"). The live /stock/profile2
# call _fetch_price still makes only reads `exchange`, never these fabricated
# fields, so quote/price are unaffected.
_SUPPORTED = [DataType.PRICE, DataType.NEWS]
_TIMEOUT = 15.0
_MIN_INTERVAL = 1.1  # Finnhub free tier: 60 req/min → 1 req/sec; 1.1s adds 10% buffer
# Trailing calendar window for the candle (daily OHLC) fetch. 52 weeks + cushion
# so the downstream 52-week high/low window (366 calendar days) is fully covered
# even across weekend/holiday gaps at the boundary — mirrors FMP's _PRICE_HISTORY_DAYS.
_PRICE_HISTORY_DAYS = 372


class FinnhubProvider(DataProvider):
    """DataProvider backed by Finnhub API.

    Provides company profiles, live quotes + daily OHLC candles, and company
    news. API key required — get one at https://finnhub.io/ (60 req/min free).
    Does NOT serve FINANCIALS (see ``_SUPPORTED`` note).
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0
        # Reuse one AsyncClient across the session to amortise TLS handshakes.
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    @property
    def name(self) -> str:
        return "finnhub"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by Finnhub. Supported: {_SUPPORTED}"
            )
        try:
            if data_type == DataType.PRICE:
                data = await self._fetch_price(ticker)
            elif data_type == DataType.NEWS:
                return await self._fetch_news(ticker)
            else:
                raise ProviderError(f"Unhandled data_type: {data_type}")
        except httpx.TimeoutException as e:
            raise ProviderError(f"Finnhub timeout for '{ticker}'") from e
        except httpx.HTTPStatusError as e:
            # Finnhub free tier signals throttling with HTTP 429 (60 req/min).
            # ONLY 429 maps to the typed RateLimitedProviderError; 403 here
            # means endpoint-not-on-plan (e.g. /stock/candle premium gate),
            # which is a capability gap, not throttling. Never interpolate the raw
            # httpx exception: it embeds the request URL and can surface through
            # route/provider diagnostics.
            if e.response.status_code == 429:
                raise RateLimitedProviderError(
                    f"Finnhub rate limited (HTTP 429) for '{ticker}'"
                ) from e
            raise ProviderError(
                f"Finnhub API error for '{ticker}' (HTTP {e.response.status_code})"
            ) from e
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
        ) as e:
            raise ProviderError(f"Finnhub network error for '{ticker}' ({type(e).__name__})") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"Finnhub fetch failed for '{ticker}' ({type(e).__name__})") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_price(self, ticker: str) -> dict[str, Any]:
        """Current price (/quote) + 1y daily OHLC (/stock/candle) + exchange.

        Returns the SAME shape as YFinanceProvider._fetch_price and
        FMPProvider._fetch_price — ``current_price`` + ``price_history`` (oldest
        first, each bar date/open/high/low/close/volume) + ``exchange`` — so the
        provider-agnostic ``normalize_price`` and every downstream PRICE consumer
        work without a Finnhub-specific branch. This is the third live-quote leg
        for users who hit a yfinance 429 and have no FMP key configured.

        ``/quote`` carries the live price (``c``); ``/stock/profile2`` the
        exchange. ``/stock/candle?resolution=D`` carries the daily bars — but it
        is PREMIUM-only as of mid-2024: a free-tier key gets HTTP 403 ("You don't
        have access to this resource", live-confirmed via finnhubio/Finnhub-API
        #534/#546/#553). We degrade gracefully on a 403/no_data candle: emit the
        live ``current_price`` with an EMPTY ``price_history`` rather than sinking
        the whole PRICE fetch — normalize_price then carries the live quote with
        no bars (52w high/low render N/A), which still unblocks DCF/quote paths.
        A genuine /quote failure (no price) still raises so DataLayer can fall
        through to the next provider.
        """
        quote = (await self._get("/quote", params={"symbol": ticker})).json()
        current_price = quote.get("c") if isinstance(quote, dict) else None
        # Finnhub returns c=0 for an unknown/delisted symbol (not None). Treat a
        # non-positive price as "no quote" so DataLayer falls through instead of
        # stamping a fabricated $0 live price.
        if not isinstance(current_price, int | float) or current_price <= 0:
            raise ProviderError(
                f"Finnhub /quote returned no usable price for '{ticker}' (delisted or unknown)"
            )

        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()
        exchange = profile.get("exchange") if isinstance(profile, dict) else None
        quote_currency = profile.get("currency") if isinstance(profile, dict) else None

        price_history = await self._fetch_candle_bars(ticker)

        return {
            "current_price": float(current_price),
            "price_history": price_history,
            "exchange": exchange,
            "quote_currency": quote_currency,
        }

    async def _fetch_candle_bars(self, ticker: str) -> list[dict[str, Any]]:
        """Trailing ~1y of daily OHLCV from /stock/candle, oldest-first.

        ``/stock/candle`` is premium-only on the current free tier (HTTP 403).
        Swallow that ONE status (and a ``s != "ok"`` no-data body) and return an
        empty list so the caller can still serve a quote-only PRICE result; any
        other HTTP/network error propagates so the real failure isn't masked.

        Finnhub candle bodies are parallel arrays under keys s/t/o/h/l/c/v
        (``t`` = unix seconds). Reassemble into the canonical per-bar dict.
        """
        today = datetime.now(tz=timezone.utc)
        start = today - timedelta(days=_PRICE_HISTORY_DAYS)
        try:
            candle = (
                await self._get(
                    "/stock/candle",
                    params={
                        "symbol": ticker,
                        "resolution": "D",
                        "from": int(start.timestamp()),
                        "to": int(today.timestamp()),
                    },
                )
            ).json()
        except httpx.HTTPStatusError as e:
            # 403 = candle endpoint not on this key's tier (free tier). Degrade to
            # quote-only rather than failing the whole PRICE fetch.
            if e.response.status_code == 403:
                return []
            raise

        if not isinstance(candle, dict) or candle.get("s") != "ok":
            return []

        timestamps = candle.get("t") or []
        opens = candle.get("o") or []
        highs = candle.get("h") or []
        lows = candle.get("l") or []
        closes = candle.get("c") or []
        volumes = candle.get("v") or []
        bars: list[dict[str, Any]] = []
        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue
            bars.append(
                {
                    "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                    "open": opens[i] if i < len(opens) else None,
                    "high": highs[i] if i < len(highs) else None,
                    "low": lows[i] if i < len(lows) else None,
                    "close": close,
                    "volume": volumes[i] if i < len(volumes) else None,
                }
            )
        # Finnhub candle arrays are already chronological (oldest-first), matching
        # yfinance/FMP price_history ordering the 52-week window assumes.
        return bars

    async def _fetch_news(self, ticker: str) -> DataResult:
        """Fetch recent company news from Finnhub /company-news (last 90 days)."""
        today = datetime.now(tz=timezone.utc).date()
        from_date = (today - timedelta(days=90)).isoformat()
        to_date = today.isoformat()
        raw: list[dict[str, Any]] = (
            await self._get(
                "/company-news",
                params={"symbol": ticker, "from": from_date, "to": to_date},
            )
        ).json()
        news_items = [
            {
                "title": item.get("headline", ""),
                "source": item.get("source", ""),
                "published": datetime.fromtimestamp(item["datetime"], tz=timezone.utc).isoformat()
                if item.get("datetime")
                else "",
                "url": item.get("url", ""),
            }
            for item in raw
        ]
        return DataResult(
            data={"news_items": news_items},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.NEWS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make authenticated, rate-limited GET request to Finnhub API.

        Serialises concurrent calls via asyncio.Lock and enforces a minimum
        inter-request interval (_MIN_INTERVAL) to respect the 60 req/min free-tier limit.
        """
        # Hold the lock ONLY for the rate-limit gate (paces request STARTS to
        # _MIN_INTERVAL apart); release it BEFORE the HTTP round-trip so concurrent
        # requests overlap. Holding it across self._client.get() serialized all
        # Finnhub traffic and head-of-line-blocked on any single slow request.
        # httpx.AsyncClient is safe for concurrent requests.
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
        headers = {"X-Finnhub-Token": self._api_key}
        resp = await self._client.get(f"{_BASE_URL}{path}", params=params or {}, headers=headers)
        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()
