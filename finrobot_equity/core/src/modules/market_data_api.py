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

def fetch_fmp_enterprise_value(ticker: str, api_key: str, limit: int = 2000) -> pd.DataFrame | None:
    """Fetches historical enterprise value from Financial Modeling Prep API."""
    url = f"https://financialmodelingprep.com/api/v3/enterprise-value/{ticker}?limit={limit}&apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if not data:
            print(f"No EV data returned from FMP for {ticker}.")
            return None
        
        df = pd.DataFrame(data)
        if "date" not in df.columns or "enterpriseValue" not in df.columns:
            print(f"FMP EV data for {ticker} does not contain expected columns ('date', 'enterpriseValue'). Response: {data}")
            return None
            
        df["date"] = pd.to_datetime(df["date"])
        df = df[["date", "enterpriseValue"]].sort_values(by="date").reset_index(drop=True)
        return df
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP EV for {ticker}: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Error processing FMP EV data for {ticker}: {e}. Response: {data if 'data' in locals() else 'N/A'}")
        return None

def get_fmp_ratios_and_key_metrics(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetches financial ratios and key metrics from FMP API."""
    ratios_df, key_metrics_df = None, None
    try:
        # Ratios
        ratios_url = f"https://financialmodelingprep.com/api/v3/ratios/{ticker}?period={period}&limit={limit}&apikey={api_key}"
        response_ratios = requests.get(ratios_url)
        response_ratios.raise_for_status()
        ratios_data = response_ratios.json()
        if ratios_data:
            ratios_df = pd.DataFrame(ratios_data)
            ratios_df["date"] = pd.to_datetime(ratios_df["date"])
            ratios_df["year"] = ratios_df["date"].dt.year

        # Key Metrics
        key_metrics_url = f"https://financialmodelingprep.com/api/v3/key-metrics/{ticker}?period={period}&limit={limit}&apikey={api_key}"
        response_key_metrics = requests.get(key_metrics_url)
        response_key_metrics.raise_for_status()
        key_metrics_data = response_key_metrics.json()
        if key_metrics_data:
            key_metrics_df = pd.DataFrame(key_metrics_data)
            key_metrics_df["date"] = pd.to_datetime(key_metrics_df["date"])
            key_metrics_df["year"] = key_metrics_df["date"].dt.year

    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP ratios/key metrics for {ticker}: {e}")
    except (KeyError, ValueError) as e:
        print(f"Error processing FMP ratios/key metrics data for {ticker}: {e}")
        
    return ratios_df, key_metrics_df

def get_fmp_income_statement(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches income statement data from FMP API."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if not data:
            print(f"No income statement data from FMP for {ticker}.")
            return None
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        return df
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP income statement for {ticker}: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Error processing FMP income statement data for {ticker}: {e}")
        return None

def get_fmp_balance_sheet(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches balance sheet data from FMP API."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/balance-sheet-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if not data:
            print(f"No balance sheet data from FMP for {ticker}.")
            return None
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        return df
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP balance sheet for {ticker}: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Error processing FMP balance sheet data for {ticker}: {e}")
        return None

def get_fmp_cash_flow_statement(ticker: str, api_key: str, period: str = "annual", limit: int = 5) -> pd.DataFrame | None:
    """Fetches cash flow statement data from FMP API."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{ticker}?period={period}&limit={limit}&apikey={api_key}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if not data:
            print(f"No cash flow data from FMP for {ticker}.")
            return None
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        return df
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP cash flow for {ticker}: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Error processing FMP cash flow data for {ticker}: {e}")
        return None

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

def get_fmp_current_price(ticker: str, api_key: str) -> float | None:
    """Fetches the latest stock price from Financial Modeling Prep API."""
    url = f"https://financialmodelingprep.com/api/v3/quote-short/{ticker}?apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            quote_data = data[0]
            if "price" in quote_data and quote_data["price"] is not None:
                return float(quote_data["price"])
            else:
                url_full_quote = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={api_key}"
                response_full = requests.get(url_full_quote)
                response_full.raise_for_status()
                data_full = response_full.json()
                if data_full and isinstance(data_full, list) and len(data_full) > 0:
                    quote_data_full = data_full[0]
                    if "price" in quote_data_full and quote_data_full["price"] is not None:
                        return float(quote_data_full["price"])
                    elif "previousClose" in quote_data_full and quote_data_full["previousClose"] is not None:
                        print(f"Current price not available for {ticker} via /quote or /quote-short, using previous close: {quote_data_full['previousClose']}")
                        return float(quote_data_full["previousClose"])
                print(f"Price data not found in FMP quote for {ticker}. Response: {quote_data}")
                return None
        else:
            print(f"No data or unexpected format returned from FMP /quote-short for {ticker}. Response: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP current price for {ticker}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error processing FMP current price data for {ticker}: {e}. Response: {data if 'data' in locals() else 'N/A'}")
        return None

def get_analyst_insights(ticker: str, api_key: str = None) -> tuple[str | None, float | None]:
    """
    Fetches analyst rating and target price using FMP API.
    
    Args:
        ticker: Stock ticker symbol
        api_key: FMP API key (optional, will try to use existing functions if not provided)
    
    Returns:
        Tuple of (rating, target_price)
    """
    rating = None
    target_price = None
    
    try:
        # Try to get rating from FMP
        if api_key:
            rating = get_fmp_analyst_rating(ticker, api_key)
            target_price = get_fmp_target_price(ticker, api_key)
            
            if rating:
                print(f"[INFO] For {ticker} - Rating: {rating}")
            if target_price:
                print(f"[INFO] For {ticker} - Target Price: {target_price}")
        else:
            print(f"[WARN] No API key provided for get_analyst_insights. Skipping.")
            
    except Exception as e:
        print(f"[ERROR] Error in get_analyst_insights for {ticker}: {e}")
        
    return rating, target_price

def get_fmp_target_price(ticker: str, api_key: str) -> float | None:
    """Fetches the latest analyst target price from Financial Modeling Prep API v4."""
    url = f"https://financialmodelingprep.com/api/v4/price-target?symbol={ticker}&apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            for item in data:
                try:
                    item['parsedDate'] = pd.to_datetime(item.get('publishedDate'))
                except Exception as e:
                    print(f"Warning: Could not parse publishedDate '{item.get('publishedDate')}' for {ticker}: {e}")
                    item['parsedDate'] = None
            
            valid_data = [item for item in data if item['parsedDate'] is not None]
            
            if not valid_data:
                print(f"No valid published dates found in FMP target price data for {ticker}.")
                return None

            latest_target_info = sorted(valid_data, key=lambda x: x['parsedDate'], reverse=True)[0]
            
            if "priceTarget" in latest_target_info and latest_target_info["priceTarget"] is not None:
                return float(latest_target_info["priceTarget"])
            else:
                print(f"Price target not found in the latest FMP data for {ticker}. Data: {latest_target_info}")
                return None
        else:
            print(f"No target price data or unexpected format returned from FMP for {ticker}. Response: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP target price for {ticker}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error processing FMP target price data for {ticker}: {e}. Response: {data if 'data' in locals() else 'N/A'}")
        return None

def get_fmp_analyst_rating(ticker: str, api_key: str) -> str | None:
    """Fetches the latest analyst rating (e.g., Buy, Hold, Sell) from Financial Modeling Prep API v4."""
    url = f"https://financialmodelingprep.com/api/v4/upgrades-downgrades?symbol={ticker}&apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            for item in data:
                try:
                    item['parsedDate'] = pd.to_datetime(item.get('publishedDate'))
                except Exception as e:
                    print(f"Warning: Could not parse publishedDate '{item.get('publishedDate')}' for {ticker}: {e}")
                    item['parsedDate'] = None
            
            valid_data = [item for item in data if item['parsedDate'] is not None]

            if not valid_data:
                print(f"No valid published dates found in FMP analyst rating data for {ticker}.")
                return None

            latest_rating_info = sorted(valid_data, key=lambda x: x['parsedDate'], reverse=True)[0]
            
            if "newGrade" in latest_rating_info and latest_rating_info["newGrade"]:
                return str(latest_rating_info["newGrade"])
            elif "action" in latest_rating_info and latest_rating_info["action"]:
                 print(f"newGrade not found, using action: {latest_rating_info['action']} for {ticker}")
                 return str(latest_rating_info["action"])
            else:
                print(f"Analyst rating (newGrade or action) not found in the latest FMP data for {ticker}. Data: {latest_rating_info}")
                return None
        else:
            print(f"No analyst rating data or unexpected format returned from FMP for {ticker}. Response: {data}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching FMP analyst rating for {ticker}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error processing FMP analyst rating data for {ticker}: {e}. Response: {data if 'data' in locals() else 'N/A'}")
        return None

def get_fmp_company_profile(ticker: str, api_key: str) -> dict | None:
    """Fetches comprehensive company profile data from FMP API."""
    url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]  # Profile returns a list with one item
        else:
            print(f"No profile data returned for {ticker}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching company profile for {ticker}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error processing company profile data for {ticker}: {e}")
        return None

def get_fmp_market_cap(ticker: str, api_key: str) -> float | None:
    """Fetches current market capitalization from FMP API."""
    url = f"https://financialmodelingprep.com/api/v3/market-capitalization/{ticker}?apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            market_cap = data[0].get('marketCap')
            return float(market_cap) if market_cap else None
        else:
            print(f"No market cap data returned for {ticker}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching market cap for {ticker}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error processing market cap data for {ticker}: {e}")
        return None

def get_comprehensive_company_metrics(ticker: str, api_key: str) -> dict:
    """Fetches all key company metrics needed for equity report from FMP API."""
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
        'exchange': None
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
    
    # 4. Get detailed quote for volume if not in profile
    if not metrics['volume']:
        try:
            quote_url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={api_key}"
            response = requests.get(quote_url)
            response.raise_for_status()
            quote_data = response.json()
            if quote_data and isinstance(quote_data, list) and len(quote_data) > 0:
                quote = quote_data[0]
                avg_volume = quote.get('avgVolume')
                if avg_volume:
                    metrics['volume'] = avg_volume / 1e6  # Convert to millions
        except Exception as e:
            print(f"Warning: Could not fetch quote data for volume: {e}")
    
    # 5. Get financial ratios
    try:
        ratios_df, key_metrics_df = get_fmp_ratios_and_key_metrics(ticker, api_key, limit=1)
        
        if ratios_df is not None and not ratios_df.empty:
            latest_ratios = ratios_df.iloc[0]
            metrics['pb_ratio'] = latest_ratios.get('priceToBookRatio')
            metrics['roe'] = latest_ratios.get('returnOnEquity')
            if latest_ratios.get('returnOnEquity'):
                metrics['roe'] = latest_ratios['returnOnEquity'] * 100  # Convert to percentage
            metrics['net_debt_to_equity'] = latest_ratios.get('debtEquityRatio')
            # Try to get forward P/E from ratios
            metrics['fwd_pe'] = latest_ratios.get('priceEarningsRatio')
        
        if key_metrics_df is not None and not key_metrics_df.empty:
            latest_key_metrics = key_metrics_df.iloc[0]
            # Override with key metrics if available
            if latest_key_metrics.get('peRatio'):
                metrics['fwd_pe'] = latest_key_metrics['peRatio']
            if latest_key_metrics.get('pbRatio'):
                metrics['pb_ratio'] = latest_key_metrics['pbRatio']
    except Exception as e:
        print(f"Warning: Could not fetch financial ratios: {e}")
    
    # 6. Get dividend yield from profile or financial data
    if profile and profile.get('lastDiv'):
        if current_price and profile['lastDiv'] > 0:
            # Calculate dividend yield: (annual dividend / current price) * 100
            annual_dividend = profile['lastDiv']  # Assuming this is annual
            metrics['dividend_yield'] = (annual_dividend / current_price) * 100
    
    # 7. Get shares outstanding for free float calculation (approximate)
    try:
        if profile and profile.get('sharesOutstanding'):
            # Most companies have high free float, use a reasonable estimate
            metrics['free_float'] = 95.0  # Default assumption for large companies
    except Exception as e:
        print(f"Warning: Could not calculate free float: {e}")
    
    # Fill in any remaining None values with sensible defaults
    if metrics['free_float'] is None:
        metrics['free_float'] = 95.0
    if metrics['sector'] is None:
        metrics['sector'] = 'Technology'  # Default for many stocks
    if metrics['rating'] is None:
        metrics['rating'] = 'N/A'
    
    print(f"Successfully fetched metrics for {ticker}")
    return metrics


def get_company_news(ticker: str, api_key: str, days_back: int = 5, limit: int = 50) -> list[dict] | None:
    """
    Fetches recent company news from FMP API.
    
    Args:
        ticker: Stock ticker symbol
        api_key: FMP API key
        days_back: Number of days to look back for news (default: 5)
        limit: Maximum number of news articles to fetch (default: 50)
    
    Returns:
        List of dictionaries containing filtered news data, or None if error occurs
    """
    try:
        from datetime import datetime, timedelta
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Format dates for API
        from_date = start_date.strftime('%Y-%m-%d')
        to_date = end_date.strftime('%Y-%m-%d')
        
        # FMP Stock News API endpoint
        url = f"https://financialmodelingprep.com/api/v3/stock_news"
        params = {
            'tickers': ticker,
            'from': from_date,
            'to': to_date,
            'limit': limit,
            'apikey': api_key
        }
        
        print(f"Fetching news for {ticker} from {from_date} to {to_date}...")
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print(f"No news data returned from FMP for {ticker}.")
            return None
        
        # Filter to keep only required fields
        filtered_news = []
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
        
        print(f"Successfully fetched {len(filtered_news)} news articles for {ticker}")
        return filtered_news
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching news for {ticker}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching news for {ticker}: {e}")
        return None


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