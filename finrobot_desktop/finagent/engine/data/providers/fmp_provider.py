from __future__ import annotations

from datetime import datetime, timezone

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

_BASE_URL = "https://financialmodelingprep.com/api/v3"
_SUPPORTED = ["financials"]
_TIMEOUT = 15.0


class FMPProvider(DataProvider):
    """DataProvider backed by Financial Modeling Prep API.

    Provides D&A, R&D, SGA, and other detailed financials that yfinance lacks.
    API key required — get one at https://financialmodelingprep.com/
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "fmp"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by FMP. Supported: {_SUPPORTED}"
            )
        try:
            income = (await self._get(f"/income-statement/{ticker}", params={"limit": 1})).json()
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
        except Exception as e:
            raise ProviderError(f"FMP fetch failed for '{ticker}': {e}") from e

        inc = income[0] if income else {}
        bal = balance[0] if balance else {}
        prof = profile[0] if profile else {}

        # Key normalization: FMP camelCase keys → common snake_case keys
        data = {
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

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """Make authenticated GET request to FMP API."""
        p: dict = {"apikey": self._api_key}
        if params:
            p.update(params)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp
