import yfinance as yf
import mplfinance as mpf
from typing import Annotated

from ..data_source.yfinance_utils import YFinanceUtils

def plot_candlestick_chart(
    ticker_symbol: Annotated[str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"],
    start_date: Annotated[str, "Start date of the historical data in 'YYYY-MM-DD' format"],
    end_date: Annotated[str, "End date of the historical data in 'YYYY-MM-DD' format"],
    save_path: Annotated[str, "File path where the plot should be saved"]
):
    """
    Plot a candlestick chart using mplfinance for the specified stock and time period,
    and save the plot to a file.
    """
    # Fetch historical data
    stock_data = YFinanceUtils.get_stock_data(ticker_symbol, start_date, end_date)
    print(stock_data)

    # Plot candlestick chart
    mpf.plot(stock_data, type='candle', style='charles',
             title=f'{ticker_symbol} Candlestick Chart',
             ylabel='Price', volume=True, ylabel_lower='Volume', show_nontrading=True,
             savefig=save_path)

    return f"Candlestick chart saved to <img {save_path}>"


# Example usage:
start_date = '2024-03-01'
end_date = '2024-04-01'
save_path = 'AAPL_candlestick_chart.png'
plot_candlestick_chart('AAPL', start_date, end_date, save_path)