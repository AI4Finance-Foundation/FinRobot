import asyncio
from datetime import datetime, timezone

import yfinance as yf

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

# Reduce "Too Many Requests" errors from Yahoo Finance
try:
    yf.set_tz_cache_dir("/tmp/yf_cache")
except Exception:
    pass  # non-critical, ignore if not supported

_SUPPORTED = ["financials", "price", "news"]
_CALL_DELAY = 1.0  # seconds between the info fetch and subsequent calls
_MAX_RETRIES = 3  # retry attempts on rate-limit errors
_RETRY_DELAYS = [2, 5, 10]  # seconds to wait before each retry


def _make_ticker(symbol: str) -> yf.Ticker:
    """Create a Ticker. Let yfinance use its internal curl_cffi session."""
    return yf.Ticker(symbol)


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "too many requests" in msg or "rate limit" in msg or "429" in msg


class YFinanceProvider(DataProvider):
    """DataProvider backed by yfinance. Free, no API key required."""

    @property
    def name(self) -> str:
        return "yfinance"

    def capabilities(self) -> list[str]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        if data_type == "filings":
            raise ProviderError(
                "data_type 'filings' is not supported by yfinance. "
                "SEC EDGAR provider will be added in P2b."
            )
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by yfinance. Supported: {_SUPPORTED}"
            )

        # Fetch and validate ticker info with retry on rate limiting.
        # info is passed to sub-methods to avoid a redundant second HTTP call.
        info = None
        t = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                t = await asyncio.to_thread(_make_ticker, ticker)
                info = await asyncio.to_thread(lambda: t.info)
                if not info or (
                    info.get("regularMarketPrice") is None
                    and info.get("currentPrice") is None
                    and info.get("marketCap") is None
                ):
                    if len(info) <= 1:
                        raise ProviderError(f"Ticker '{ticker}' not found or returned no data")
                break  # success
            except ProviderError:
                raise
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < _MAX_RETRIES:
                    wait = _RETRY_DELAYS[attempt]
                    await asyncio.sleep(wait)
                    continue
                raise ProviderError(f"Failed to fetch ticker '{ticker}': {e}") from e

        if data_type == "financials":
            years_kwarg = kwargs.get("years")
            if years_kwarg and years_kwarg > 1:
                result = await self._fetch_historical_financials(ticker, info, t, years_kwarg)
            else:
                result = self._fetch_financials(ticker, info)
        elif data_type == "price":
            await asyncio.sleep(_CALL_DELAY)
            result = await self._fetch_price(ticker, t, info)
        elif data_type == "news":
            await asyncio.sleep(_CALL_DELAY)
            result = await self._fetch_news(ticker, t)

        return result

    def _fetch_financials(self, ticker: str, info: dict) -> DataResult:
        try:
            data = {
                "revenue": info.get("totalRevenue"),
                "ebitda": info.get("ebitda"),
                "net_income": info.get("netIncomeToCommon"),
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "pe_ratio": info.get("trailingPE"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "total_debt": info.get("totalDebt", 0),
                "total_cash": info.get("totalCash", 0),
            }
        except Exception as e:
            raise ProviderError(f"Failed to fetch financials for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_historical_financials(
        self, ticker: str, info: dict, t: yf.Ticker, years: int
    ) -> DataResult:
        """Fetch multi-year financials from income_stmt DataFrame.

        Falls back to single-year (_fetch_financials) if income_stmt is empty.
        """
        try:
            income_stmt = await asyncio.to_thread(lambda: t.income_stmt)
        except Exception:
            return self._fetch_financials(ticker, info)

        if income_stmt is None or income_stmt.empty:
            return self._fetch_financials(ticker, info)

        # Columns are fiscal-year-end dates, most recent first.
        cols = income_stmt.columns[:years]
        yearly_data = []
        for col in cols:
            series = income_stmt[col]
            revenue = series.get("Total Revenue")
            gross_profit = series.get("Gross Profit")
            operating_income = series.get("Operating Income")
            entry = {
                "fiscal_year": str(col.date()) if hasattr(col, "date") else str(col),
                "revenue": revenue,
                "ebitda": series.get("EBITDA"),
                "net_income": series.get("Net Income"),
                "gross_profit": gross_profit,
                "operating_income": operating_income,
                "gross_margin": (
                    gross_profit / revenue if revenue and gross_profit else None
                ),
                "operating_margin": (
                    operating_income / revenue if revenue and operating_income else None
                ),
            }
            yearly_data.append(entry)

        return DataResult(
            data={"yearly_data": yearly_data},
            provider=self.name,
            ticker=ticker,
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_price(self, ticker: str, t: yf.Ticker, info: dict) -> DataResult:
        try:
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            hist = await asyncio.to_thread(t.history, period="1y")
            price_history = []
            for date, row in hist.iterrows():
                price_history.append(
                    {
                        "date": str(date.date()),
                        "open": row["Open"],
                        "high": row["High"],
                        "low": row["Low"],
                        "close": row["Close"],
                        "volume": row["Volume"],
                    }
                )
        except Exception as e:
            raise ProviderError(f"Failed to fetch price for '{ticker}': {e}") from e

        return DataResult(
            data={"current_price": current_price, "price_history": price_history},
            provider=self.name,
            ticker=ticker,
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def _fetch_news(self, ticker: str, t: yf.Ticker) -> DataResult:
        try:
            raw_news = await asyncio.to_thread(lambda: t.news or [])
            headlines = []
            for item in raw_news:
                content = item.get("content", {})
                title = content.get("title") or item.get("title", "")
                if title:
                    headlines.append(title)
        except Exception as e:
            raise ProviderError(f"Failed to fetch news for '{ticker}': {e}") from e

        return DataResult(
            data={"headlines": headlines},
            provider=self.name,
            ticker=ticker,
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
