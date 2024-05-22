import yfinance as yf
from typing import Annotated, Callable, Any, Optional
from pandas import DataFrame
from functools import wraps

from ..utils import save_output, SavePathType, decorate_all_methods


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
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"],
        start_date: Annotated[
            str, "start date for retrieving stock price data, YYYY-mm-dd"
        ],
        end_date: Annotated[
            str, "end date for retrieving stock price data, YYYY-mm-dd"
        ],
        save_path: SavePathType = None,
    ) -> DataFrame:
        stock_data = ticker.history(start=start_date, end=end_date)
        save_output(stock_data, f"Stock data for {ticker.ticker}", save_path)
        return stock_data

    def get_stock_info(
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"],
    ) -> dict:
        """Fetches and returns stock information."""
        stock_info = ticker.info
        return stock_info

    def get_company_info(
        self,
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns company information as a DataFrame."""
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
        self,
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns the dividends data as a DataFrame."""
        dividends = ticker.dividends
        if save_path:
            dividends.to_csv(save_path)
            print(f"Dividends for {ticker.ticker} saved to {save_path}")
        return dividends

    def get_income_stmt(
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"]
    ) -> DataFrame:
        """Fetches and returns the income statement of the company as a DataFrame."""
        income_stmt = ticker.financials
        return income_stmt

    def get_balance_sheet(
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"]
    ) -> DataFrame:
        """Fetches and returns the balance sheet of the company as a DataFrame."""
        balance_sheet = ticker.balance_sheet
        return balance_sheet

    def get_cash_flow(
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"]
    ) -> DataFrame:
        """Fetches and returns the cash flow statement of the company as a DataFrame."""
        cash_flow = ticker.cashflow
        return cash_flow

    def get_analyst_recommendations(
        ticker: Annotated[yf.Ticker, "Ticker object for the specified symbol"]
    ) -> tuple:
        """Fetches the latest analyst recommendations and returns the most common recommendation and its count."""
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
    # print(YFinanceUtils.get_stock_data("AAPL", "2021-01-01", "2021-12-31"))
    print(YFinanceUtils.get_stock_info("AAPL"))
