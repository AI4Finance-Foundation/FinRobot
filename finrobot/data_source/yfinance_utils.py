import yfinance as yf
from typing import Annotated, Callable, Any, Optional
from pandas import DataFrame
from functools import wraps

from ..utils import save_output, SavePathType, decorate_all_methods
from .cache_utils import get_cache_path, is_cache_valid, read_disk_cache, write_disk_cache, TTL_CONFIG

# In-memory cache for YFinance data to avoid redundant API calls
_yfinance_cache = {}


def init_ticker(func: Callable) -> Callable:
    """Decorator to initialize yf.Ticker and pass it to the function."""

    @wraps(func)
    def wrapper(symbol: Annotated[str, "ticker symbol"], *args, **kwargs) -> Any:
        ticker = yf.Ticker(symbol)
        return func(ticker, *args, **kwargs)

    return wrapper


@decorate_all_methods(init_ticker)
class YFinanceUtils:

    def get_stock_data(
        symbol: Annotated[str, "ticker symbol"],
        start_date: Annotated[
            str, "start date for retrieving stock price data, YYYY-mm-dd"
        ],
        end_date: Annotated[
            str, "end date for retrieving stock price data, YYYY-mm-dd"
        ],
        save_path: SavePathType = None,
    ) -> DataFrame:
        """retrieve stock price data for designated ticker symbol"""
        ticker = symbol
        stock_data = ticker.history(start=start_date, end=end_date)
        save_output(stock_data, f"Stock data for {ticker.ticker}", save_path)
        return stock_data

    def get_stock_info(
        symbol: Annotated[str, "ticker symbol"],
    ) -> dict:
        """Fetches and returns latest stock information."""
        ticker = symbol
        ticker_symbol = ticker.ticker

        # Check in-memory cache first
        cache_key = f"stock_info:{ticker_symbol}"
        if cache_key in _yfinance_cache:
            return _yfinance_cache[cache_key]

        # Check disk cache with TTL (1 day for stock info)
        disk_cache_path = get_cache_path("yfinance", cache_key)
        ttl = TTL_CONFIG.get("yfinance_info", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _yfinance_cache[cache_key] = cached_data
                return cached_data

        # Fetch from API
        stock_info = ticker.info

        # Cache the result
        if stock_info:
            _yfinance_cache[cache_key] = stock_info
            write_disk_cache(disk_cache_path, stock_info)

        return stock_info

    def get_company_info(
        symbol: Annotated[str, "ticker symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns company information as a DataFrame."""
        ticker = symbol
        info = ticker.info
        company_info = {
            "Company Name": info.get("shortName", "N/A"),
            "Industry": info.get("industry", "N/A"),
            "Sector": info.get("sector", "N/A"),
            "Country": info.get("country", "N/A"),
            "Website": info.get("website", "N/A"),
        }
        company_info_df = DataFrame([company_info])
        if save_path:
            company_info_df.to_csv(save_path)
            print(f"Company info for {ticker.ticker} saved to {save_path}")
        return company_info_df

    def get_stock_dividends(
        symbol: Annotated[str, "ticker symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns the latest dividends data as a DataFrame."""
        ticker = symbol
        dividends = ticker.dividends
        if save_path:
            dividends.to_csv(save_path)
            print(f"Dividends for {ticker.ticker} saved to {save_path}")
        return dividends

    def get_income_stmt(symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest income statement of the company as a DataFrame."""
        ticker = symbol
        ticker_symbol = ticker.ticker

        # Check in-memory cache first
        cache_key = f"income_stmt:{ticker_symbol}"
        if cache_key in _yfinance_cache:
            return _yfinance_cache[cache_key]

        # Check disk cache with TTL (7 days for financials)
        disk_cache_path = get_cache_path("yfinance", cache_key)
        ttl = TTL_CONFIG.get("yfinance_financials", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _yfinance_cache[cache_key] = cached_data
                return cached_data

        # Fetch from API
        income_stmt = ticker.financials

        # Cache the result
        if income_stmt is not None and not income_stmt.empty:
            _yfinance_cache[cache_key] = income_stmt
            write_disk_cache(disk_cache_path, income_stmt)

        return income_stmt

    def get_balance_sheet(symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest balance sheet of the company as a DataFrame."""
        ticker = symbol
        ticker_symbol = ticker.ticker

        # Check in-memory cache first
        cache_key = f"balance_sheet:{ticker_symbol}"
        if cache_key in _yfinance_cache:
            return _yfinance_cache[cache_key]

        # Check disk cache with TTL (7 days for financials)
        disk_cache_path = get_cache_path("yfinance", cache_key)
        ttl = TTL_CONFIG.get("yfinance_financials", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _yfinance_cache[cache_key] = cached_data
                return cached_data

        # Fetch from API
        balance_sheet = ticker.balance_sheet

        # Cache the result
        if balance_sheet is not None and not balance_sheet.empty:
            _yfinance_cache[cache_key] = balance_sheet
            write_disk_cache(disk_cache_path, balance_sheet)

        return balance_sheet

    def get_cash_flow(symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest cash flow statement of the company as a DataFrame."""
        ticker = symbol
        ticker_symbol = ticker.ticker

        # Check in-memory cache first
        cache_key = f"cash_flow:{ticker_symbol}"
        if cache_key in _yfinance_cache:
            return _yfinance_cache[cache_key]

        # Check disk cache with TTL (7 days for financials)
        disk_cache_path = get_cache_path("yfinance", cache_key)
        ttl = TTL_CONFIG.get("yfinance_financials", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _yfinance_cache[cache_key] = cached_data
                return cached_data

        # Fetch from API
        cash_flow = ticker.cashflow

        # Cache the result
        if cash_flow is not None and not cash_flow.empty:
            _yfinance_cache[cache_key] = cash_flow
            write_disk_cache(disk_cache_path, cash_flow)

        return cash_flow

    def get_analyst_recommendations(symbol: Annotated[str, "ticker symbol"]) -> tuple:
        """Fetches the latest analyst recommendations and returns the most common recommendation and its count."""
        ticker = symbol
        recommendations = ticker.recommendations
        if recommendations.empty:
            return None, 0  # No recommendations available

        # Assuming 'period' column exists and needs to be excluded
        row_0 = recommendations.iloc[0, 1:]  # Exclude 'period' column if necessary

        # Find the maximum voting result
        max_votes = row_0.max()
        majority_voting_result = row_0[row_0 == max_votes].index.tolist()

        return majority_voting_result[0], max_votes


if __name__ == "__main__":
    print(YFinanceUtils.get_stock_data("AAPL", "2021-01-01", "2021-12-31"))
    # print(YFinanceUtils.get_stock_data())
