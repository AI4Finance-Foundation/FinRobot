import json
import importlib
import yfinance as yf
import backtrader as bt
from backtrader.strategies import SMA_CrossOver
from typing import Annotated, List, Tuple
from matplotlib import pyplot as plt


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
            str,
            "BackTrader Strategy class to be backtested. Can be pre-defined or custom. Pre-defined options: 'SMA_CrossOver'. If custom, provide module path and class name as a string like 'my_module:TestStrategy'.",
        ],
        params: Annotated[
            str,
            "Additional parameters to be passed to the strategy class formatted as json string. E.g. {'fast': 10, 'slow': 30} for SMACross.",
        ] = {},
        cash: Annotated[
            float, "Initial cash amount for the backtest. Default to 10000.0"
        ] = 10000.0,
        stake_size: Annotated[int, "Fixed stake size for each trade. Default to 1"] = 1,
    ) -> str:
        """
        Use the Backtrader library to backtest a trading strategy on historical stock data.
        """
        cerebro = bt.Cerebro()

        if strategy == "SMA_CrossOver":
            strategy_class = SMA_CrossOver
        else:
            assert (
                ":" in strategy
            ), "Custom strategy should be module path and class name separated by a colon."
            module_path, class_name = strategy.split(":")
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, class_name)

        params = json.loads(params)
        cerebro.addstrategy(strategy_class, **params)

        # Create a data feed
        data = bt.feeds.PandasData(
            dataname=yf.download(ticker_symbol, start_date, end_date, auto_adjust=True)
        )
        cerebro.adddata(data)  # Add the data feed
        # Set our desired cash start
        cerebro.broker.setcash(cash)

        # Set the size of the trades
        cerebro.addsizer(bt.sizers.FixedSize, stake=stake_size)

        # Attach analyzers
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="mysharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="mydrawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="myreturns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="mytradeanalyzer")

        stats_dict = {"Starting Portfolio Value:": cerebro.broker.getvalue()}

        results = cerebro.run()  # run it all
        first_strategy = results[0]

        # Access analysis results
        stats_dict["Sharpe Ratio"] = first_strategy.analyzers.mysharpe.get_analysis()
        stats_dict["Drawdown"] = first_strategy.analyzers.mydrawdown.get_analysis()
        stats_dict["Returns"] = first_strategy.analyzers.myreturns.get_analysis()
        stats_dict["Trade Analysis"] = (
            first_strategy.analyzers.mytradeanalyzer.get_analysis()
        )
        stats_dict["Final Portfolio Value"] = cerebro.broker.getvalue()

        plt.figure()
        cerebro.plot()  # and plot it with a single command
        plt.show()

        return "Back Test Finished. Results: \n" + str(stats_dict)


if __name__ == "__main__":
    # Example usage:
    start_date = "2011-01-01"
    end_date = "2012-12-31"
    ticker = "MSFT"
    # BackTraderUtils.back_test(
    #     ticker, start_date, end_date, "SMA_CrossOver", {"fast": 10, "slow": 30}
    # )
    BackTraderUtils.back_test(
        ticker,
        start_date,
        end_date,
        "test_module:TestStrategy",
        {"exitbars": 5},
    )
