import yfinance as yf
from typing import Annotated


class YFinanceUtils:

    def get_stock_data(
        symbol: Annotated[str, "ticker symbol"],
        start_date: Annotated[str, "start date for retrieving stock price data, YYYY-mm-dd"],
        end_date: Annotated[str, "end date for retrieving stock price data, YYYY-mm-dd"],
        ) -> str:
        
        stock_data = yf.download(symbol, start=start_date, end=end_date)

        return stock_data

