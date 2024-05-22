import os
import json
import importlib
import yfinance as yf
import backtrader as bt
from backtrader.strategies import SMA_CrossOver
from typing import Annotated, List, Tuple
from matplotlib import pyplot as plt
from pprint import pformat
from IPython import get_ipython


class DeployedCapitalAnalyzer(bt.Analyzer):
    def start(self):
        self.deployed_capital = []
        self.initial_cash = self.strategy.broker.get_cash()  # Initial cash in account

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.deployed_capital.append(order.executed.price * order.executed.size)
            elif order.issell():
                self.deployed_capital.append(order.executed.price * order.executed.size)

    def stop(self):
        total_deployed = sum(self.deployed_capital)
        final_cash = self.strategy.broker.get_value()
        net_profit = final_cash - self.initial_cash
        if total_deployed > 0:
            self.retn = net_profit / total_deployed
        else:
            self.retn = 0

    def get_analysis(self):
        return {"return_on_deployed_capital": self.retn}


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
        strategy_params: Annotated[
            str,
            "Additional parameters to be passed to the strategy class formatted as json string. E.g. {'fast': 10, 'slow': 30} for SMACross.",
        ] = "",
        sizer: Annotated[
            int | str | None,
            "Sizer used for backtesting. Can be a fixed number or a custom Sizer class. If input is integer, a corresponding fixed sizer will be applied. If custom, provide module path and class name as a string like 'my_module:TestSizer'.",
        ] = None,
        sizer_params: Annotated[
            str,
            "Additional parameters to be passed to the sizer class formatted as json string.",
        ] = "",
        indicator: Annotated[
            str | None,
            "Custom indicator class added to strategy. Provide module path and class name as a string like 'my_module:TestIndicator'.",
        ] = None,
        indicator_params: Annotated[
            str,
            "Additional parameters to be passed to the indicator class formatted as json string.",
        ] = "",
        cash: Annotated[
            float, "Initial cash amount for the backtest. Default to 10000.0"
        ] = 10000.0,
        save_fig: Annotated[
            str | None, "Path to save the plot of backtest results. Default to None."
        ] = None,
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

        strategy_params = json.loads(strategy_params) if strategy_params else {}
        cerebro.addstrategy(strategy_class, **strategy_params)

        # Create a data feed
        data = bt.feeds.PandasData(
            dataname=yf.download(ticker_symbol, start_date, end_date, auto_adjust=True)
        )
        cerebro.adddata(data)  # Add the data feed
        # Set our desired cash start
        cerebro.broker.setcash(cash)

        # Set the size of the trades
        if sizer is not None:
            if isinstance(sizer, int):
                cerebro.addsizer(bt.sizers.FixedSize, stake=sizer)
            else:
                assert (
                    ":" in sizer
                ), "Custom sizer should be module path and class name separated by a colon."
                module_path, class_name = sizer.split(":")
                module = importlib.import_module(module_path)
                sizer_class = getattr(module, class_name)
                sizer_params = json.loads(sizer_params) if sizer_params else {}
                cerebro.addsizer(sizer_class, **sizer_params)

        # Set additional indicator
        if indicator is not None:
            assert (
                ":" in indicator
            ), "Custom indicator should be module path and class name separated by a colon."
            module_path, class_name = indicator.split(":")
            module = importlib.import_module(module_path)
            indicator_class = getattr(module, class_name)
            indicator_params = json.loads(indicator_params) if indicator_params else {}
            cerebro.addindicator(indicator_class, **indicator_params)

        # Attach analyzers
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe_ratio")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="draw_down")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
        # cerebro.addanalyzer(DeployedCapitalAnalyzer, _name="deployed_capital")

        stats_dict = {"Starting Portfolio Value:": cerebro.broker.getvalue()}

        results = cerebro.run()  # run it all
        first_strategy = results[0]

        # Access analysis results
        stats_dict["Final Portfolio Value"] = cerebro.broker.getvalue()
        # stats_dict["Deployed Capital"] = pformat(
        #     first_strategy.analyzers.deployed_capital.get_analysis(), indent=4
        # )
        stats_dict["Sharpe Ratio"] = (
            first_strategy.analyzers.sharpe_ratio.get_analysis()
        )
        stats_dict["Drawdown"] = first_strategy.analyzers.draw_down.get_analysis()
        stats_dict["Returns"] = first_strategy.analyzers.returns.get_analysis()
        stats_dict["Trade Analysis"] = (
            first_strategy.analyzers.trade_analyzer.get_analysis()
        )

        if save_fig:
            directory = os.path.dirname(save_fig)
            if directory:
                os.makedirs(directory, exist_ok=True)
            plt.figure(figsize=(12, 8))
            cerebro.plot()
            plt.savefig(save_fig)
            plt.close()

        return "Back Test Finished. Results: \n" + pformat(stats_dict, indent=2)


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
