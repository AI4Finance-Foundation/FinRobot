from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

_BASE_URL = "https://finnhub.io/api/v1"
_SUPPORTED = [DataType.FINANCIALS, DataType.PRICE, DataType.PROFILE, DataType.NEWS]
_TIMEOUT = 15.0
_MIN_INTERVAL = 1.1  # Finnhub free tier: 60 req/min → 1 req/sec; 1.1s adds 10% buffer
# Trailing calendar window for the candle (daily OHLC) fetch. 52 weeks + cushion
# so the downstream 52-week high/low window (366 calendar days) is fully covered
# even across weekend/holiday gaps at the boundary — mirrors FMP's _PRICE_HISTORY_DAYS.
_PRICE_HISTORY_DAYS = 372


class FinnhubProvider(DataProvider):
    """DataProvider backed by Finnhub API.

    Provides company profiles, basic financials, and SEC-reported data.
    API key required — get one at https://finnhub.io/
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

    @property
    def financials_fields(self) -> set[str]:
        return {
            "revenue",
            "ebitda",
            "net_income",
            "market_cap",
            "shares_outstanding",
            "gross_margin",
            "operating_margin",
            "depreciation_amortization",
            "total_debt",
            "total_cash",
        }

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by Finnhub. Supported: {_SUPPORTED}"
            )
        try:
            if data_type == DataType.FINANCIALS:
                years = kwargs.get("years")
                data = await self._fetch_financials(ticker, years=years)
            elif data_type == DataType.PRICE:
                data = await self._fetch_price(ticker)
            elif data_type == DataType.PROFILE:
                data = await self._fetch_profile(ticker)
            elif data_type == DataType.NEWS:
                return await self._fetch_news(ticker)
            else:
                raise ProviderError(f"Unhandled data_type: {data_type}")
        except httpx.TimeoutException as e:
            raise ProviderError(f"Finnhub timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Finnhub API error for '{ticker}': {e}") from e
        except (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
        ) as e:
            raise ProviderError(f"Finnhub network error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"Finnhub fetch failed for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_financials(self, ticker: str, *, years: int | None = None) -> dict[str, Any]:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()

        reported = (
            await self._get(
                "/stock/financials-reported",
                params={"symbol": ticker, "freq": "annual"},
            )
        ).json()

        filings = reported.get("data", [])

        if years is not None and years > 1:
            parsed = [self._parse_filing(filing, profile) for filing in filings[:years]]
            return {"yearly_data": parsed}

        # Single-year (default): return flat dict
        latest = filings[0] if filings else {}
        return self._parse_filing(latest, profile)

    @staticmethod
    def _parse_filing(filing: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        """Parse a single Finnhub SEC filing into a normalized dict."""
        report = filing.get("report", {})

        def _find_concept(section: str, concept: str) -> float | None:
            items = report.get(section, [])
            for item in items:
                if item.get("concept") == concept:
                    val: Any = item.get("value")
                    return float(val) if val is not None else None
            return None

        mkt_cap_millions = profile.get("marketCapitalization")
        shares_millions = profile.get("shareOutstanding")

        revenue = _find_concept("ic", "Revenues")
        net_income = _find_concept("ic", "NetIncomeLoss")
        da = _find_concept("ic", "DepreciationAndAmortization")
        operating_income = _find_concept("ic", "OperatingIncomeLoss")
        cogs = _find_concept("ic", "CostOfGoodsAndServicesSold")
        total_debt = _find_concept("bs", "LongTermDebt")
        total_cash = _find_concept("bs", "CashAndCashEquivalentsAtCarryingValue")

        return {
            "revenue": revenue,
            "ebitda": (
                operating_income + da if (operating_income is not None and da is not None) else None
            ),
            "net_income": net_income,
            "depreciation_amortization": da,
            "total_debt": total_debt,
            "total_cash": total_cash,
            "market_cap": mkt_cap_millions * 1_000_000 if mkt_cap_millions else None,
            "shares_outstanding": shares_millions * 1_000_000 if shares_millions else None,
            "gross_margin": ((revenue - cogs) / revenue if revenue and cogs is not None else None),
            "operating_margin": (
                operating_income / revenue if revenue and operating_income is not None else None
            ),
            "current_price": None,
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
            # This source pulls freq=annual SEC filings — tag it so normalize
            # doesn't default period_basis to "ttm" and stamp as_of to the fetch
            # wall-clock. Without these a 12-month-old 10-K is mislabeled a fresh
            # TTM snapshot. ``endDate`` is the fiscal-period end (the semantic
            # date the freshness pill / ttm-lag read).
            "period_basis": "annual",
            "fiscal_year": filing.get("endDate") or filing.get("filedDate"),
        }

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

        price_history = await self._fetch_candle_bars(ticker)

        return {
            "current_price": float(current_price),
            "price_history": price_history,
            "exchange": exchange,
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

    async def _fetch_profile(self, ticker: str) -> dict[str, Any]:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()
        return {
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
            "market_cap": (profile.get("marketCapitalization", 0) or 0) * 1_000_000,
            "shares_outstanding": (profile.get("shareOutstanding", 0) or 0) * 1_000_000,
            "exchange": profile.get("exchange"),
        }

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
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
            headers = {"X-Finnhub-Token": self._api_key}
            resp = await self._client.get(
                f"{_BASE_URL}{path}", params=params or {}, headers=headers
            )
            resp.raise_for_status()
            return resp

    async def close(self) -> None:
        """Release the shared httpx client. Called from DataLayer.close()."""
        await self._client.aclose()
