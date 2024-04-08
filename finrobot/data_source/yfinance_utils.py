import yfinance as yf
from typing import Annotated
from pandas import DataFrame
from ..utils import save_output, SavePathType


class YFinanceUtils:

    def get_stock_data(
        symbol: Annotated[str, "ticker symbol"],
        start_date: Annotated[str, "start date for retrieving stock price data, YYYY-mm-dd"],
        end_date: Annotated[str, "end date for retrieving stock price data, YYYY-mm-dd"],
        save_path: SavePathType = None
    ) -> DataFrame:
        stock_data = yf.download(symbol, start=start_date, end=end_date)
        save_output(stock_data, f"Stock data for {symbol}", save_path)    
        return stock_data
    

if __name__ == '__main__':
    print(YFinanceUtils.get_stock_data("AAPL", "2021-01-01", "2021-12-31"))