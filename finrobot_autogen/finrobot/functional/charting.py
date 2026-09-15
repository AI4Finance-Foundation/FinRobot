import os
import mplfinance as mpf
import pandas as pd

from matplotlib import pyplot as plt
from typing import Annotated, List, Tuple
from pandas import DateOffset
from datetime import datetime, timedelta

from ..data_source.yfinance_utils import YFinanceUtils


class MplFinanceUtils:

    def plot_stock_price_chart(
        ticker_symbol: Annotated[
            str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"
        ],
        start_date: Annotated[
            str, "Start date of the historical data in 'YYYY-MM-DD' format"
        ],
        end_date: Annotated[
            str, "End date of the historical data in 'YYYY-MM-DD' format"
        ],
        save_path: Annotated[str, "File path where the plot should be saved"],
        verbose: Annotated[
            str, "Whether to print stock data to console. Default to False."
        ] = False,
        type: Annotated[
            str,
            "Type of the plot, should be one of 'candle','ohlc','line','renko','pnf','hollow_and_filled'. Default to 'candle'",
        ] = "candle",
        style: Annotated[
            str,
            "Style of the plot, should be one of 'default','classic','charles','yahoo','nightclouds','sas','blueskies','mike'. Default to 'default'.",
        ] = "default",
        mav: Annotated[
            int | List[int] | Tuple[int, ...] | None,
            "Moving average window(s) to plot on the chart. Default to None.",
        ] = None,
        show_nontrading: Annotated[
            bool, "Whether to show non-trading days on the chart. Default to False."
        ] = False,
    ) -> str:
        """
        Plot a stock price chart using mplfinance for the specified stock and time period,
        and save the plot to a file.
        """
        # Fetch historical data
        stock_data = YFinanceUtils.get_stock_data(ticker_symbol, start_date, end_date)
        if verbose:
            print(stock_data.to_string())

        params = {
            "type": type,
            "style": style,
            "title": f"{ticker_symbol} {type} chart",
            "ylabel": "Price",
            "volume": True,
            "ylabel_lower": "Volume",
            "mav": mav,
            "show_nontrading": show_nontrading,
            "savefig": save_path,
        }
        # Using dictionary comprehension to filter out None values (MplFinance does not accept None values)
        filtered_params = {k: v for k, v in params.items() if v is not None}

        # Plot chart
        mpf.plot(stock_data, **filtered_params)

        return f"{type} chart saved to <img {save_path}>"


class ReportChartUtils:

    def get_share_performance(
        ticker_symbol: Annotated[
            str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"
        ],
        filing_date: Annotated[str | datetime, "filing date in 'YYYY-MM-DD' format"],
        save_path: Annotated[str, "File path where the plot should be saved"],
    ) -> str:
        """Plot the stock performance of a company compared to the S&P 500 over the past year."""
        if isinstance(filing_date, str):
            filing_date = datetime.strptime(filing_date, "%Y-%m-%d")

        def fetch_stock_data(ticker):
            start = (filing_date - timedelta(days=365)).strftime("%Y-%m-%d")
            end = filing_date.strftime("%Y-%m-%d")
            historical_data = YFinanceUtils.get_stock_data(ticker, start, end)
            # hist = stock.history(period=period)
            return historical_data["Close"]

        target_close = fetch_stock_data(ticker_symbol)
        sp500_close = fetch_stock_data("^GSPC")
        info = YFinanceUtils.get_stock_info(ticker_symbol)

        # 计算变化率
        company_change = (
            (target_close - target_close.iloc[0]) / target_close.iloc[0] * 100
        )
        sp500_change = (sp500_close - sp500_close.iloc[0]) / sp500_close.iloc[0] * 100

        # 计算额外的日期点
        start_date = company_change.index.min()
        four_months = start_date + DateOffset(months=4)
        eight_months = start_date + DateOffset(months=8)
        end_date = company_change.index.max()

        # 准备绘图
        plt.rcParams.update({"font.size": 20})  # 调整为更大的字体大小
        plt.figure(figsize=(14, 7))
        plt.plot(
            company_change.index,
            company_change,
            label=f'{info["shortName"]} Change %',
            color="blue",
        )
        plt.plot(
            sp500_change.index, sp500_change, label="S&P 500 Change %", color="red"
        )

        # 设置标题和标签
        plt.title(f'{info["shortName"]} vs S&P 500 - Change % Over the Past Year')
        plt.xlabel("Date")
        plt.ylabel("Change %")

        # 设置x轴刻度标签
        plt.xticks(
            [start_date, four_months, eight_months, end_date],
            [
                start_date.strftime("%Y-%m"),
                four_months.strftime("%Y-%m"),
                eight_months.strftime("%Y-%m"),
                end_date.strftime("%Y-%m"),
            ],
        )

        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        # plt.show()
        plot_path = (
            f"{save_path}/stock_performance.png"
            if os.path.isdir(save_path)
            else save_path
        )
        plt.savefig(plot_path)
        plt.close()
        return f"last year stock performance chart saved to <img {plot_path}>"

    def get_pe_eps_performance(
        ticker_symbol: Annotated[
            str, "Ticker symbol of the stock (e.g., 'AAPL' for Apple)"
        ],
        filing_date: Annotated[str | datetime, "filing date in 'YYYY-MM-DD' format"],
        years: Annotated[int, "number of years to search from, default to 4"] = 4,
        save_path: Annotated[str, "File path where the plot should be saved"] = None,
    ) -> str:
        """Plot the PE ratio and EPS performance of a company over the past n years."""
        if isinstance(filing_date, str):
            filing_date = datetime.strptime(filing_date, "%Y-%m-%d")

        ss = YFinanceUtils.get_income_stmt(ticker_symbol)
        eps = ss.loc["Diluted EPS", :]

        # 获取过去5年的历史数据
        # historical_data = self.stock.history(period="5y")
        days = round((years + 1) * 365.25)
        start = (filing_date - timedelta(days=days)).strftime("%Y-%m-%d")
        end = filing_date.strftime("%Y-%m-%d")
        historical_data = YFinanceUtils.get_stock_data(ticker_symbol, start, end)

        # 指定的日期，并确保它们都是UTC时区的
        dates = pd.to_datetime(eps.index[::-1], utc=True)

        # 为了确保我们能够找到最接近的股市交易日，我们将转换日期并查找最接近的日期
        results = {}
        for date in dates:
            # 如果指定日期不是交易日，使用bfill和ffill找到最近的交易日股价
            if date not in historical_data.index:
                close_price = historical_data.asof(date)
            else:
                close_price = historical_data.loc[date]

            results[date] = close_price["Close"]

        pe = [p / e for p, e in zip(results.values(), eps.values[::-1])]
        dates = eps.index[::-1]
        eps = eps.values[::-1]

        info = YFinanceUtils.get_stock_info(ticker_symbol)

        # 创建图形和轴对象
        fig, ax1 = plt.subplots(figsize=(14, 7))
        plt.rcParams.update({"font.size": 20})  # 调整为更大的字体大小

        # 绘制市盈率
        color = "tab:blue"
        ax1.set_xlabel("Date")
        ax1.set_ylabel("PE Ratio", color=color)
        ax1.plot(dates, pe, color=color)
        ax1.tick_params(axis="y", labelcolor=color)
        ax1.grid(True)

        # 创建与ax1共享x轴的第二个轴对象
        ax2 = ax1.twinx()
        color = "tab:red"
        ax2.set_ylabel("EPS", color=color)  # 第二个y轴的标签
        ax2.plot(dates, eps, color=color)
        ax2.tick_params(axis="y", labelcolor=color)

        # 设置标题和x轴标签角度
        plt.title(f'{info["shortName"]} PE Ratios and EPS Over the Past {years} Years')
        plt.xticks(rotation=45)

        # 设置x轴刻度标签
        plt.xticks(dates, [d.strftime("%Y-%m") for d in dates])

        plt.tight_layout()
        # plt.show()
        plot_path = (
            f"{save_path}/pe_performance.png" if os.path.isdir(save_path) else save_path
        )
        plt.savefig(plot_path)
        plt.close()
        return f"pe performance chart saved to <img {plot_path}>"


if __name__ == "__main__":
    # Example usage:
    start_date = "2024-03-01"
    end_date = "2024-04-01"
    save_path = "AAPL_candlestick_chart.png"
    MplFinanceUtils.plot_candlestick_chart("AAPL", start_date, end_date, save_path)
