from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.types import DataType

_BASE_URL = "https://financialmodelingprep.com/api/v3"
_SUPPORTED = [DataType.FINANCIALS, DataType.NEWS, DataType.EARNINGS]
_TIMEOUT = 15.0
_MIN_INTERVAL = 0.15  # 6 req/sec — stays within per-minute burst limits on all FMP tiers


class FMPProvider(DataProvider):
    """DataProvider backed by Financial Modeling Prep API.

    Provides D&A, R&D, SGA, and other detailed financials that yfinance lacks.
    API key required — get one at https://financialmodelingprep.com/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0

    @property
    def name(self) -> str:
        return "fmp"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by FMP. Supported: {_SUPPORTED}"
            )
        if data_type == DataType.NEWS:
            return await self._fetch_news(ticker)
        if data_type == DataType.EARNINGS:
            return await self._fetch_earnings(ticker)
        years: int | None = kwargs.get("years")
        limit = years if years and years > 1 else 1
        try:
            income = (
                await self._get(f"/income-statement/{ticker}", params={"limit": limit})
            ).json()
            balance = (
                await self._get(f"/balance-sheet-statement/{ticker}", params={"limit": 1})
            ).json()
            profile = (await self._get(f"/profile/{ticker}")).json()
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"FMP API error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"FMP fetch failed for '{ticker}': {e}") from e

        bal = balance[0] if balance else {}
        prof = profile[0] if profile else {}

        if years and years > 1 and len(income) > 1:
            data: dict[str, Any] = {
                "yearly_data": [
                    self._build_single_year_data(inc_i, bal, prof)
                    for inc_i in income
                ],
            }
        else:
            inc = income[0] if income else {}
            data = self._build_single_year_data(inc, bal, prof)

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _build_single_year_data(inc: dict[str, Any], bal: dict[str, Any], prof: dict[str, Any]) -> dict[str, Any]:
        """Extract a flat dict of normalized financial fields for one year."""
        return {
            "revenue": inc.get("revenue"),
            "ebitda": inc.get("ebitda"),
            "net_income": inc.get("netIncome"),
            "gross_margin": (
                inc["grossProfit"] / inc["revenue"]
                if inc.get("grossProfit") and inc.get("revenue")
                else None
            ),
            "operating_margin": (
                inc["operatingIncome"] / inc["revenue"]
                if inc.get("operatingIncome") and inc.get("revenue")
                else None
            ),
            "depreciation_amortization": inc.get("depreciationAndAmortization"),
            "rd_expense": inc.get("researchAndDevelopmentExpenses"),
            "sga_expense": inc.get("sellingGeneralAndAdministrative"),
            "interest_expense": inc.get("interestExpense"),
            "total_debt": bal.get("totalDebt", 0),
            "total_cash": bal.get("cashAndCashEquivalents", 0),
            "market_cap": prof.get("mktCap"),
            "shares_outstanding": (
                int(prof["mktCap"] / prof["price"])
                if prof.get("mktCap") and prof.get("price")
                else None
            ),
            "pe_ratio": (
                prof["price"] / (inc["netIncome"] / int(prof["mktCap"] / prof["price"]))
                if inc.get("netIncome")
                and prof.get("mktCap")
                and prof.get("price")
                and inc["netIncome"] > 0
                else None
            ),
            "beta": prof.get("beta"),
            "current_price": prof.get("price"),
            "company_name": prof.get("companyName"),
            "industry": prof.get("industry"),
            "sector": prof.get("sector"),
        }

    async def _fetch_news(self, ticker: str) -> DataResult:
        """Fetch recent news articles for a ticker from FMP /stock_news endpoint."""
        try:
            resp = await self._get("/stock_news", params={"tickers": ticker, "limit": 20})
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout fetching news for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"FMP API error fetching news for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"FMP news fetch failed for '{ticker}': {e}") from e

        raw: list[dict[str, Any]] = resp.json()
        news_items = [
            {
                "title": item.get("title", ""),
                "source": item.get("site", ""),
                "published": item.get("publishedDate", ""),
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

    async def _fetch_earnings(self, ticker: str) -> DataResult:
        """Fetch earnings surprises from FMP /earnings-surprises/{ticker}."""
        try:
            resp = await self._get(f"/earnings-surprises/{ticker}")
        except httpx.TimeoutException as e:
            raise ProviderError(f"FMP timeout fetching earnings for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"FMP API error fetching earnings for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"FMP earnings fetch failed for '{ticker}': {e}") from e

        raw: list[dict[str, Any]] = resp.json()
        earnings_history = [
            {
                "date": item.get("date", ""),
                "eps_actual": item.get("epsActual"),
                "eps_estimated": item.get("epsEstimated"),
                "revenue_actual": item.get("revenueActual"),
                "revenue_estimated": item.get("revenueEstimated"),
            }
            for item in raw
            if item.get("epsActual") is not None and item.get("epsEstimated") is not None
        ]
        return DataResult(
            data={"earnings_history": earnings_history},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.EARNINGS,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make authenticated, rate-limited GET request to FMP API.

        Serialises concurrent calls via asyncio.Lock and enforces a minimum
        inter-request interval (_MIN_INTERVAL) to avoid per-minute burst limits.
        """
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()
            p: dict[str, Any] = {"apikey": self._api_key}
            if params:
                p.update(params)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE_URL}{path}", params=p)
                resp.raise_for_status()
                return resp
