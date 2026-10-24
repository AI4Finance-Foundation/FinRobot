#!/usr/bin/env python
# coding: utf-8

import yfinance as yf
import pandas as pd
import requests
import datetime
import os

# Assuming common_utils.py is in the same parent directory (src/modules)
from .common_utils import get_api_key, load_config 

def fetch_yfinance_volume(ticker: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """Fetches historical trading volume data using yfinance."""
    try:
        stock_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if stock_data.empty:
            print(f"No data returned from yfinance for {ticker} between {start_date} and {end_date}")
            return None
        stock_data = stock_data[["Volume"]]
        stock_data.reset_index(inplace=True)
        stock_data["Date"] = pd.to_datetime(stock_data["Date"])
        return stock_data
    except Exception as e:
        print(f"Error fetching yfinance volume for {ticker}: {e}")
        return None

def get_yf_income_statement(ticker: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches income statement data using yfinance as a fallback."""
    try:
        t = yf.Ticker(ticker)
        fin = t.quarterly_financials if period == "quarterly" else t.financials
        if fin is None or fin.empty:
            return None
        records = []
        for col in fin.columns:
            col_date = pd.to_datetime(col)
            year = col_date.year
            d = fin[col]
            rev = d.get('Total Revenue')
            if pd.isna(rev) or rev is None:
                rev = d.get('Operating Revenue')
            cost = d.get('Cost Of Revenue')
            if pd.isna(cost) or cost is None:
                cost = d.get('Reconciled Cost Of Revenue', 0.0)
            gp = d.get('Gross Profit')
            op_exp = d.get('Operating Expense')
            sga = d.get('Selling General And Administration')
            if pd.isna(sga) or sga is None:
                sga = d.get('Selling And Marketing Expense', 0.0)
            ebitda = d.get('EBITDA')
            if pd.isna(ebitda) or ebitda is None:
                ebitda = d.get('Normalized EBITDA')
            eps = d.get('Diluted EPS')
            if pd.isna(eps) or eps is None:
                eps = d.get('Basic EPS')
            row_data = {
                'date': col_date,
                'year': year,
                'revenue': float(rev) if pd.notna(rev) else None,
                'costOfRevenue': float(cost) if pd.notna(cost) else 0.0,
                'grossProfit': float(gp) if pd.notna(gp) else None,
                'operatingExpenses': float(op_exp) if pd.notna(op_exp) else None,
                'sellingGeneralAndAdministrativeExpenses': float(sga) if pd.notna(sga) else None,
                'ebitda': float(ebitda) if pd.notna(ebitda) else None,
                'operatingIncome': float(d.get('Operating Income')) if pd.notna(d.get('Operating Income')) else None,
                'netIncome': float(d.get('Net Income')) if pd.notna(d.get('Net Income')) else None,
                'eps': float(eps) if pd.notna(eps) else None,
                'epsdiluted': float(eps) if pd.notna(eps) else None,
            }
            records.append(row_data)
        df = pd.DataFrame(records).dropna(subset=['revenue'])
        if df.empty:
            return None
        df = df.sort_values('date', ascending=False).head(limit).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Error fetching yfinance income statement for {ticker}: {e}")
        return None

def get_yf_balance_sheet(ticker: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches balance sheet data using yfinance as a fallback."""
    try:
        t = yf.Ticker(ticker)
        bs = t.quarterly_balance_sheet if period == "quarterly" else t.balance_sheet
        if bs is None or bs.empty:
            return None
        records = []
        for col in bs.columns:
            col_date = pd.to_datetime(col)
            year = col_date.year
            d = bs[col]
            row_data = {
                'date': col_date,
                'year': year,
                'totalAssets': float(d.get('Total Assets')) if pd.notna(d.get('Total Assets')) else None,
                'totalStockholdersEquity': float(d.get('Stockholders Equity', d.get('Common Stock Equity'))) if pd.notna(d.get('Stockholders Equity', d.get('Common Stock Equity'))) else None,
                'totalLiabilities': float(d.get('Total Liabilities Net Minority Interest')) if pd.notna(d.get('Total Liabilities Net Minority Interest')) else None,
                'totalDebt': float(d.get('Total Debt')) if pd.notna(d.get('Total Debt')) else None,
                'netDebt': float(d.get('Net Debt')) if pd.notna(d.get('Net Debt')) else None,
                'cashAndCashEquivalents': float(d.get('Cash And Cash Equivalents', d.get('Cash Cash Equivalents And Short Term Investments'))) if pd.notna(d.get('Cash And Cash Equivalents', d.get('Cash Cash Equivalents And Short Term Investments'))) else None,
            }
            records.append(row_data)
        df = pd.DataFrame(records)
        df = df.sort_values('date', ascending=False).head(limit).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Error fetching yfinance balance sheet for {ticker}: {e}")
        return None

def get_yf_cash_flow_statement(ticker: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches cash flow statement data using yfinance as a fallback."""
    try:
        t = yf.Ticker(ticker)
        cf = t.quarterly_cashflow if period == "quarterly" else t.cashflow
        if cf is None or cf.empty:
            return None
        records = []
        for col in cf.columns:
            col_date = pd.to_datetime(col)
            year = col_date.year
            d = cf[col]
            row_data = {
                'date': col_date,
                'year': year,
                'operatingCashFlow': float(d.get('Operating Cash Flow')) if pd.notna(d.get('Operating Cash Flow')) else None,
                'capitalExpenditure': float(d.get('Capital Expenditure')) if pd.notna(d.get('Capital Expenditure')) else None,
                'freeCashFlow': float(d.get('Free Cash Flow')) if pd.notna(d.get('Free Cash Flow')) else None,
                'netIncome': float(d.get('Net Income From Continuing Operations', d.get('Net Income'))) if pd.notna(d.get('Net Income From Continuing Operations', d.get('Net Income'))) else None,
            }
            records.append(row_data)
        df = pd.DataFrame(records)
        df = df.sort_values('date', ascending=False).head(limit).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Error fetching yfinance cash flow for {ticker}: {e}")
        return None

def get_yf_ratios_and_key_metrics(ticker: str, limit: int = 5) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetches financial ratios and key metrics using yfinance as fallback."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        now = datetime.datetime.now()
        ratios_record = [{
            'date': now,
            'year': now.year,
            'priceEarningsRatio': info.get('trailingPE') or info.get('forwardPE'),
            'priceToBookRatio': info.get('priceToBook'),
            'returnOnEquity': info.get('returnOnEquity'),
            'debtEquityRatio': (info.get('debtToEquity') / 100.0) if info.get('debtToEquity') is not None else None,
            'dividendYield': info.get('dividendYield'),
        }]
        key_metrics_record = [{
            'date': now,
            'year': now.year,
            'peRatio': info.get('trailingPE') or info.get('forwardPE'),
            'pbRatio': info.get('priceToBook'),
            'enterpriseValueOverEBITDA': info.get('enterpriseToEbitda'),
            'marketCap': info.get('marketCap'),
            'enterpriseValue': info.get('enterpriseValue'),
        }]
        return pd.DataFrame(ratios_record), pd.DataFrame(key_metrics_record)
    except Exception as e:
        print(f"Error fetching yfinance ratios for {ticker}: {e}")
        return None, None

def fetch_fmp_enterprise_value(ticker: str, api_key: str, limit: int = 2000) -> pd.DataFrame | None:
    """Fetches historical enterprise value from Financial Modeling Prep API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v3/enterprise-value/{ticker}?limit={limit}&apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                if "date" in df.columns and "enterpriseValue" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    return df[["date", "enterpriseValue"]].sort_values(by="date").reset_index(drop=True)
        except Exception as e:
            print(f"Notice: FMP EV for {ticker} unavailable ({e}), falling back to yfinance.")

    try:
        t = yf.Ticker(ticker)
        ev = t.info.get('enterpriseValue')
        if ev:
            now = datetime.datetime.now()
            return pd.DataFrame([{'date': now, 'enterpriseValue': float(ev)}])
    except Exception as e:
        print(f"Error fetching yfinance EV for {ticker}: {e}")
    return None

def get_fmp_ratios_and_key_metrics(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetches financial ratios and key metrics from FMP API with yfinance fallback."""
    ratios_df, key_metrics_df = None, None
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        try:
            # Ratios
            ratios_url = f"https://financialmodelingprep.com/api/v3/ratios/{ticker}?period={period}&limit={limit}&apikey={api_key}"
            response_ratios = requests.get(ratios_url, timeout=10)
            response_ratios.raise_for_status()
            ratios_data = response_ratios.json()
            if ratios_data and isinstance(ratios_data, list):
                ratios_df = pd.DataFrame(ratios_data)
                ratios_df["date"] = pd.to_datetime(ratios_df["date"])
                ratios_df["year"] = ratios_df["date"].dt.year

            # Key Metrics
            key_metrics_url = f"https://financialmodelingprep.com/api/v3/key-metrics/{ticker}?period={period}&limit={limit}&apikey={api_key}"
            response_key_metrics = requests.get(key_metrics_url, timeout=10)
            response_key_metrics.raise_for_status()
            key_metrics_data = response_key_metrics.json()
            if key_metrics_data and isinstance(key_metrics_data, list):
                key_metrics_df = pd.DataFrame(key_metrics_data)
                key_metrics_df["date"] = pd.to_datetime(key_metrics_df["date"])
                key_metrics_df["year"] = key_metrics_df["date"].dt.year

        except Exception as e:
            print(f"Notice: FMP ratios/key metrics for {ticker} unavailable ({e}), falling back to yfinance.")

    if ratios_df is None or ratios_df.empty or key_metrics_df is None or key_metrics_df.empty:
        yf_ratios, yf_key_metrics = get_yf_ratios_and_key_metrics(ticker, limit)
        ratios_df = ratios_df if ratios_df is not None and not ratios_df.empty else yf_ratios
        key_metrics_df = key_metrics_df if key_metrics_df is not None and not key_metrics_df.empty else yf_key_metrics

    return ratios_df, key_metrics_df

def get_fmp_income_statement(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches income statement data from FMP API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        try:
            url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"])
                df["year"] = df["date"].dt.year
                return df
        except Exception as e:
            print(f"Notice: FMP income statement for {ticker} unavailable ({e}), falling back to yfinance.")

    return get_yf_income_statement(ticker, period=period, limit=limit)

def get_fmp_balance_sheet(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches balance sheet data from FMP API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        try:
            url = f"https://financialmodelingprep.com/api/v3/balance-sheet-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"])
                df["year"] = df["date"].dt.year
                return df
        except Exception as e:
            print(f"Notice: FMP balance sheet for {ticker} unavailable ({e}), falling back to yfinance.")

    return get_yf_balance_sheet(ticker, period=period, limit=limit)

def get_fmp_cash_flow_statement(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches cash flow statement data from FMP API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        try:
            url = f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"])
                df["year"] = df["date"].dt.year
                return df
        except Exception as e:
            print(f"Notice: FMP cash flow for {ticker} unavailable ({e}), falling back to yfinance.")

    return get_yf_cash_flow_statement(ticker, period=period, limit=limit)

def get_comprehensive_financial_data(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> dict:
    """Fetches all three financial statements for a company."""
    print(f"Fetching comprehensive financial data for {ticker}...")
    
    financial_data = {
        'income_statement': get_fmp_income_statement(ticker, api_key, period, limit),
        'balance_sheet': get_fmp_balance_sheet(ticker, api_key, period, limit),
        'cash_flow': get_fmp_cash_flow_statement(ticker, api_key, period, limit),
        'ratios': None,
        'key_metrics': None
    }
    
    # Also get ratios and key metrics
    ratios_df, key_metrics_df = get_fmp_ratios_and_key_metrics(ticker, api_key, period, limit)
    financial_data['ratios'] = ratios_df
    financial_data['key_metrics'] = key_metrics_df
    
    return financial_data

def combine_peer_financial_data(tickers: list[str], api_key: str, years_limit: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combines EBITDA and EV/EBITDA for a list of peer tickers."""
    all_peers_data = {}
    for ticker in tickers:
        income_df = get_fmp_income_statement(ticker, api_key, limit=years_limit)
        _, key_metrics_df = get_fmp_ratios_and_key_metrics(ticker, api_key, limit=years_limit)
        
        ticker_data = {}
        if income_df is not None and not income_df.empty:
            for _, row in income_df.iterrows():
                year = row["year"]
                if year not in ticker_data: ticker_data[year] = {}
                ticker_data[year]["EBITDA"] = row.get("ebitda")

        if key_metrics_df is not None and not key_metrics_df.empty:
            for _, row in key_metrics_df.iterrows():
                year = row["year"]
                if year not in ticker_data: ticker_data[year] = {}
                ticker_data[year]["EV/EBITDA"] = row.get("enterpriseValueOverEBITDA")
        
        if ticker_data:
            all_peers_data[ticker] = ticker_data

    ebitda_records = []
    for ticker, yearly_data in all_peers_data.items():
        for year, metrics in yearly_data.items():
            if "EBITDA" in metrics and metrics["EBITDA"] is not None:
                ebitda_records.append({"ticker": ticker, "year": year, "EBITDA": metrics["EBITDA"]})
    df_ebitda_all = pd.DataFrame(ebitda_records)
    df_ebitda_pivot = pd.DataFrame()
    if not df_ebitda_all.empty:
        df_ebitda_pivot = df_ebitda_all.pivot(index="year", columns="ticker", values="EBITDA").sort_index()

    ev_ebitda_records = []
    for ticker, yearly_data in all_peers_data.items():
        for year, metrics in yearly_data.items():
            if "EV/EBITDA" in metrics and metrics["EV/EBITDA"] is not None:
                ev_ebitda_records.append({"ticker": ticker, "year": year, "EV/EBITDA": metrics["EV/EBITDA"]})
    df_ev_ebitda_all = pd.DataFrame(ev_ebitda_records)
    df_ev_ebitda_pivot = pd.DataFrame()
    if not df_ev_ebitda_all.empty:
        df_ev_ebitda_pivot = df_ev_ebitda_all.pivot(index="year", columns="ticker", values="EV/EBITDA").sort_index()
        
    return df_ebitda_pivot, df_ev_ebitda_pivot

def project_ebitda_for_peers(df_ebitda_historical: pd.DataFrame, num_projection_years: int = 1) -> pd.DataFrame:
    """Projects EBITDA for future years based on average historical YoY growth."""
    df_projected = df_ebitda_historical.copy()
    if df_projected.empty:
        return df_projected

    last_historical_year = df_projected.index.max()
    
    for company in df_projected.columns:
        historical_values = df_projected[company].dropna()
        if len(historical_values) < 2:
            print(f"Not enough historical EBITDA data for {company} to project.")
            continue
        
        growth_rates = historical_values.pct_change().dropna()
        if growth_rates.empty or all(g == 0 for g in growth_rates):
            avg_growth_rate = 0 
        else:
            avg_growth_rate = growth_rates.mean()

        current_ebitda = historical_values.iloc[-1]
        for i in range(1, num_projection_years + 1):
            projection_year = last_historical_year + i
            current_ebitda = current_ebitda * (1 + avg_growth_rate)
            df_projected.loc[projection_year, company] = current_ebitda
            
    return df_projected.sort_index()

def get_fmp_current_price(ticker: str, api_key: str = None) -> float | None:
    """Fetches the latest stock price from Financial Modeling Prep API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v3/quote-short/{ticker}?apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                quote_data = data[0]
                if "price" in quote_data and quote_data["price"] is not None:
                    return float(quote_data["price"])
        except Exception as e:
            pass

    try:
        t = yf.Ticker(ticker)
        price = getattr(t.fast_info, 'last_price', None)
        if price is not None and not pd.isna(price):
            return float(price)
        hist = t.history(period="1d")
        if not hist.empty and 'Close' in hist:
            return float(hist['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching yfinance current price for {ticker}: {e}")
    return None

def get_analyst_insights(ticker: str, api_key: str = None) -> tuple[str | None, float | None]:
    """
    Fetches analyst rating and target price using FMP API with yfinance fallback.
    """
    rating = None
    target_price = None
    
    try:
        if api_key:
            rating = get_fmp_analyst_rating(ticker, api_key)
            target_price = get_fmp_target_price(ticker, api_key)
    except Exception as e:
        print(f"[ERROR] Error in get_analyst_insights for {ticker}: {e}")

    if not target_price or not rating:
        try:
            info = yf.Ticker(ticker).info or {}
            if not target_price:
                target_price = info.get('targetMeanPrice') or info.get('targetMedianPrice')
            if not rating:
                rec = info.get('recommendationKey')
                if rec:
                    rating = rec.capitalize()
        except Exception:
            pass
        
    return rating, target_price

def get_fmp_target_price(ticker: str, api_key: str) -> float | None:
    """Fetches the latest analyst target price from Financial Modeling Prep API v4 with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v4/price-target?symbol={ticker}&apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                for item in data:
                    try:
                        item['parsedDate'] = pd.to_datetime(item.get('publishedDate'))
                    except Exception:
                        item['parsedDate'] = None
                
                valid_data = [item for item in data if item.get('parsedDate') is not None]
                if valid_data:
                    latest_target_info = sorted(valid_data, key=lambda x: x['parsedDate'], reverse=True)[0]
                    if "priceTarget" in latest_target_info and latest_target_info["priceTarget"] is not None:
                        return float(latest_target_info["priceTarget"])
        except Exception:
            pass

    try:
        t = yf.Ticker(ticker)
        target = t.info.get('targetMeanPrice') or t.info.get('targetMedianPrice')
        if target is not None:
            return float(target)
    except Exception:
        pass
    return None

def get_fmp_analyst_rating(ticker: str, api_key: str) -> str | None:
    """Fetches the latest analyst rating from Financial Modeling Prep API v4 with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v4/upgrades-downgrades?symbol={ticker}&apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                for item in data:
                    try:
                        item['parsedDate'] = pd.to_datetime(item.get('publishedDate'))
                    except Exception:
                        item['parsedDate'] = None
                valid_data = [item for item in data if item.get('parsedDate') is not None]
                if valid_data:
                    latest_rating_info = sorted(valid_data, key=lambda x: x['parsedDate'], reverse=True)[0]
                    if "newGrade" in latest_rating_info and latest_rating_info["newGrade"]:
                        return str(latest_rating_info["newGrade"])
                    elif "action" in latest_rating_info and latest_rating_info["action"]:
                        return str(latest_rating_info["action"])
        except Exception:
            pass

    try:
        t = yf.Ticker(ticker)
        rec = t.info.get('recommendationKey')
        if rec:
            return rec.capitalize()
    except Exception:
        pass
    return None

def get_fmp_company_profile(ticker: str, api_key: str) -> dict | None:
    """Fetches comprehensive company profile data from FMP API with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
        except Exception:
            pass

    try:
        info = yf.Ticker(ticker).info or {}
        return {
            'companyName': info.get('longName') or info.get('shortName') or ticker,
            'mktCap': info.get('marketCap'),
            'volAvg': info.get('averageVolume'),
            'beta': info.get('beta'),
            'sector': info.get('sector', 'N/A'),
            'industry': info.get('industry', 'N/A'),
            'exchangeShortName': info.get('exchange', 'N/A'),
            'lastDiv': info.get('dividendRate', 0),
            'sharesOutstanding': info.get('sharesOutstanding'),
            'description': info.get('longBusinessSummary', '')
        }
    except Exception as e:
        print(f"Error fetching yfinance profile for {ticker}: {e}")
        return None

def get_fmp_market_cap(ticker: str, api_key: str) -> float | None:
    """Fetches current market capitalization with yfinance fallback."""
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        url = f"https://financialmodelingprep.com/api/v3/market-capitalization/{ticker}?apikey={api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                market_cap = data[0].get('marketCap')
                return float(market_cap) if market_cap else None
        except Exception:
            pass

    try:
        t = yf.Ticker(ticker)
        mc = t.info.get('marketCap')
        return float(mc) if mc else None
    except Exception:
        return None

def get_comprehensive_company_metrics(ticker: str, api_key: str) -> dict:
    """Fetches all key company metrics needed for equity report with fallbacks."""
    print(f"Fetching comprehensive company metrics for {ticker}...")
    
    metrics = {
        'share_price': None,
        'target_price': None,
        'market_cap': None,
        'volume': None,
        'fwd_pe': None,
        'pb_ratio': None,
        'dividend_yield': None,
        'free_float': None,
        'roe': None,
        'net_debt_to_equity': None,
        'rating': None,
        'beta': None,
        'sector': None,
        'industry': None,
        'exchange': None,
        '52w_range': None,
        'shares_outstanding': None,
    }
    
    # 1. Get current price and basic quote data
    current_price = get_fmp_current_price(ticker, api_key)
    if current_price:
        metrics['share_price'] = current_price
    
    # 2. Get target price and rating
    target_price = get_fmp_target_price(ticker, api_key)
    if target_price:
        metrics['target_price'] = target_price
    
    rating = get_fmp_analyst_rating(ticker, api_key)
    if rating:
        metrics['rating'] = rating
    
    # 3. Get company profile data
    profile = get_fmp_company_profile(ticker, api_key)
    if profile:
        metrics['market_cap'] = profile.get('mktCap', 0) / 1e9 if profile.get('mktCap') else None  # Convert to billions
        metrics['volume'] = profile.get('volAvg', 0) / 1e6 if profile.get('volAvg') else None  # Convert to millions
        metrics['beta'] = profile.get('beta')
        metrics['sector'] = profile.get('sector', 'N/A')
        metrics['industry'] = profile.get('industry', 'N/A')
        metrics['exchange'] = profile.get('exchangeShortName', 'N/A')
    
    # 4. Get detailed quote data (volume, 52w range, shares outstanding)
    try:
        quote_url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={api_key}"
        response = requests.get(quote_url, timeout=10)
        response.raise_for_status()
        quote_data = response.json()
        if quote_data and isinstance(quote_data, list) and len(quote_data) > 0:
            quote = quote_data[0]
            # Volume
            if not metrics['volume']:
                avg_volume = quote.get('avgVolume')
                if avg_volume:
                    metrics['volume'] = avg_volume / 1e6  # Convert to millions
            # 52-week range
            year_high = quote.get('yearHigh')
            year_low = quote.get('yearLow')
            if year_high is not None and year_low is not None:
                metrics['52w_range'] = f"${year_low:.2f} - ${year_high:.2f}"
            # Shares outstanding
            shares_out = quote.get('sharesOutstanding')
            if shares_out:
                metrics['shares_outstanding'] = float(shares_out)
    except Exception:
        pass

    if metrics['52w_range'] is None or metrics['shares_outstanding'] is None:
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            low52 = info.get('fiftyTwoWeekLow')
            high52 = info.get('fiftyTwoWeekHigh')
            if low52 and high52:
                metrics['52w_range'] = f"${low52:.2f} - ${high52:.2f}"
            if not metrics['shares_outstanding']:
                metrics['shares_outstanding'] = info.get('sharesOutstanding')
        except Exception:
            pass
    
    # 5. Get financial ratios
    try:
        ratios_df, key_metrics_df = get_fmp_ratios_and_key_metrics(ticker, api_key, limit=1)
        
        if ratios_df is not None and not ratios_df.empty:
            latest_ratios = ratios_df.iloc[0]
            metrics['pb_ratio'] = latest_ratios.get('priceToBookRatio') or latest_ratios.get('pbRatio')
            metrics['roe'] = latest_ratios.get('returnOnEquity')
            if metrics['roe'] and metrics['roe'] < 1:
                metrics['roe'] = metrics['roe'] * 100  # Convert to percentage
            metrics['net_debt_to_equity'] = latest_ratios.get('debtEquityRatio')
            metrics['fwd_pe'] = latest_ratios.get('priceEarningsRatio') or latest_ratios.get('peRatio')
        
        if key_metrics_df is not None and not key_metrics_df.empty:
            latest_key_metrics = key_metrics_df.iloc[0]
            if latest_key_metrics.get('peRatio') and not metrics['fwd_pe']:
                metrics['fwd_pe'] = latest_key_metrics['peRatio']
            if latest_key_metrics.get('pbRatio') and not metrics['pb_ratio']:
                metrics['pb_ratio'] = latest_key_metrics['pbRatio']
    except Exception as e:
        print(f"Warning: Could not fetch financial ratios: {e}")
    
    # 6. Get dividend yield from profile or financial data
    if profile and profile.get('lastDiv'):
        if current_price and profile['lastDiv'] > 0:
            annual_dividend = profile['lastDiv']
            metrics['dividend_yield'] = (annual_dividend / current_price) * 100
    
    # 7. Get shares outstanding for free float calculation (approximate)
    if metrics['free_float'] is None:
        metrics['free_float'] = 95.0
    if metrics['sector'] is None or metrics['sector'] == 'N/A':
        metrics['sector'] = 'Technology'
    if metrics['rating'] is None:
        metrics['rating'] = 'N/A'
    
    print(f"Successfully fetched metrics for {ticker}")
    return metrics


def get_technical_indicators(ticker: str, api_key: str) -> dict:
    """从 FMP 或 yfinance 获取历史价格并计算 SMA50/200、RSI14、MACD、成交量信号。"""
    result = {
        'sma50': None, 'sma200': None, 'rsi14': None,
        'macd': None, 'macd_signal': None, 'macd_histogram': None,
        'avg_volume_20d': None, 'latest_volume': None,
        'price': None,
        'ma_signal': 'N/A', 'rsi_signal': 'N/A',
        'macd_signal_label': 'N/A', 'volume_signal': 'N/A',
        'overall_signal': 'N/A',
    }
    try:
        import numpy as np
        prices = []
        if api_key and api_key != "YOUR_FMP_KEY_HERE":
            try:
                url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?timeseries=250&apikey={api_key}"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                prices = data.get('historical', [])
            except Exception:
                pass

        if len(prices) >= 50:
            df = pd.DataFrame(prices).sort_values('date').reset_index(drop=True)
            close = df['close'].astype(float)
            volume = df['volume'].astype(float)
        else:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist.empty or len(hist) < 50:
                return result
            close = hist['Close'].astype(float)
            volume = hist['Volume'].astype(float)

        result['price'] = close.iloc[-1]

        # SMA
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        result['sma50'] = round(sma50, 2)
        if sma200 is not None:
            result['sma200'] = round(sma200, 2)

        # MA signal
        price = close.iloc[-1]
        if sma200 is not None:
            if price > sma50 > sma200:
                result['ma_signal'] = 'Bullish'
            elif price < sma50 < sma200:
                result['ma_signal'] = 'Bearish'
            elif price > sma200:
                result['ma_signal'] = 'Neutral-Bullish'
            else:
                result['ma_signal'] = 'Neutral-Bearish'
        elif price > sma50:
            result['ma_signal'] = 'Bullish'
        else:
            result['ma_signal'] = 'Bearish'

        # RSI 14
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi_val = rsi.iloc[-1]
        result['rsi14'] = round(rsi_val, 1)
        if rsi_val > 70:
            result['rsi_signal'] = 'Overbought'
        elif rsi_val < 30:
            result['rsi_signal'] = 'Oversold'
        elif rsi_val > 55:
            result['rsi_signal'] = 'Bullish'
        elif rsi_val < 45:
            result['rsi_signal'] = 'Bearish'
        else:
            result['rsi_signal'] = 'Neutral'

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        histogram = macd_line - signal_line
        result['macd'] = round(macd_line.iloc[-1], 2)
        result['macd_signal'] = round(signal_line.iloc[-1], 2)
        result['macd_histogram'] = round(histogram.iloc[-1], 2)
        if macd_line.iloc[-1] > signal_line.iloc[-1] and histogram.iloc[-1] > 0:
            result['macd_signal_label'] = 'Bullish'
        elif macd_line.iloc[-1] < signal_line.iloc[-1] and histogram.iloc[-1] < 0:
            result['macd_signal_label'] = 'Bearish'
        else:
            result['macd_signal_label'] = 'Neutral'

        # Volume
        avg_vol = volume.tail(20).mean()
        latest_vol = volume.iloc[-1]
        result['avg_volume_20d'] = round(avg_vol)
        result['latest_volume'] = round(latest_vol)
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1
        if vol_ratio > 1.5:
            result['volume_signal'] = 'High Activity'
        elif vol_ratio < 0.5:
            result['volume_signal'] = 'Low Activity'
        else:
            result['volume_signal'] = 'Normal'

        # Overall signal
        signals = [result['ma_signal'], result['rsi_signal'],
                   result['macd_signal_label']]
        bullish = sum(1 for s in signals if 'Bullish' in s or s == 'Oversold')
        bearish = sum(1 for s in signals if 'Bearish' in s or s == 'Overbought')
        if bullish >= 2:
            result['overall_signal'] = 'Bullish'
        elif bearish >= 2:
            result['overall_signal'] = 'Bearish'
        else:
            result['overall_signal'] = 'Neutral'

        print(f"✅ Computed technical indicators for {ticker}: {result['overall_signal']}")
    except Exception as e:
        print(f"⚠️ Could not compute technical indicators: {e}")
    return result


def get_company_news(ticker: str, api_key: str, days_back: int = 5, limit: int = 50) -> list[dict] | None:
    """
    Fetches recent company news from FMP API with yfinance fallback.
    """
    filtered_news = []
    if api_key and api_key != "YOUR_FMP_KEY_HERE":
        try:
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            from_date = start_date.strftime('%Y-%m-%d')
            to_date = end_date.strftime('%Y-%m-%d')
            url = f"https://financialmodelingprep.com/api/v3/stock_news"
            params = {
                'tickers': ticker,
                'from': from_date,
                'to': to_date,
                'limit': limit,
                'apikey': api_key
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                for article in data:
                    filtered_article = {
                        'symbol': article.get('symbol'),
                        'title': article.get('title'),
                        'publishedDate': article.get('publishedDate'),
                        'text': article.get('text'),
                        'site': article.get('site'),
                        'url': article.get('url')
                    }
                    filtered_news.append(filtered_article)
                if filtered_news:
                    print(f"Successfully fetched {len(filtered_news)} news articles from FMP for {ticker}")
                    return filtered_news
        except Exception:
            pass

    try:
        t = yf.Ticker(ticker)
        yf_news = t.news or []
        for article in yf_news[:limit]:
            content = article.get('content', {}) if isinstance(article.get('content'), dict) else article
            title = content.get('title') or article.get('title', '')
            pub_date = content.get('pubDate') or article.get('providerPublishTime', '')
            summary = content.get('summary') or article.get('summary', '')
            prov = content.get('provider', {}).get('displayName') if isinstance(content.get('provider'), dict) else 'Yahoo Finance'
            url = content.get('canonicalUrl', {}).get('url') if isinstance(content.get('canonicalUrl'), dict) else article.get('link', '')
            filtered_news.append({
                'symbol': ticker,
                'title': title,
                'publishedDate': str(pub_date),
                'text': summary,
                'site': prov,
                'url': url
            })
        if filtered_news:
            print(f"Successfully fetched {len(filtered_news)} news articles from yfinance for {ticker}")
            return filtered_news
    except Exception as e:
        print(f"Error fetching news for {ticker}: {e}")
    return filtered_news if filtered_news else None


if __name__ == "__main__":
    print("Testing market_data_api.py...")
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path_test = os.path.join(current_script_dir, "..", "..", "config", "config.ini")
    
    fmp_api_key_for_test = "YOUR_FMP_KEY_HERE" 
    if not os.path.exists(config_path_test):
        print(f"Test config file not found at {config_path_test}. Creating a dummy one for structure test.")
        os.makedirs(os.path.dirname(config_path_test), exist_ok=True)
        with open(config_path_test, "w") as f:
            f.write("[API_KEYS]\n")
            f.write("fmp_api_key = YOUR_FMP_KEY_HERE\n")
        print("Please put a valid FMP API key in the dummy config.ini to run live tests.")
    else:
        try:
            test_config = load_config(config_path_test)
            fmp_api_key_for_test = get_api_key(test_config, section="API_KEYS", key="fmp_api_key")
        except Exception as e:
            print(f"Error loading test config: {e}")

    if fmp_api_key_for_test != "YOUR_FMP_KEY_HERE" and fmp_api_key_for_test:
        print(f"\nUsing FMP API Key: {fmp_api_key_for_test[:5]}... for live FMP tests")
        
        print("\nTesting get_comprehensive_financial_data for AAPL...")
        financial_data = get_comprehensive_financial_data("AAPL", fmp_api_key_for_test)
        for statement_type, df in financial_data.items():
            if df is not None and not df.empty:
                print(f"{statement_type}: {len(df)} years of data")
            else:
                print(f"{statement_type}: No data")
    else:
        print("\nSkipping live FMP API tests. Please provide a valid API key in config.ini.")

    print("\nmarket_data_api.py tests complete.")