from __future__ import annotations

from datetime import datetime, timezone

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

_BASE_URL = "https://finnhub.io/api/v1"
_SUPPORTED = ["financials", "profile"]
_TIMEOUT = 15.0


class FinnhubProvider(DataProvider):
    """DataProvider backed by Finnhub API.

    Provides company profiles, basic financials, and SEC-reported data.
    API key required — get one at https://finnhub.io/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "finnhub"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by Finnhub. Supported: {_SUPPORTED}"
            )
        try:
            if data_type == "financials":
                data = await self._fetch_financials(ticker)
            elif data_type == "profile":
                data = await self._fetch_profile(ticker)
            else:
                raise ProviderError(f"Unhandled data_type: {data_type}")
        except httpx.TimeoutException as e:
            raise ProviderError(f"Finnhub timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Finnhub API error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Finnhub fetch failed for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_financials(self, ticker: str) -> dict:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()

        reported = (
            await self._get(
                "/stock/financials-reported",
                params={"symbol": ticker, "freq": "annual"},
            )
        ).json()

        # Extract latest annual filing
        filings = reported.get("data", [])
        latest = filings[0] if filings else {}
        report = latest.get("report", {})

        def _find_concept(section: str, concept: str) -> float | None:
            items = report.get(section, [])
            for item in items:
                if item.get("concept") == concept:
                    return item.get("value")
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

    async def _fetch_profile(self, ticker: str) -> dict:
        profile = (await self._get("/stock/profile2", params={"symbol": ticker})).json()
        return {
            "company_name": profile.get("name"),
            "industry": profile.get("finnhubIndustry"),
            "market_cap": (profile.get("marketCapitalization", 0) or 0) * 1_000_000,
            "shares_outstanding": (profile.get("shareOutstanding", 0) or 0) * 1_000_000,
            "exchange": profile.get("exchange"),
        }

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Make authenticated GET request to Finnhub API."""
        headers = {"X-Finnhub-Token": self._api_key}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=params or {}, headers=headers)
            resp.raise_for_status()
            return resp
