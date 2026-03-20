"""Equity research agents module."""

from .tagline_agent import tagline_agent
from .company_overview_agent import company_overview_agent
from .investment_overview_agent import investment_overview_agent
from .valuation_overview_agent import valuation_overview_agent
from .risks_agent import risks_agent
from .competitor_analysis_agent import competitor_analysis_agent
from .major_takeaways_agent import major_takeaways_agent
from .agent_manager import EquityResearchAgentManager

__all__ = [
    'tagline_agent',
    'company_overview_agent', 
    'investment_overview_agent',
    'valuation_overview_agent',
    'risks_agent',
    'competitor_analysis_agent',
    'major_takeaways_agent',
    'EquityResearchAgentManager'
]
