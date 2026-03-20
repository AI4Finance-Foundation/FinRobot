"""
FinRobot Equity Research Module

This module provides comprehensive equity research analysis capabilities,
including financial data processing, analysis, and report generation.

Usage:
    from finrobot_equity.core.src.generate_financial_analysis import main as generate_analysis
    from finrobot_equity.core.src.create_equity_report import main as create_report
    
    # Generate financial analysis
    generate_analysis(ticker='NVDA', company_name='NVIDIA')
    
    # Create equity report
    create_report(ticker='NVDA')
"""

__version__ = "0.1.0"
__author__ = "AI4Finance Foundation"
__description__ = "Equity Research Analysis Module for FinRobot"

try:
    from finrobot_equity.core.src.generate_financial_analysis import main as generate_analysis
    from finrobot_equity.core.src.create_equity_report import main as create_report
    
    __all__ = ['generate_analysis', 'create_report']
except ImportError:
    # If core modules are not available, still allow importing the package
    __all__ = []
