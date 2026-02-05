#!/usr/bin/env python3
"""
Advanced XBRL Parser for SEC Filings
Extracts structured financial data from XBRL files
"""

import re
import json
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class XBRLParser:
    """Parse XBRL data from SEC filings"""
    
    def __init__(self):
        self.gaap_mappings = {
            # Income Statement
            'Revenues': ['Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax'],
            'CostOfRevenue': ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold'],
            'GrossProfit': ['GrossProfit'],
            'OperatingExpenses': ['OperatingExpenses'],
            'ResearchAndDevelopment': ['ResearchAndDevelopmentExpense'],
            'SellingGeneralAdmin': ['SellingGeneralAndAdministrativeExpense'],
            'OperatingIncome': ['OperatingIncomeLoss', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxes'],
            'NetIncome': ['NetIncomeLoss', 'ProfitLoss'],
            'EPS': ['EarningsPerShareDiluted', 'EarningsPerShareBasic'],
            
            # Balance Sheet
            'TotalAssets': ['Assets'],
            'CurrentAssets': ['AssetsCurrent'],
            'Cash': ['CashAndCashEquivalentsAtCarryingValue'],
            'Receivables': ['AccountsReceivableNetCurrent'],
            'Inventory': ['InventoryNet'],
            'PPE': ['PropertyPlantAndEquipmentNet'],
            'Intangibles': ['IntangibleAssetsNetExcludingGoodwill'],
            'Goodwill': ['Goodwill'],
            
            'TotalLiabilities': ['Liabilities'],
            'CurrentLiabilities': ['LiabilitiesCurrent'],
            'LongTermDebt': ['LongTermDebtNoncurrent', 'LongTermDebt'],
            'ShareholdersEquity': ['StockholdersEquity'],
            
            # Cash Flow
            'OperatingCashFlow': ['NetCashProvidedByUsedInOperatingActivities'],
            'InvestingCashFlow': ['NetCashProvidedByUsedInInvestingActivities'],
            'FinancingCashFlow': ['NetCashProvidedByUsedInFinancingActivities'],
            'CapitalExpenditures': ['PaymentsToAcquirePropertyPlantAndEquipment'],
            'FreeCashFlow': ['FreeCashFlow'],
            
            # Shares
            'SharesOutstanding': ['CommonStockSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingBasic']
        }
        
        self.context_patterns = {
            'instant': re.compile(r'(\d{4}-\d{2}-\d{2})'),
            'duration': re.compile(r'from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})')
        }
    
    async def fetch_xbrl_from_filing(self, filing_url: str, session: aiohttp.ClientSession) -> Optional[str]:
        """Fetch XBRL data from SEC filing URL"""
        try:
            # First get the filing page
            async with session.get(filing_url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
            
            # Find XBRL document link
            xbrl_link = None
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if 'xml' in href.lower() and ('xbrl' in href.lower() or '_htm.xml' in href):
                    xbrl_link = f"https://www.sec.gov{href}" if href.startswith('/') else href
                    break
            
            if not xbrl_link:
                # Try alternative pattern
                table = soup.find('table', class_='tableFile')
                if table:
                    for row in table.find_all('tr'):
                        cells = row.find_all('td')
                        if len(cells) > 3 and 'EX-101.INS' in cells[3].text:
                            link = cells[2].find('a')
                            if link:
                                xbrl_link = f"https://www.sec.gov{link.get('href')}"
                                break
            
            if xbrl_link:
                async with session.get(xbrl_link) as response:
                    return await response.text()
            
            return None
            
        except aiohttp.ClientError as e:
            logger.error("Network error fetching XBRL: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error fetching XBRL: %s", e)
            return None
    
    def parse_xbrl_string(self, xbrl_content: str) -> Dict[str, Any]:
        """Parse XBRL content and extract financial data"""
        try:
            # Parse XML
            root = ET.fromstring(xbrl_content)
            
            # Extract namespaces
            namespaces = self._extract_namespaces(root)
            
            # Extract contexts (time periods)
            contexts = self._extract_contexts(root, namespaces)
            
            # Extract financial data
            financial_data = self._extract_financial_data(root, namespaces, contexts)
            
            # Organize by statement type
            organized_data = self._organize_financial_data(financial_data)
            
            # Calculate derived metrics
            organized_data['derived_metrics'] = self._calculate_derived_metrics(organized_data)
            
            # Add metadata
            organized_data['metadata'] = {
                'parsing_date': datetime.now().isoformat(),
                'contexts_found': len(contexts),
                'data_points_extracted': sum(len(v) for v in financial_data.values())
            }
            
            return organized_data
            
        except ET.ParseError as e:
            return {'error': f'XML parsing error: {str(e)}'}
        except Exception as e:
            return {'error': f'XBRL parsing error: {str(e)}'}
    
    def _extract_namespaces(self, root: ET.Element) -> Dict[str, str]:
        """Extract XML namespaces"""
        namespaces = {}
        for key, value in root.attrib.items():
            if key.startswith('xmlns:'):
                prefix = key.split(':')[1]
                namespaces[prefix] = value
        return namespaces
    
    def _extract_contexts(self, root: ET.Element, namespaces: Dict[str, str]) -> Dict[str, Dict]:
        """Extract context information (time periods)"""
        contexts = {}
        
        # Look for context elements
        for context in root.findall('.//xbrli:context', namespaces) or root.findall('.//context'):
            context_id = context.get('id')
            if not context_id:
                continue
            
            context_info = {'id': context_id}
            
            # Extract period information
            period = context.find('.//xbrli:period', namespaces) or context.find('.//period')
            if period is not None:
                instant = period.find('.//xbrli:instant', namespaces) or period.find('.//instant')
                if instant is not None:
                    context_info['type'] = 'instant'
                    context_info['date'] = instant.text
                else:
                    start = period.find('.//xbrli:startDate', namespaces) or period.find('.//startDate')
                    end = period.find('.//xbrli:endDate', namespaces) or period.find('.//endDate')
                    if start is not None and end is not None:
                        context_info['type'] = 'duration'
                        context_info['start_date'] = start.text
                        context_info['end_date'] = end.text
            
            contexts[context_id] = context_info
        
        return contexts
    
    def _extract_financial_data(self, root: ET.Element, namespaces: Dict[str, str], 
                               contexts: Dict[str, Dict]) -> Dict[str, List[Dict]]:
        """Extract financial data points"""
        financial_data = {}
        
        # Try to find all numeric facts
        for elem in root.iter():
            # Skip if not a data element
            if elem.tag.startswith('{'):
                namespace, tag = elem.tag.split('}')
                tag_name = tag
            else:
                tag_name = elem.tag
            
            # Check if it's a numeric value
            if elem.text and elem.text.strip():
                try:
                    # Try to parse as number
                    value = float(elem.text.strip().replace(',', ''))
                    
                    # Get context
                    context_ref = elem.get('contextRef')
                    if context_ref and context_ref in contexts:
                        context = contexts[context_ref]
                        
                        # Get unit (for scale)
                        unit_ref = elem.get('unitRef')
                        decimals = elem.get('decimals', '0')
                        
                        # Store the data point
                        if tag_name not in financial_data:
                            financial_data[tag_name] = []
                        
                        financial_data[tag_name].append({
                            'value': value,
                            'context': context,
                            'unit': unit_ref,
                            'decimals': decimals
                        })
                
                except ValueError:
                    # Not a numeric value
                    pass
        
        return financial_data
    
    def _organize_financial_data(self, raw_data: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Organize raw XBRL data into financial statements"""
        organized = {
            'income_statement': {},
            'balance_sheet': {},
            'cash_flow': {},
            'metrics': {},
            'time_series': {}
        }
        
        # Map GAAP concepts to our standard names
        for standard_name, gaap_names in self.gaap_mappings.items():
            for gaap_name in gaap_names:
                # Look for exact matches and partial matches
                for tag_name, values in raw_data.items():
                    if gaap_name.lower() in tag_name.lower():
                        # Determine which statement this belongs to
                        if standard_name in ['Revenues', 'CostOfRevenue', 'GrossProfit', 
                                           'OperatingExpenses', 'ResearchAndDevelopment',
                                           'SellingGeneralAdmin', 'OperatingIncome', 
                                           'NetIncome', 'EPS']:
                            statement = 'income_statement'
                        elif standard_name in ['TotalAssets', 'CurrentAssets', 'Cash',
                                             'Receivables', 'Inventory', 'PPE', 
                                             'Intangibles', 'Goodwill', 'TotalLiabilities',
                                             'CurrentLiabilities', 'LongTermDebt', 
                                             'ShareholdersEquity']:
                            statement = 'balance_sheet'
                        elif standard_name in ['OperatingCashFlow', 'InvestingCashFlow',
                                             'FinancingCashFlow', 'CapitalExpenditures',
                                             'FreeCashFlow']:
                            statement = 'cash_flow'
                        else:
                            statement = 'metrics'
                        
                        # Get the most recent value
                        if values:
                            most_recent = self._get_most_recent_value(values)
                            if most_recent:
                                organized[statement][standard_name] = most_recent
                                
                                # Also build time series
                                organized['time_series'][standard_name] = self._build_time_series(values)
                        
                        break
        
        return organized
    
    def _get_most_recent_value(self, values: List[Dict]) -> Optional[float]:
        """Get the most recent value from a list of data points"""
        # Sort by date (for instant) or end_date (for duration)
        sorted_values = []
        for v in values:
            context = v.get('context', {})
            if context.get('type') == 'instant':
                date_str = context.get('date')
            elif context.get('type') == 'duration':
                date_str = context.get('end_date')
            else:
                continue
            
            if date_str:
                try:
                    date = datetime.fromisoformat(date_str)
                    sorted_values.append((date, v['value']))
                except ValueError:
                    pass
        
        if sorted_values:
            sorted_values.sort(key=lambda x: x[0], reverse=True)
            return sorted_values[0][1]
        
        return None
    
    def _build_time_series(self, values: List[Dict]) -> List[Dict[str, Any]]:
        """Build time series data from values"""
        time_series = []
        
        for v in values:
            context = v.get('context', {})
            if context.get('type') == 'instant':
                date_str = context.get('date')
            elif context.get('type') == 'duration':
                date_str = context.get('end_date')
            else:
                continue
            
            if date_str:
                time_series.append({
                    'date': date_str,
                    'value': v['value'],
                    'period_type': context.get('type')
                })
        
        # Sort by date
        time_series.sort(key=lambda x: x['date'])
        
        return time_series
    
    def _calculate_derived_metrics(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Calculate derived financial metrics"""
        metrics = {}
        
        # Income statement metrics
        income = data.get('income_statement', {})
        if income.get('Revenues') and income.get('NetIncome'):
            metrics['net_margin'] = income['NetIncome'] / income['Revenues']
        
        if income.get('Revenues') and income.get('GrossProfit'):
            metrics['gross_margin'] = income['GrossProfit'] / income['Revenues']
        
        if income.get('Revenues') and income.get('OperatingIncome'):
            metrics['operating_margin'] = income['OperatingIncome'] / income['Revenues']
        
        # Balance sheet metrics  
        balance = data.get('balance_sheet', {})
        if balance.get('CurrentAssets') and balance.get('CurrentLiabilities'):
            metrics['current_ratio'] = balance['CurrentAssets'] / balance['CurrentLiabilities']
        
        if balance.get('TotalAssets') and balance.get('TotalLiabilities'):
            metrics['debt_to_assets'] = balance['TotalLiabilities'] / balance['TotalAssets']
        
        if balance.get('ShareholdersEquity') and income.get('NetIncome'):
            metrics['roe'] = income['NetIncome'] / balance['ShareholdersEquity']
        
        if balance.get('TotalAssets') and income.get('NetIncome'):
            metrics['roa'] = income['NetIncome'] / balance['TotalAssets']
        
        # Cash flow metrics
        cash_flow = data.get('cash_flow', {})
        if cash_flow.get('OperatingCashFlow') and cash_flow.get('CapitalExpenditures'):
            metrics['free_cash_flow'] = (cash_flow['OperatingCashFlow'] - 
                                        abs(cash_flow['CapitalExpenditures']))
        
        # Valuation metrics (would need market data)
        if balance.get('SharesOutstanding') and income.get('EPS'):
            metrics['computed_shares'] = income['NetIncome'] / income['EPS'] if income['EPS'] != 0 else 0
        
        return metrics
    
    def extract_key_metrics(self, xbrl_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key metrics for analysis"""
        return {
            'revenue': xbrl_data.get('income_statement', {}).get('Revenues'),
            'net_income': xbrl_data.get('income_statement', {}).get('NetIncome'),
            'total_assets': xbrl_data.get('balance_sheet', {}).get('TotalAssets'),
            'total_liabilities': xbrl_data.get('balance_sheet', {}).get('TotalLiabilities'),
            'shareholders_equity': xbrl_data.get('balance_sheet', {}).get('ShareholdersEquity'),
            'operating_cash_flow': xbrl_data.get('cash_flow', {}).get('OperatingCashFlow'),
            'free_cash_flow': xbrl_data.get('derived_metrics', {}).get('free_cash_flow'),
            'current_ratio': xbrl_data.get('derived_metrics', {}).get('current_ratio'),
            'roe': xbrl_data.get('derived_metrics', {}).get('roe'),
            'roa': xbrl_data.get('derived_metrics', {}).get('roa'),
            'debt_to_assets': xbrl_data.get('derived_metrics', {}).get('debt_to_assets'),
            'net_margin': xbrl_data.get('derived_metrics', {}).get('net_margin'),
            'gross_margin': xbrl_data.get('derived_metrics', {}).get('gross_margin')
        }