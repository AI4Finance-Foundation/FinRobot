#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import numpy as np

def clean_financial_number(x):
    """Cleans a string representing a financial number into a float."""
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        # Remove commas, parentheses for negatives, and strip whitespace
        x = x.replace(',', '').replace('(', '-').replace(')', '').strip()
        try:
            return float(x)
        except ValueError:
            return np.nan
    return np.nan

def extract_historical_metrics_from_api_data(financial_data: dict) -> pd.DataFrame | None:
    """Extracts and combines historical financial metrics from FMP API data.

    Args:
        financial_data: Dictionary containing DataFrames from FMP API
                       Expected keys: 'income_statement', 'balance_sheet', 'cash_flow', 'ratios', 'key_metrics'

    Returns:
        A pandas DataFrame with combined and cleaned historical metrics, or None if an error occurs.
    """
    
    income_df = financial_data.get('income_statement')
    balance_df = financial_data.get('balance_sheet')
    cash_flow_df = financial_data.get('cash_flow')
    ratios_df = financial_data.get('ratios')
    key_metrics_df = financial_data.get('key_metrics')
    
    if income_df is None or income_df.empty:
        print("Error: Income statement data is required but not available.")
        return None

    # Sort by date (most recent first) and extract years
    income_df = income_df.sort_values('date', ascending=False).reset_index(drop=True)
    
    # Create year labels (e.g., 2024A, 2023A, etc.)
    years = []
    for _, row in income_df.iterrows():
        year = row['year']
        year_label = f"{year}A"  # A for Actual
        years.append(year_label)
    
    if not years:
        print("No valid years found in income statement data.")
        return None

    # Define metrics to extract (including new EPS and PE Ratio)
    output_metrics_order = [
        'Revenue', 'Cost of Operations', 'SG&A',
        'Contribution Profit', 'Contribution Margin',
        'EBITDA', 'EBITDA Margin', 'SG&A Margin',
        'Revenue Growth', 'EPS', 'PE Ratio'
    ]
    
    # Initialize the final data structure
    final_data_dict = {'metrics': output_metrics_order}
    for year in years:
        final_data_dict[year] = [None] * len(output_metrics_order)  # Use None instead of np.nan for mixed types

    # Extract data for each year
    for i, (_, row) in enumerate(income_df.iterrows()):
        year_label = years[i]
        year_value = row['year']
        
        # Extract basic metrics from income statement
        # Try multiple field names as FMP API can use different naming conventions
        revenue = (row.get('revenue') or 
                  row.get('totalRevenue') or 
                  row.get('netSales') or 
                  row.get('totalNetSales'))
        
        cost_of_revenue = (row.get('costOfRevenue') or 
                          row.get('costOfGoodsSold') or 
                          row.get('totalCostOfSales'))
        
        gross_profit = row.get('grossProfit')
        operating_expenses = row.get('operatingExpenses')
        
        selling_general_admin = (row.get('sellingGeneralAndAdministrativeExpenses') or 
                               row.get('sellingAndMarketingExpenses') or
                               row.get('sellingGeneralAdministrative'))
        
        ebitda = row.get('ebitda')
        
        # Extract EPS from income statement
        eps = (row.get('eps') or 
               row.get('epsdiluted') or 
               row.get('netIncomePerShare'))
        
        # Calculate derived metrics if not directly available
        if revenue and cost_of_revenue:
            contribution_profit = revenue - cost_of_revenue
        elif gross_profit:
            contribution_profit = gross_profit
        else:
            contribution_profit = None
            
        # Store basic metrics
        metrics_idx = {metric: idx for idx, metric in enumerate(output_metrics_order)}
        
        if revenue:
            final_data_dict[year_label][metrics_idx['Revenue']] = revenue
            
        if cost_of_revenue:
            final_data_dict[year_label][metrics_idx['Cost of Operations']] = cost_of_revenue
            
        if selling_general_admin:
            final_data_dict[year_label][metrics_idx['SG&A']] = selling_general_admin
            
        if contribution_profit:
            final_data_dict[year_label][metrics_idx['Contribution Profit']] = contribution_profit
            
        if ebitda:
            final_data_dict[year_label][metrics_idx['EBITDA']] = ebitda
            
        if eps:
            final_data_dict[year_label][metrics_idx['EPS']] = eps
        
        # Extract PE Ratio from ratios or key_metrics if available
        pe_ratio = None
        if ratios_df is not None and not ratios_df.empty:
            ratios_year_data = ratios_df[ratios_df['year'] == year_value]
            if not ratios_year_data.empty:
                pe_ratio = (ratios_year_data.iloc[0].get('priceEarningsRatio') or 
                           ratios_year_data.iloc[0].get('peRatio'))
        
        if pe_ratio is None and key_metrics_df is not None and not key_metrics_df.empty:
            key_metrics_year_data = key_metrics_df[key_metrics_df['year'] == year_value]
            if not key_metrics_year_data.empty:
                pe_ratio = (key_metrics_year_data.iloc[0].get('peRatio') or
                           key_metrics_year_data.iloc[0].get('priceEarningsRatio'))
        
        if pe_ratio:
            final_data_dict[year_label][metrics_idx['PE Ratio']] = pe_ratio

    # Convert to DataFrame with object dtype to handle mixed types (numbers and percentages)
    df_combined = pd.DataFrame(final_data_dict).astype('object')

    # Calculate remaining derived metrics
    for year in years:
        rev = df_combined.loc[df_combined['metrics'] == 'Revenue', year].values[0]
        cost = df_combined.loc[df_combined['metrics'] == 'Cost of Operations', year].values[0]
        sga = df_combined.loc[df_combined['metrics'] == 'SG&A', year].values[0]
        contrib_profit = df_combined.loc[df_combined['metrics'] == 'Contribution Profit', year].values[0]
        ebitda = df_combined.loc[df_combined['metrics'] == 'EBITDA', year].values[0]

        # Calculate margins
        if pd.notna(rev) and rev != 0:
            if pd.notna(contrib_profit):
                contrib_margin = contrib_profit / rev
                df_combined.loc[df_combined['metrics'] == 'Contribution Margin', year] = f"{contrib_margin*100:.1f}%"
                
            if pd.notna(ebitda):
                ebitda_margin = ebitda / rev
                df_combined.loc[df_combined['metrics'] == 'EBITDA Margin', year] = f"{ebitda_margin*100:.1f}%"
                
            if pd.notna(sga):
                sga_margin = sga / rev
                df_combined.loc[df_combined['metrics'] == 'SG&A Margin', year] = f"{sga_margin*100:.1f}%"

    # Calculate revenue growth rates
    revenue_values = []
    for year in reversed(years):  # Start from oldest to newest
        rev = df_combined.loc[df_combined['metrics'] == 'Revenue', year].values[0]
        revenue_values.append(rev)
    
    growth_rates = [np.nan]  # First year has no previous year to compare
    for i in range(1, len(revenue_values)):
        prev_rev, curr_rev = revenue_values[i-1], revenue_values[i]
        if pd.notna(prev_rev) and pd.notna(curr_rev) and prev_rev != 0:
            growth_rate = (curr_rev - prev_rev) / prev_rev
            growth_rates.append(growth_rate)
        else:
            growth_rates.append(np.nan)
    
    # Apply growth rates (reverse order to match years)
    for i, year in enumerate(reversed(years)):
        growth_rate = growth_rates[i]
        df_combined.loc[df_combined['metrics'] == 'Revenue Growth', year] = f"{growth_rate*100:.1f}%" if pd.notna(growth_rate) else 'N/A'

    return df_combined

def extract_historical_metrics_from_pdf_data(dataframes, table_config):
    """Extracts and combines historical financial metrics from a list of DataFrames (extracted from PDFs).
    
    This function is kept for backward compatibility with PDF-based processing.

    Args:
        dataframes: A list of pandas DataFrames, each from a PDF report table.
                    Expected to be in chronological order (e.g., [df_23_22, df_21_20, df_19_18]).
        table_config: A list of dictionaries, each defining how to extract data for a pair of years from a dataframe.

    Returns:
        A pandas DataFrame with combined and cleaned historical metrics, or None if an error occurs.
    """
    if not dataframes or not table_config or len(dataframes) != len(table_config):
        print("Error: DataFrames list and table_config list must be non-empty and of the same length.")
        return None

    all_metrics_data = {}

    for i, config in enumerate(table_config):
        df = dataframes[config["df_index"]]
        if df is None or df.empty:
            print(f"Warning: DataFrame at index {config['df_index']} is empty or None. Skipping.")
            continue

        # Basic cleaning: remove rows that are likely headers or separators within the data block
        df = df[~df[0].astype(str).str.contains("Years Ended|Year Ended", case=False, na=False)]
        df = df.reset_index(drop=True)

        def get_values_from_df(label_list, df_table):
            """Helper to find the first matching label and return its corresponding values."""
            for label in label_list:
                row = df_table[df_table[0].astype(str).str.contains(label, case=False, na=False)]
                if not row.empty:
                    # Data is in columns 2 and 4 based on debug output
                    val1 = clean_financial_number(row.iloc[0, 2]) if len(row.iloc[0]) > 2 else None  # Column 2: 2024 data
                    val2 = clean_financial_number(row.iloc[0, 4]) if len(row.iloc[0]) > 4 else None  # Column 4: 2023 data
                    return [val1, val2]
            return [None, None]

        current_year_pair_metrics = {}
        current_year_pair_metrics["Revenue"] = get_values_from_df([config["revenue_label"], "Total revenues"], df)
        current_year_pair_metrics["Cost of Operations"] = get_values_from_df([config["cost_label"], "Cost of sales"], df)
        current_year_pair_metrics["SG&A"] = get_values_from_df([config["sga_label"], "Selling, general & administrative"], df)

        # Store these extracted metrics, mapping them to the correct years
        for metric_name, values in current_year_pair_metrics.items():
            if metric_name not in all_metrics_data:
                all_metrics_data[metric_name] = {}
            if values[0] is not None: # Value for the first year in config (e.g., 2023A)
                 all_metrics_data[metric_name][config["years"][0]] = values[0]
            if len(values) > 1 and values[1] is not None: # Value for the second year in config (e.g., 2022A)
                 all_metrics_data[metric_name][config["years"][1]] = values[1]

    # Consolidate into the final structure
    output_metrics_order = [
        'Revenue', 'Cost of Operations', 'SG&A',
        'Contribution Profit', 'Contribution Margin',
        'EBITDA', 'EBITDA Margin', 'SG&A Margin'
    ]
    
    collected_years = sorted(list(set(y for metrics in all_metrics_data.values() for y in metrics.keys())))
    if not collected_years:
        print("No data collected from tables.")
        return None

    final_data_dict = {'metrics': output_metrics_order}
    for year in collected_years:
        final_data_dict[year] = [None] * len(output_metrics_order)  # Use None for mixed types

    for i, metric_label in enumerate(output_metrics_order):
        if metric_label in ["Revenue", "Cost of Operations", "SG&A"]:
            if metric_label in all_metrics_data:
                for year in collected_years:
                    final_data_dict[year][i] = all_metrics_data[metric_label].get(year, None)

    df_combined = pd.DataFrame(final_data_dict).astype('object')  # Ensure object dtype

    # Calculate derived metrics for each year
    for year in collected_years:
        rev = df_combined.loc[df_combined['metrics'] == 'Revenue', year].values[0]
        cost = df_combined.loc[df_combined['metrics'] == 'Cost of Operations', year].values[0]
        sga = df_combined.loc[df_combined['metrics'] == 'SG&A', year].values[0]

        contrib_profit = np.nan
        ebitda = np.nan

        if pd.notna(rev) and pd.notna(cost):
            contrib_profit = rev - cost
            df_combined.loc[df_combined['metrics'] == 'Contribution Profit', year] = round(contrib_profit, 2)
            if rev != 0:
                contrib_margin = contrib_profit / rev
                df_combined.loc[df_combined['metrics'] == 'Contribution Margin', year] = f"{contrib_margin*100:.1f}%"
        
        if pd.notna(contrib_profit) and pd.notna(sga):
            ebitda = contrib_profit - sga
            df_combined.loc[df_combined['metrics'] == 'EBITDA', year] = round(ebitda, 2)
            if rev != 0:
                ebitda_margin = ebitda / rev
                df_combined.loc[df_combined['metrics'] == 'EBITDA Margin', year] = f"{ebitda_margin*100:.1f}%"

        if pd.notna(rev) and rev != 0 and pd.notna(sga):
            sga_margin = sga / rev
            df_combined.loc[df_combined['metrics'] == 'SG&A Margin', year] = f"{sga_margin*100:.1f}%"
        
    return df_combined

def calculate_growth_and_forecasts(df_historical: pd.DataFrame, forecast_config: dict) -> pd.DataFrame:
    """Appends growth rates and forecasts to the historical metrics DataFrame."""
    df_final = df_historical.copy().astype('object')  # Ensure object dtype for mixed types
    actual_years = sorted([col for col in df_final.columns if isinstance(col, str) and col.endswith('A')])
    forecast_years = sorted(forecast_config.get("revenue_growth_assumptions", {}).keys())
    
    # Create new columns for forecast years if they don't exist
    for f_year in forecast_years:
        if f_year not in df_final.columns:
            df_final[f_year] = None  # Use None instead of np.nan

    # Calculate Revenue Growth YoY for actual years (if not already present)
    if not (df_final['metrics'] == 'Revenue Growth').any():
        # Add 'Revenue Growth' row if it doesn't exist
        new_row = pd.DataFrame([{'metrics': 'Revenue Growth'}]).astype('object')
        for col in df_final.columns:
            if col != 'metrics' and col not in new_row.columns:
                new_row[col] = None
        df_final = pd.concat([df_final, new_row], ignore_index=True)

    # Calculate historical growth rates
    revenue_values_actual = [df_final.loc[df_final['metrics'] == 'Revenue', y].values[0] for y in actual_years]
    growth_rates_actual = [np.nan]
    for i in range(1, len(revenue_values_actual)):
        prev, curr = revenue_values_actual[i-1], revenue_values_actual[i]
        if pd.notna(prev) and pd.notna(curr) and prev != 0:
            growth_rates_actual.append((curr - prev) / prev)
        else:
            growth_rates_actual.append(np.nan)

    # Update historical growth rates
    for i, year_col in enumerate(actual_years):
        rate = growth_rates_actual[i]
        df_final.loc[df_final['metrics'] == 'Revenue Growth', year_col] = f"{rate*100:.1f}%" if pd.notna(rate) else 'N/A'

    # Forecast Future Revenue
    last_actual_revenue_year = forecast_config["revenue_base_year"]
    if last_actual_revenue_year not in df_final.columns:
        print(f"Error: Revenue base year {last_actual_revenue_year} not found in historical data.")
        return df_final
        
    current_revenue = df_final.loc[df_final['metrics'] == 'Revenue', last_actual_revenue_year].values[0]
    growth_rates_forecast = []

    for f_year in forecast_years:
        growth_assumption = forecast_config["revenue_growth_assumptions"][f_year]
        if pd.notna(current_revenue):
            current_revenue *= (1 + growth_assumption)
            df_final.loc[df_final['metrics'] == 'Revenue', f_year] = round(current_revenue, 2)
            growth_rates_forecast.append(growth_assumption)
        else:
            growth_rates_forecast.append(np.nan)

    # Update Revenue Growth row for forecast years
    for i, f_year in enumerate(forecast_years):
        rate = growth_rates_forecast[i]
        df_final.loc[df_final['metrics'] == 'Revenue Growth', f_year] = f"{rate*100:.1f}%" if pd.notna(rate) else 'N/A'
    
    # Forecast Margins and back-calculate values
    for metric, improvement in forecast_config.get("margin_improvement", {}).items():
        base_margin_str = str(df_final.loc[df_final['metrics'] == metric, last_actual_revenue_year].values[0])
        if '%' in base_margin_str:
            current_margin = float(base_margin_str.replace('%','')) / 100
            for f_year in forecast_years:
                current_margin += improvement
                df_final.loc[df_final['metrics'] == metric, f_year] = f"{current_margin*100:.1f}%"

    # Forecast SG&A margin
    sga_margin_change = forecast_config.get("sga_margin_change", 0)
    base_sga_margin_str = str(df_final.loc[df_final['metrics'] == 'SG&A Margin', last_actual_revenue_year].values[0])
    if '%' in base_sga_margin_str:
        current_sga_margin = float(base_sga_margin_str.replace('%','')) / 100
        for f_year in forecast_years:
            current_sga_margin += sga_margin_change
            df_final.loc[df_final['metrics'] == 'SG&A Margin', f_year] = f"{current_sga_margin*100:.1f}%"
            rev_forecast = df_final.loc[df_final['metrics'] == 'Revenue', f_year].values[0]
            if pd.notna(rev_forecast):
                sga_forecast = rev_forecast * current_sga_margin
                df_final.loc[df_final['metrics'] == 'SG&A', f_year] = round(sga_forecast, 2)
    
    # Forecast EPS and PE Ratio for future years
    # For EPS, assume it grows proportionally with net income/revenue improvement
    base_eps = df_final.loc[df_final['metrics'] == 'EPS', last_actual_revenue_year].values[0]
    base_pe = df_final.loc[df_final['metrics'] == 'PE Ratio', last_actual_revenue_year].values[0]
    
    if pd.notna(base_eps):
        current_eps = base_eps
        for f_year in forecast_years:
            # Assume EPS grows with revenue growth + margin improvements
            revenue_growth = forecast_config["revenue_growth_assumptions"][f_year]
            margin_improvement = forecast_config.get("margin_improvement", {}).get("EBITDA Margin", 0)
            eps_growth_factor = (1 + revenue_growth) * (1 + margin_improvement)
            current_eps *= eps_growth_factor
            df_final.loc[df_final['metrics'] == 'EPS', f_year] = round(current_eps, 2)
    
    # For PE Ratio, assume it remains relatively stable or slightly decreases (conservative assumption)
    if pd.notna(base_pe):
        current_pe = base_pe
        for i, f_year in enumerate(forecast_years):
            # Slightly decrease PE over time (assuming multiple compression)
            pe_decline_factor = 0.95 ** (i + 1)  # 5% decline per year
            current_pe_forecast = current_pe * pe_decline_factor
            df_final.loc[df_final['metrics'] == 'PE Ratio', f_year] = round(current_pe_forecast, 1)
    
    # Recalculate other metrics based on forecasted margins/values
    for f_year in forecast_years:
        rev = df_final.loc[df_final['metrics'] == 'Revenue', f_year].values[0]
        sga = df_final.loc[df_final['metrics'] == 'SG&A', f_year].values[0]
        
        # Calculate based on Contribution Margin
        contrib_margin_str = str(df_final.loc[df_final['metrics'] == 'Contribution Margin', f_year].values[0])
        if pd.notna(rev) and '%' in contrib_margin_str:
            contrib_margin = float(contrib_margin_str.replace('%','')) / 100
            contrib_profit = rev * contrib_margin
            cost_of_ops = rev - contrib_profit
            df_final.loc[df_final['metrics'] == 'Cost of Operations', f_year] = round(cost_of_ops, 2)
            df_final.loc[df_final['metrics'] == 'Contribution Profit', f_year] = round(contrib_profit, 2)
            if pd.notna(sga):
                ebitda = contrib_profit - sga
                df_final.loc[df_final['metrics'] == 'EBITDA', f_year] = round(ebitda, 2)
                if rev != 0:
                    ebitda_margin = ebitda / rev
                    df_final.loc[df_final['metrics'] == 'EBITDA Margin', f_year] = f"{ebitda_margin*100:.1f}%"

    # Calculate CAGR
    cagr_start_year = actual_years[0] if actual_years else None
    cagr_end_year = actual_years[-1] if actual_years else None
    if cagr_start_year and cagr_end_year and cagr_start_year != cagr_end_year:
        rev_start = df_final.loc[df_final['metrics'] == 'Revenue', cagr_start_year].values[0]
        rev_end = df_final.loc[df_final['metrics'] == 'Revenue', cagr_end_year].values[0]
        num_years = int(cagr_end_year.replace('A','')) - int(cagr_start_year.replace('A',''))
        if pd.notna(rev_start) and pd.notna(rev_end) and rev_start > 0 and num_years > 0:
            cagr = (rev_end / rev_start)**(1/num_years) - 1
            df_final['CAGR'] = pd.Series(['N/A'] * len(df_final), dtype='object')
            df_final.loc[df_final['metrics'] == 'Revenue', 'CAGR'] = f"{cagr*100:.1f}%"
    
    # Reorder columns to be chronological
    ordered_cols = ['metrics'] + actual_years + forecast_years
    if 'CAGR' in df_final.columns:
        ordered_cols.append('CAGR')
    df_final = df_final[ordered_cols]

    return df_final

if __name__ == "__main__":
    print("Testing API-based financial_data_processor.py...")
    
    # Create sample API data structure for testing
    sample_income_data = pd.DataFrame([
        {
            'date': '2024-09-30',
            'year': 2024,
            'revenue': 385603000000,
            'costOfRevenue': 210352000000,
            'grossProfit': 175251000000,
            'sellingGeneralAndAdministrativeExpenses': 26027000000,
            'ebitda': 131000000000,
            'eps': 6.08
        },
        {
            'date': '2023-09-30', 
            'year': 2023,
            'revenue': 383285000000,
            'costOfRevenue': 214137000000,
            'grossProfit': 169148000000,
            'sellingGeneralAndAdministrativeExpenses': 24932000000,
            'ebitda': 123000000000,
            'eps': 6.16
        },
        {
            'date': '2022-09-30', 
            'year': 2022,
            'revenue': 394328000000,
            'costOfRevenue': 223546000000,
            'grossProfit': 170782000000,
            'sellingGeneralAndAdministrativeExpenses': 25094000000,
            'ebitda': 130541000000,
            'eps': 6.11
        }
    ])
    
    sample_ratios_data = pd.DataFrame([
        {'date': '2024-09-30', 'year': 2024, 'priceEarningsRatio': 28.5},
        {'date': '2023-09-30', 'year': 2023, 'priceEarningsRatio': 26.2},
        {'date': '2022-09-30', 'year': 2022, 'priceEarningsRatio': 24.8}
    ])
    
    sample_financial_data = {
        'income_statement': sample_income_data,
        'balance_sheet': None,
        'cash_flow': None,
        'ratios': sample_ratios_data,
        'key_metrics': None
    }
    
    print("Testing extract_historical_metrics_from_api_data...")
    historical_df = extract_historical_metrics_from_api_data(sample_financial_data)
    if historical_df is not None:
        print("Historical metrics extracted successfully:")
        print(historical_df)
        
        print("\nTesting calculate_growth_and_forecasts...")
        forecast_config = {
            "revenue_base_year": "2024A",
            "revenue_growth_assumptions": {"2025E": 0.05, "2026E": 0.06}, 
            "margin_improvement": {"Contribution Margin": 0.01, "EBITDA Margin": 0.01},
            "sga_margin_change": -0.005
        }
        
        final_df = calculate_growth_and_forecasts(historical_df, forecast_config)
        print("Final metrics with forecasts:")
        print(final_df)
    else:
        print("Failed to extract historical metrics")
    
    print("\nAPI-based financial_data_processor.py tests complete.")