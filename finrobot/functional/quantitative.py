import os
import json
import pickle
import backtrader as bt
import yfinance as yf
from typing import Annotated, List, Tuple
from functools import wraps


class BackTraderUtils:

    def back_test(
        ticker_symbol: Annotated[
            str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"
        ],
        start_date: Annotated[
            str, "Start date of the historical data in 'YYYY-MM-DD' format"
        ],
        end_date: Annotated[
            str, "End date of the historical data in 'YYYY-MM-DD' format"
        ],
        strategy: Annotated[
            str, "BackTrader Strategy class to be backtested. module:class"
        ],
        params: Annotated[
            dict,
            "Additional parameters to be passed to the strategy class. E.g. {'fast': 10, 'slow': 30} for SMACross.",
        ] = {},
    ) -> str:
        """
        Use the Backtrader library to backtest a trading strategy on historical stock data.
        """
        cerebro = bt.Cerebro()

        # Deserialize and Add a strategy
        with open(os.path.join(load_dir, "strategy.pkl"), "rb") as f:
            strategy_func = pickle.load(f)

        with open(os.path.join(load_dir, "config.json"), "r") as f:
            loaded_params = json.load(f)
            strategy_class = strategy_func(**loaded_params)

        cerebro.addstrategy(strategy_class)

        # Create a data feed
        data = bt.feeds.PandasData(
            dataname=yf.download(ticker_symbol, start_date, end_date, auto_adjust=True)
        )
        cerebro.adddata(data)  # Add the data feed

        cerebro.run()  # run it all
        cerebro.plot()  # and plot it with a single command

        return "Back Test Finished."


if __name__ == "__main__":
    # Example usage:
    start_date = "2011-01-01"
    end_date = "2012-12-31"
    ticker = "MSFT"
    BackTraderUtils.create_sma_cross(10, 30, "sma_cross")
    BackTraderUtils.back_test(ticker, start_date, end_date, "sma_cross")
