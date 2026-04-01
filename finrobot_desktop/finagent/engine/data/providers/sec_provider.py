from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
_SUPPORTED = ["filings"]
_TIMEOUT = 15.0
_MIN_REQUEST_INTERVAL = 0.11  # SEC rate limit: 10 req/s -> at least 100ms between requests


class SECEdgarProvider(DataProvider):
    """DataProvider for SEC EDGAR (10-K/10-Q filings).

    Free, no API key required, but requires a User-Agent header
    (SEC policy: 'CompanyName AdminEmail').
    Rate limit: 10 requests/second.
    """

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._last_request: float = 0

    @property
    def name(self) -> str:
        return "sec_edgar"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by SEC EDGAR. Supported: {_SUPPORTED}"
            )
        try:
            data = await self._fetch_filings(ticker)
        except httpx.TimeoutException as e:
            raise ProviderError(f"SEC EDGAR timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"SEC EDGAR API error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"SEC EDGAR fetch failed for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_filings(self, ticker: str) -> dict:
        """Fetch latest 10-K filing metadata from SEC EDGAR."""
        cik = await self._resolve_cik(ticker)
        submissions = (await self._get(f"{_SUBMISSIONS_URL}/CIK{cik}.json")).json()

        filings = submissions.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        # Find latest 10-K
        latest_10k_idx = None
        for i, form in enumerate(forms):
            if form == "10-K":
                latest_10k_idx = i
                break

        if latest_10k_idx is None:
            return {
                "company_name": submissions.get("name"),
                "cik": cik,
                "latest_10k_date": None,
                "latest_10k_accession": None,
                "has_10k": False,
            }

        return {
            "company_name": submissions.get("name"),
            "cik": cik,
            "latest_10k_date": dates[latest_10k_idx],
            "latest_10k_accession": accessions[latest_10k_idx],
            "has_10k": True,
        }

    async def _resolve_cik(self, ticker: str) -> str:
        """Resolve ticker to zero-padded CIK."""
        tickers = (await self._get("https://www.sec.gov/files/company_tickers.json")).json()
        for entry in tickers.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        raise ProviderError(f"Could not resolve CIK for ticker '{ticker}'")

    async def _get(self, url: str) -> httpx.Response:
        """Make rate-limited GET request with required User-Agent."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            self._last_request = asyncio.get_event_loop().time()
            resp.raise_for_status()
            return resp
