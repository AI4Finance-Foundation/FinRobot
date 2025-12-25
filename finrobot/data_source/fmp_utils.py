import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ..utils import decorate_all_methods, get_next_weekday

# from finrobot.utils import decorate_all_methods, get_next_weekday
from functools import wraps
from typing import Annotated, List


# FMP API Base URLs - Updated to use stable endpoints (August 2025)
FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


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
        # Updated to stable API endpoint
        url = f"{FMP_STABLE_BASE}/price-target?symbol={ticker_symbol}&apikey={fmp_api_key}"

        price_target = "Not Given"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            est = []

            date = datetime.strptime(date, "%Y-%m-%d")
            for tprice in data:
                tdate = tprice.get("publishedDate", "").split("T")[0]
                if tdate:
                    tdate = datetime.strptime(tdate, "%Y-%m-%d")
                    if abs((tdate - date).days) <= 999:
                        est.append(tprice.get("priceTarget", 0))

            if est:
                price_target = f"{np.min(est)} - {np.max(est)} (md. {np.median(est)})"
            else:
                price_target = "N/A"
        elif response.status_code == 404:
            # Endpoint may not be available in current plan
            return "N/A (Price target endpoint not available)"
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
        # Updated to stable API endpoint
        url = f"{FMP_STABLE_BASE}/sec-filings?symbol={ticker_symbol}&type=10-K&limit=10&apikey={fmp_api_key}"

        filing_url = None
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            if not data:
                return "No SEC filings found"
            
            if fyear == "latest":
                filing_url = data[0].get("finalLink") or data[0].get("link")
                filing_date = data[0].get("fillingDate") or data[0].get("filingDate")
            else:
                for filing in data:
                    filing_date_str = filing.get("fillingDate") or filing.get("filingDate", "")
                    if filing_date_str.split("-")[0] == fyear:
                        filing_url = filing.get("finalLink") or filing.get("link")
                        filing_date = filing_date_str
                        break

            if filing_url:
                return f"Link: {filing_url}\nFiling Date: {filing_date}"
            else:
                return f"No 10-K filing found for year {fyear}"
        elif response.status_code == 404:
            # Try alternative: use SEC API directly or return helpful message
            return f"SEC filings endpoint not available. Use SEC API for 10-K filings."
        else:
            return f"Failed to retrieve data: {response.status_code}"

    def get_historical_market_cap(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date of the market cap, should be 'yyyy-mm-dd'"],
    ) -> str:
        """Get the historical market capitalization for a given stock on a given date"""
        date = get_next_weekday(date).strftime("%Y-%m-%d")
        # Updated to stable API endpoint
        url = f"{FMP_STABLE_BASE}/historical-market-capitalization?symbol={ticker_symbol}&from={date}&to={date}&apikey={fmp_api_key}"

        mkt_cap = None
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                mkt_cap = data[0].get("marketCap", 0)
                return mkt_cap
            else:
                # Fallback: get current market cap from profile
                profile_url = f"{FMP_STABLE_BASE}/profile?symbol={ticker_symbol}&apikey={fmp_api_key}"
                profile_resp = requests.get(profile_url)
                if profile_resp.status_code == 200:
                    profile_data = profile_resp.json()
                    if profile_data and len(profile_data) > 0:
                        return profile_data[0].get("mktCap", 0)
                return "No market cap data available"
        else:
            return f"Failed to retrieve data: {response.status_code}"

    def get_historical_bvps(
        ticker_symbol: Annotated[str, "ticker symbol"],
        target_date: Annotated[str, "date of the BVPS, should be 'yyyy-mm-dd'"],
    ) -> str:
        """Get the historical book value per share for a given stock on a given date"""
        # BVPS is in the ratios endpoint, not key-metrics
        url = f"{FMP_STABLE_BASE}/ratios?symbol={ticker_symbol}&limit=40&apikey={fmp_api_key}"
        response = requests.get(url)
        
        if response.status_code != 200:
            return f"Failed to retrieve data: {response.status_code}"
            
        data = response.json()

        if not data:
            return "No data available"

        # Find the closest data to target date
        closest_data = None
        min_date_diff = float("inf")
        target_date_dt = datetime.strptime(target_date, "%Y-%m-%d")
        for entry in data:
            date_str = entry.get("date", "")
            if date_str:
                date_of_data = datetime.strptime(date_str, "%Y-%m-%d")
                date_diff = abs(target_date_dt - date_of_data).days
                if date_diff < min_date_diff:
                    min_date_diff = date_diff
                    closest_data = entry

        if closest_data:
            bvps = closest_data.get("bookValuePerShare")
            if bvps is not None:
                return round(bvps, 2)
            return "No BVPS data available"
        else:
            return "No close date data found"
        
    def get_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"],
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> pd.DataFrame:
        """Get the financial metrics for a given stock for the last 'years' years"""
        # Updated to stable API endpoints
        df = pd.DataFrame()

        # Construct URLs for stable API
        income_statement_url = f"{FMP_STABLE_BASE}/income-statement?symbol={ticker_symbol}&limit={years}&apikey={fmp_api_key}"
        ratios_url = f"{FMP_STABLE_BASE}/ratios?symbol={ticker_symbol}&limit={years}&apikey={fmp_api_key}"
        key_metrics_url = f"{FMP_STABLE_BASE}/key-metrics?symbol={ticker_symbol}&limit={years}&apikey={fmp_api_key}"

        # Requesting data from the API
        income_resp = requests.get(income_statement_url)
        key_metrics_resp = requests.get(key_metrics_url)
        ratios_resp = requests.get(ratios_url)
        
        if income_resp.status_code != 200 or key_metrics_resp.status_code != 200 or ratios_resp.status_code != 200:
            print(f"Failed to retrieve financial metrics for {ticker_symbol}")
            return df
            
        income_data = income_resp.json()
        key_metrics_data = key_metrics_resp.json()
        ratios_data = ratios_resp.json()

        # Iterate over the years of data
        for year_offset in range(min(years, len(income_data))):
            if income_data and key_metrics_data and ratios_data:
                try:
                    # Safe access with defaults
                    revenue = income_data[year_offset].get("revenue", 0) or 0
                    prev_revenue = income_data[year_offset - 1].get("revenue", 1) if year_offset > 0 else revenue
                    gross_profit = income_data[year_offset].get("grossProfit", 0) or 0
                    ebitda = income_data[year_offset].get("ebitda", 0) or 0
                    ebitda_ratio = income_data[year_offset].get("ebitdaratio", 0) or 0
                    net_income = income_data[year_offset].get("netIncome", 1) or 1
                    
                    enterprise_value = key_metrics_data[year_offset].get("enterpriseValue", 0) or 0
                    ev_to_ocf = key_metrics_data[year_offset].get("evToOperatingCashFlow", 1) or 1
                    roic = key_metrics_data[year_offset].get("roic", 0) or 0
                    ev_ebitda = key_metrics_data[year_offset].get("enterpriseValueOverEBITDA", 0) or 0
                    pb_ratio = key_metrics_data[year_offset].get("pbRatio", 0) or 0
                    
                    pe_ratio = ratios_data[year_offset].get("priceEarningsRatio", 0) or 0
                    
                    # Calculate FCF
                    fcf = enterprise_value / ev_to_ocf if ev_to_ocf != 0 else 0
                    
                    metrics = {
                        "Revenue": round(revenue / 1e6),
                        "Revenue Growth": "{}%".format(round(((revenue - prev_revenue) / prev_revenue) * 100, 1)) if prev_revenue else "N/A",
                        "Gross Revenue": round(gross_profit / 1e6),
                        "Gross Margin": round(gross_profit / revenue, 2) if revenue else 0,
                        "EBITDA": round(ebitda / 1e6),
                        "EBITDA Margin": round(ebitda_ratio, 2),
                        "FCF": round(fcf / 1e6),
                        "FCF Conversion": round(fcf / net_income, 2) if net_income else 0,
                        "ROIC": "{}%".format(round(roic * 100, 1)),
                        "EV/EBITDA": round(ev_ebitda, 2),
                        "PE Ratio": round(pe_ratio, 2),
                        "PB Ratio": round(pb_ratio, 2),
                    }
                    
                    # Extract year from date
                    year = income_data[year_offset].get("date", "")[:4]
                    if year:
                        df[year] = pd.Series(metrics)
                except (KeyError, TypeError, ZeroDivisionError) as e:
                    print(f"Error processing year {year_offset}: {e}")
                    continue

        df = df.sort_index(axis=1)
        return df

    def get_competitor_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"], 
        competitors: Annotated[List[str], "list of competitor ticker symbols"],  
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> dict:
        """Get financial metrics for the company and its competitors."""
        all_data = {}

        symbols = [ticker_symbol] + competitors

        for symbol in symbols:
            # Updated to stable API endpoints
            income_statement_url = f"{FMP_STABLE_BASE}/income-statement?symbol={symbol}&limit={years}&apikey={fmp_api_key}"
            ratios_url = f"{FMP_STABLE_BASE}/ratios?symbol={symbol}&limit={years}&apikey={fmp_api_key}"
            key_metrics_url = f"{FMP_STABLE_BASE}/key-metrics?symbol={symbol}&limit={years}&apikey={fmp_api_key}"

            income_resp = requests.get(income_statement_url)
            ratios_resp = requests.get(ratios_url)
            key_metrics_resp = requests.get(key_metrics_url)
            
            if income_resp.status_code != 200 or ratios_resp.status_code != 200 or key_metrics_resp.status_code != 200:
                print(f"Failed to retrieve data for {symbol}")
                all_data[symbol] = pd.DataFrame()
                continue
                
            income_data = income_resp.json()
            ratios_data = ratios_resp.json()
            key_metrics_data = key_metrics_resp.json()

            metrics = {}

            if income_data and ratios_data and key_metrics_data:
                for year_offset in range(min(years, len(income_data))):
                    try:
                        # Safe access with defaults
                        revenue = income_data[year_offset].get("revenue", 0) or 0
                        prev_revenue = income_data[year_offset - 1].get("revenue", 1) if year_offset > 0 else None
                        gross_profit = income_data[year_offset].get("grossProfit", 0) or 0
                        ebitda_ratio = income_data[year_offset].get("ebitdaratio", 0) or 0
                        net_income = income_data[year_offset].get("netIncome", 1) or 1
                        
                        enterprise_value = key_metrics_data[year_offset].get("enterpriseValue", 0) or 0
                        ev_to_ocf = key_metrics_data[year_offset].get("evToOperatingCashFlow", 1) or 1
                        roic = key_metrics_data[year_offset].get("roic", 0) or 0
                        ev_ebitda = key_metrics_data[year_offset].get("enterpriseValueOverEBITDA", 0) or 0
                        
                        # Calculate revenue growth
                        revenue_growth = None
                        if year_offset > 0 and prev_revenue:
                            revenue_growth = "{}%".format(round(((revenue - prev_revenue) / prev_revenue) * 100, 1))
                        
                        # Calculate FCF conversion
                        fcf_conversion = None
                        if ev_to_ocf != 0 and net_income != 0:
                            fcf = enterprise_value / ev_to_ocf
                            fcf_conversion = round(fcf / net_income, 2)
                        
                        metrics[year_offset] = {
                            "Revenue": round(revenue / 1e6),
                            "Revenue Growth": revenue_growth,
                            "Gross Margin": round(gross_profit / revenue, 2) if revenue else 0,
                            "EBITDA Margin": round(ebitda_ratio, 2),
                            "FCF Conversion": fcf_conversion,
                            "ROIC": "{}%".format(round(roic * 100, 1)),
                            "EV/EBITDA": round(ev_ebitda, 2),
                        }
                    except (KeyError, TypeError, ZeroDivisionError) as e:
                        print(f"Error processing {symbol} year {year_offset}: {e}")
                        continue

            df = pd.DataFrame.from_dict(metrics, orient='index')
            df = df.sort_index(axis=1)
            all_data[symbol] = df

        return all_data

    def get_company_profile(
        ticker_symbol: Annotated[str, "ticker symbol"],
    ) -> dict:
        """Get company profile information"""
        url = f"{FMP_STABLE_BASE}/profile?symbol={ticker_symbol}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                return data[0]
            return {}
        return {}

    def get_quote(
        ticker_symbol: Annotated[str, "ticker symbol"],
    ) -> dict:
        """Get current stock quote"""
        url = f"{FMP_STABLE_BASE}/quote?symbol={ticker_symbol}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                return data[0]
            return {}
        return {}

    def get_income_statement(
        ticker_symbol: Annotated[str, "ticker symbol"],
        limit: Annotated[int, "number of periods to retrieve"] = 4,
    ) -> list:
        """Get income statement data"""
        url = f"{FMP_STABLE_BASE}/income-statement?symbol={ticker_symbol}&limit={limit}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []

    def get_balance_sheet(
        ticker_symbol: Annotated[str, "ticker symbol"],
        limit: Annotated[int, "number of periods to retrieve"] = 4,
    ) -> list:
        """Get balance sheet data"""
        url = f"{FMP_STABLE_BASE}/balance-sheet-statement?symbol={ticker_symbol}&limit={limit}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []

    def get_cash_flow(
        ticker_symbol: Annotated[str, "ticker symbol"],
        limit: Annotated[int, "number of periods to retrieve"] = 4,
    ) -> list:
        """Get cash flow statement data"""
        url = f"{FMP_STABLE_BASE}/cash-flow-statement?symbol={ticker_symbol}&limit={limit}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []

    def get_key_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"],
        limit: Annotated[int, "number of periods to retrieve"] = 4,
    ) -> list:
        """Get key financial metrics"""
        url = f"{FMP_STABLE_BASE}/key-metrics?symbol={ticker_symbol}&limit={limit}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []

    def get_ratios(
        ticker_symbol: Annotated[str, "ticker symbol"],
        limit: Annotated[int, "number of periods to retrieve"] = 4,
    ) -> list:
        """Get financial ratios"""
        url = f"{FMP_STABLE_BASE}/ratios?symbol={ticker_symbol}&limit={limit}&apikey={fmp_api_key}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []


if __name__ == "__main__":
    from finrobot.utils import register_keys_from_json

    register_keys_from_json("config_api_keys")
    
    # Test the updated endpoints
    print("Testing FMP Utils with stable endpoints...")
    print("\n1. Company Profile:")
    print(FMPUtils.get_company_profile("AAPL"))
    
    print("\n2. Quote:")
    print(FMPUtils.get_quote("AAPL"))
    
    print("\n3. Financial Metrics:")
    print(FMPUtils.get_financial_metrics("AAPL", 2))
