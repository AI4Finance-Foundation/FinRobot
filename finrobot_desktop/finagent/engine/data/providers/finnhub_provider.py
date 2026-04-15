from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.types import DataType

_BASE_URL = "https://finnhub.io/api/v1"
_SUPPORTED = [DataType.FINANCIALS, DataType.PROFILE, DataType.NEWS]
_TIMEOUT = 15.0
_MIN_INTERVAL = 1.1  # Finnhub free tier: 60 req/min → 1 req/sec; 1.1s adds 10% buffer


class FinnhubProvider(DataProvider):
    """DataProvider backed by Finnhub API.

    Provides company profiles, basic financials, and SEC-reported data.
    API key required — get one at https://finnhub.io/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0

    @property
    def name(self) -> str:
        return "finnhub"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    @property
    def financials_fields(self) -> set[str]:
        return {
            "revenue", "ebitda", "net_income", "market_cap", "shares_outstanding",
            "gross_margin", "operating_margin", "depreciation_amortization",
            "total_debt", "total_cash",
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
            parsed = [
                self._parse_filing(filing, profile) for filing in filings[:years]
            ]
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

        mkt_cap_millions = profile.get("marketCapitalization", 0)
        shares_millions = profile.get("shareOutstanding", 0)

        revenue = _find_concept("ic", "Revenues")
        net_income = _find_concept("ic", "NetIncomeLoss")
        da = _find_concept("ic", "DepreciationAndAmortization")
        operating_income = _find_concept("ic", "OperatingIncomeLoss")
        cogs = _find_concept("ic", "CostOfGoodsAndServicesSold")
        total_debt = _find_concept("bs", "LongTermDebt") or 0
        total_cash = _find_concept("bs", "CashAndCashEquivalentsAtCarryingValue") or 0

        return {
            "revenue": revenue,
            "ebitda": (
                (operating_income or 0) + (da or 0) if operating_income is not None else None
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
        }

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
                "published": datetime.fromtimestamp(
                    item["datetime"], tz=timezone.utc
                ).isoformat()
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
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_BASE_URL}{path}", params=params or {}, headers=headers
                )
                resp.raise_for_status()
                return resp
