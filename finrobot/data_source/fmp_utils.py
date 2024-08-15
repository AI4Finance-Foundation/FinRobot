import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ..utils import decorate_all_methods, get_next_weekday

# from finrobot.utils import decorate_all_methods, get_next_weekday
from functools import wraps
from typing import Annotated, List


def init_fmp_api(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global fmp_api_key
        if os.environ.get("FMP_API_KEY") is None:
            print("Please set the environment variable FMP_API_KEY to use the FMP API.")
            return None
        else:
            fmp_api_key = os.environ["FMP_API_KEY"]
            print("FMP api key found successfully.")
            return func(*args, **kwargs)

    return wrapper


@decorate_all_methods(init_fmp_api)
class FMPUtils:

    def get_target_price(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date of the target price, should be 'yyyy-mm-dd'"],
    ) -> str:
        """Get the target price for a given stock on a given date"""
        # API URL
        url = f"https://financialmodelingprep.com/api/v4/price-target?symbol={ticker_symbol}&apikey={fmp_api_key}"

        # 发送GET请求
        price_target = "Not Given"
        response = requests.get(url)

        # 确保请求成功
        if response.status_code == 200:
            # 解析JSON数据
            data = response.json()
            est = []

            date = datetime.strptime(date, "%Y-%m-%d")
            for tprice in data:
                tdate = tprice["publishedDate"].split("T")[0]
                tdate = datetime.strptime(tdate, "%Y-%m-%d")
                if abs((tdate - date).days) <= 999:
                    est.append(tprice["priceTarget"])

            if est:
                price_target = f"{np.min(est)} - {np.max(est)} (md. {np.median(est)})"
            else:
                price_target = "N/A"
        else:
            return f"Failed to retrieve data: {response.status_code}"

        return price_target

    def get_sec_report(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[
            str,
            "year of the 10-K report, should be 'yyyy' or 'latest'. Default to 'latest'",
        ] = "latest",
    ) -> str:
        """Get the url and filing date of the 10-K report for a given stock and year"""

        url = f"https://financialmodelingprep.com/api/v3/sec_filings/{ticker_symbol}?type=10-k&page=0&apikey={fmp_api_key}"

        # 发送GET请求
        filing_url = None
        response = requests.get(url)

        # 确保请求成功
        if response.status_code == 200:
            # 解析JSON数据
            data = response.json()
            # print(data)
            if fyear == "latest":
                filing_url = data[0]["finalLink"]
                filing_date = data[0]["fillingDate"]
            else:
                for filing in data:
                    if filing["fillingDate"].split("-")[0] == fyear:
                        filing_url = filing["finalLink"]
                        filing_date = filing["fillingDate"]
                        break

            return f"Link: {filing_url}\nFiling Date: {filing_date}"
        else:
            return f"Failed to retrieve data: {response.status_code}"

    def get_historical_market_cap(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date of the market cap, should be 'yyyy-mm-dd'"],
    ) -> str:
        """Get the historical market capitalization for a given stock on a given date"""
        date = get_next_weekday(date).strftime("%Y-%m-%d")
        url = f"https://financialmodelingprep.com/api/v3/historical-market-capitalization/{ticker_symbol}?limit=100&from={date}&to={date}&apikey={fmp_api_key}"

        # 发送GET请求
        mkt_cap = None
        response = requests.get(url)

        # 确保请求成功
        if response.status_code == 200:
            # 解析JSON数据
            data = response.json()
            mkt_cap = data[0]["marketCap"]
            return mkt_cap
        else:
            return f"Failed to retrieve data: {response.status_code}"

    def get_historical_bvps(
        ticker_symbol: Annotated[str, "ticker symbol"],
        target_date: Annotated[str, "date of the BVPS, should be 'yyyy-mm-dd'"],
    ) -> str:
        """Get the historical book value per share for a given stock on a given date"""
        # 从FMP API获取历史关键财务指标数据
        url = f"https://financialmodelingprep.com/api/v3/key-metrics/{ticker_symbol}?limit=40&apikey={fmp_api_key}"
        response = requests.get(url)
        data = response.json()

        if not data:
            return "No data available"

        # 找到最接近目标日期的数据
        closest_data = None
        min_date_diff = float("inf")
        target_date = datetime.strptime(target_date, "%Y-%m-%d")
        for entry in data:
            date_of_data = datetime.strptime(entry["date"], "%Y-%m-%d")
            date_diff = abs(target_date - date_of_data).days
            if date_diff < min_date_diff:
                min_date_diff = date_diff
                closest_data = entry

        if closest_data:
            return closest_data.get("bookValuePerShare", "No BVPS data available")
        else:
            return "No close date data found"
        
    def get_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"],
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> pd.DataFrame:
        """Get the financial metrics for a given stock for the last 'years' years"""
        # Base URL setup for FMP API
        base_url = "https://financialmodelingprep.com/api/v3"
        # Create DataFrame
        df = pd.DataFrame()

        # Iterate over the last 'years' years of data
        for year_offset in range(years):
            # Construct URL for income statement and ratios for each year
            income_statement_url = f"{base_url}/income-statement/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"
            ratios_url = (
                f"{base_url}/ratios/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"
            )
            key_metrics_url = f"{base_url}/key-metrics/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"

            # Requesting data from the API
            income_data = requests.get(income_statement_url).json()
            key_metrics_data = requests.get(key_metrics_url).json()
            ratios_data = requests.get(ratios_url).json()

            # Extracting needed metrics for each year
            if income_data and key_metrics_data and ratios_data:
                metrics = {
                    "Revenue": round(income_data[year_offset]["revenue"] / 1e6),
                    "Revenue Growth": "{}%".format(round(((income_data[year_offset]["revenue"] - income_data[year_offset - 1]["revenue"]) / income_data[year_offset - 1]["revenue"])*100,1)),
                    "Gross Revenue": round(income_data[year_offset]["grossProfit"] / 1e6),
                    "Gross Margin": round((income_data[year_offset]["grossProfit"] / income_data[year_offset]["revenue"]),2),
                    "EBITDA": round(income_data[year_offset]["ebitda"] / 1e6),
                    "EBITDA Margin": round((income_data[year_offset]["ebitdaratio"]),2),
                    "FCF": round(key_metrics_data[year_offset]["enterpriseValue"] / key_metrics_data[year_offset]["evToOperatingCashFlow"] / 1e6),
                    "FCF Conversion": round(((key_metrics_data[year_offset]["enterpriseValue"] / key_metrics_data[year_offset]["evToOperatingCashFlow"]) / income_data[year_offset]["netIncome"]),2),
                    "ROIC":"{}%".format(round((key_metrics_data[year_offset]["roic"])*100,1)),
                    "EV/EBITDA": round((key_metrics_data[year_offset][
                        "enterpriseValueOverEBITDA"
                    ]),2),
                    "PE Ratio": round(ratios_data[year_offset]["priceEarningsRatio"],2),
                    "PB Ratio": round(key_metrics_data[year_offset]["pbRatio"],2),
                }
                # Append the year and metrics to the DataFrame
                # Extracting the year from the date
                year = income_data[year_offset]["date"][:4]
                df[year] = pd.Series(metrics)

        df = df.sort_index(axis=1)

        return df

    def get_competitor_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"], 
        competitors: Annotated[List[str], "list of competitor ticker symbols"],  
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> dict:
        """Get financial metrics for the company and its competitors."""
        base_url = "https://financialmodelingprep.com/api/v3"
        all_data = {}

        symbols = [ticker_symbol] + competitors  # Combine company and competitors into one list
    
        for symbol in symbols:
            income_statement_url = f"{base_url}/income-statement/{symbol}?limit={years}&apikey={fmp_api_key}"
            ratios_url = f"{base_url}/ratios/{symbol}?limit={years}&apikey={fmp_api_key}"
            key_metrics_url = f"{base_url}/key-metrics/{symbol}?limit={years}&apikey={fmp_api_key}"

            income_data = requests.get(income_statement_url).json()
            ratios_data = requests.get(ratios_url).json()
            key_metrics_data = requests.get(key_metrics_url).json()

            metrics = {}

            if income_data and ratios_data and key_metrics_data:
                for year_offset in range(years):
                    metrics[year_offset] = {
                        "Revenue": round(income_data[year_offset]["revenue"] / 1e6),
                        "Revenue Growth": (
                            "{}%".format((round(income_data[year_offset]["revenue"] - income_data[year_offset - 1]["revenue"] / income_data[year_offset - 1]["revenue"])*100,1))
                            if year_offset > 0 else None
                        ),
                        "Gross Margin": round((income_data[year_offset]["grossProfit"] / income_data[year_offset]["revenue"]),2),
                        "EBITDA Margin": round((income_data[year_offset]["ebitdaratio"]),2),
                        "FCF Conversion": round((
                            key_metrics_data[year_offset]["enterpriseValue"] 
                            / key_metrics_data[year_offset]["evToOperatingCashFlow"] 
                            / income_data[year_offset]["netIncome"]
                            if key_metrics_data[year_offset]["evToOperatingCashFlow"] != 0 else None
                        ),2),
                        "ROIC":"{}%".format(round((key_metrics_data[year_offset]["roic"])*100,1)),
                        "EV/EBITDA": round((key_metrics_data[year_offset]["enterpriseValueOverEBITDA"]),2),
                    }

            df = pd.DataFrame.from_dict(metrics, orient='index')
            df = df.sort_index(axis=1)
            all_data[symbol] = df

        return all_data



if __name__ == "__main__":
    from finrobot.utils import register_keys_from_json

    register_keys_from_json("config_api_keys")
    FMPUtils.get_sec_report("NEE", "2024")
