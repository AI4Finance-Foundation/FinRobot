from datetime import datetime, timezone

import yfinance as yf

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError

# Reduce "Too Many Requests" errors from Yahoo Finance
try:
    yf.set_tz_cache_dir("/tmp/yf_cache")
except Exception:
    pass  # non-critical, ignore if not supported

_SUPPORTED = ["financials", "price", "news"]
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _make_ticker(symbol: str) -> yf.Ticker:
    """Create a Ticker with User-Agent header to avoid rate limiting."""
    t = yf.Ticker(symbol)
    try:
        if hasattr(t, "_session") and t._session is not None:
            t._session.headers.update({"User-Agent": _USER_AGENT})
    except Exception:
        pass  # header injection is best-effort
    return t


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
                f"data_type 'filings' is not supported by yfinance. "
                f"SEC EDGAR provider will be added in P2b."
            )
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by yfinance. "
                f"Supported: {_SUPPORTED}"
            )

        try:
            t = _make_ticker(ticker)
            # Validate ticker by checking if info is non-empty
            info = t.info
            if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None and info.get("marketCap") is None:
                # yfinance returns a minimal dict for invalid tickers
                if len(info) <= 1:
                    raise ProviderError(f"Ticker '{ticker}' not found or returned no data")
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Failed to fetch ticker '{ticker}': {e}") from e

        if data_type == "financials":
            return self._fetch_financials(ticker, t)
        elif data_type == "price":
            return self._fetch_price(ticker, t)
        elif data_type == "news":
            return self._fetch_news(ticker, t)

    def _fetch_financials(self, ticker: str, t: yf.Ticker) -> DataResult:
        try:
            info = t.info
            data = {
                "revenue": info.get("totalRevenue"),
                "ebitda": info.get("ebitda"),
                "net_income": info.get("netIncomeToCommon"),
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "pe_ratio": info.get("trailingPE"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
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

    def _fetch_price(self, ticker: str, t: yf.Ticker) -> DataResult:
        try:
            info = t.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            hist = t.history(period="1y")
            price_history = []
            for date, row in hist.iterrows():
                price_history.append({
                    "date": str(date.date()),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row["Volume"],
                })
        except Exception as e:
            raise ProviderError(f"Failed to fetch price for '{ticker}': {e}") from e

        return DataResult(
            data={"current_price": current_price, "price_history": price_history},
            provider=self.name,
            ticker=ticker,
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )

    def _fetch_news(self, ticker: str, t: yf.Ticker) -> DataResult:
        try:
            raw_news = t.news or []
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
