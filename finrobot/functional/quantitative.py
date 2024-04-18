import os
import json
import pickle
import backtrader as bt
import yfinance as yf
from typing import Annotated, List, Tuple
from functools import wraps



def save_strategy(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Call the original function that creates the strategy instance
        strategy_class = func(*args, **kwargs)
        
        # Serialize the instance
        filename = f'{func.__name__}.pkl'  # The name of the file is based on the function name
       
        with open(filename, 'wb') as f:
            pickle.dump(strategy_class, f)

        return f"Strategy Class saved to {filename}"
    
    return wrapper


def sma_cross(fast_period, slow_period):

    class SMACross(bt.Strategy):
        params = dict(
            pfast=fast_period,  # period for the fast moving average
            pslow=slow_period   # period for the slow moving average
        )

        def __init__(self):
            sma1 = bt.ind.SMA(period=self.p.pfast)  # fast moving average
            sma2 = bt.ind.SMA(period=self.p.pslow)  # slow moving average
            self.crossover = bt.ind.CrossOver(sma1, sma2)

        def next(self):
            if not self.position:  # not in the market
                if self.crossover > 0:  # if fast crosses slow to the upside
                    self.buy()  # enter long

            elif self.crossover < 0:  # in the market & cross to the downside
                self.close()  # close long position
    
    return SMACross


class BackTraderUtils:

    # @save_strategy
    def create_sma_cross(
        fast_period: Annotated[int, "Fast moving average period"],
        slow_period: Annotated[int, "Slow moving average period"],
        save_dir: Annotated[str, "Directory to save the serialized strategy and configs."],
    ) -> bt.Strategy:
        """
        Create a simple moving average crossover strategy.
        """
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, 'strategy.pkl'), 'wb') as f:
            pickle.dump(sma_cross, f)

        params = {'fast_period': fast_period, 'slow_period': slow_period}
        with open(os.path.join(save_dir, 'config.json'), 'w') as f:
            json.dump(params, f)

        return f"Strategy Class saved to {save_dir}"

    def back_test(
        ticker_symbol: Annotated[str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"],
        start_date: Annotated[str, "Start date of the historical data in 'YYYY-MM-DD' format"],
        end_date: Annotated[str, "End date of the historical data in 'YYYY-MM-DD' format"],
        load_dir: Annotated[str, "Directory to load the serialized strategy and configs from."],
    ) -> str:
        """
        Use the Backtrader library to backtest a trading strategy on historical stock data.
        """
        cerebro = bt.Cerebro()

        # Deserialize and Add a strategy
        with open(os.path.join(load_dir, 'strategy.pkl'), 'rb') as f:
            strategy_func = pickle.load(f)
        
        with open(os.path.join(load_dir, 'config.json'), 'r') as f:
            loaded_params = json.load(f)
            strategy_class = strategy_func(**loaded_params)

        cerebro.addstrategy(strategy_class)

        # Create a data feed
        data = bt.feeds.PandasData(
            dataname=yf.download(
                ticker_symbol, start_date, end_date, auto_adjust=True
            )
        )
        cerebro.adddata(data)  # Add the data feed

        cerebro.run()  # run it all
        cerebro.plot()  # and plot it with a single command

        return "Back Test Finished."


if __name__ == "__main__":
    # Example usage:
    start_date = '2011-01-01'
    end_date = '2012-12-31'
    ticker = 'MSFT'
    BackTraderUtils.create_sma_cross(10, 30, 'sma_cross')
    BackTraderUtils.back_test(ticker, start_date, end_date, 'sma_cross')