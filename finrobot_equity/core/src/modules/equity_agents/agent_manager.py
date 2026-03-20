import pandas as pd
import json
import os
from typing import Dict, Optional
from agents import Runner, RunConfig, ModelSettings  # Import from openai-agents package

# Import from local equity_agents
from .tagline_agent import tagline_agent
from .company_overview_agent import company_overview_agent
from .investment_overview_agent import investment_overview_agent
from .valuation_overview_agent import valuation_overview_agent
from .risks_agent import risks_agent
from .competitor_analysis_agent import competitor_analysis_agent
from .major_takeaways_agent import major_takeaways_agent
from .news_summary_agent import news_summary_agent

class EquityResearchAgentManager:
    """Manager class to coordinate all equity research agents."""
    
    def __init__(self):
        self.agents = {
            'tagline': tagline_agent,
            'company_overview': company_overview_agent,
            'investment_overview': investment_overview_agent, 
            'valuation_overview': valuation_overview_agent,
            'risks': risks_agent,
            'competitor_analysis': competitor_analysis_agent,
            'major_takeaways': major_takeaways_agent,
            'news_summary': news_summary_agent
        }
    
    def _prepare_financial_data_prompt(self, data: Dict, company_name: str, company_ticker: str) -> str:
        """Convert financial data to markdown format for agent consumption."""
        
        financial_metrics = data.get('financial_metrics')
        peer_ebitda = data.get('peer_ebitda')
        peer_ev_ebitda = data.get('peer_ev_ebitda')
        company_news = data.get('company_news')
        
        prompt = f"Financial data for {company_name} ({company_ticker}):\n\n"
        
        if financial_metrics is not None and not financial_metrics.empty:
            prompt += f"## {company_name} Financial Metrics and Forecasts\n"
            prompt += financial_metrics.to_markdown() + "\n\n"
        
        if peer_ebitda is not None and not peer_ebitda.empty:
            prompt += "## Peer EBITDA Comparison\n"
            prompt += peer_ebitda.to_markdown() + "\n\n"
            
        if peer_ev_ebitda is not None and not peer_ev_ebitda.empty:
            prompt += "## Peer EV/EBITDA Comparison\n" 
            prompt += peer_ev_ebitda.to_markdown() + "\n\n"
        
        # Add news data if available
        if company_news is not None and isinstance(company_news, list) and len(company_news) > 0:
            prompt += f"## Recent News for {company_name} ({company_ticker})\n\n"
            for i, article in enumerate(company_news, 1):
                prompt += f"### Article {i}\n"
                prompt += f"**Title:** {article.get('title', 'N/A')}\n"
                prompt += f"**Date:** {article.get('publishedDate', 'N/A')}\n"
                prompt += f"**Summary:** {article.get('text', 'N/A')}\n\n"
        
        return prompt
    
    async def generate_text_section(self, data: Dict, text_type: str, company_name: str, company_ticker: str) -> str:
        """Generate text section using appropriate agent."""
        
        if text_type not in self.agents:
            raise ValueError(f"Unknown text type: {text_type}")
        
        # Prepare the data prompt
        financial_prompt = self._prepare_financial_data_prompt(data, company_name, company_ticker)
        
        # Get the appropriate agent
        agent = self.agents[text_type]
        
        # Check if a custom model is specified via environment variable
        custom_model = os.getenv('OPENAI_MODEL_NAME')
        
        # Run the agent with optional custom model
        if custom_model:
            run_config = RunConfig(
                model_settings=ModelSettings(model=custom_model)
            )
            result = await Runner.run(agent, financial_prompt, run_config=run_config)
        else:
            result = await Runner.run(agent, financial_prompt)
        
        # Field mapping for each text type
        field_mapping = {
            'tagline': 'tagline',
            'company_overview': 'overview',
            'investment_overview': 'investment_update',
            'valuation_overview': 'valuation_analysis',
            'risks': 'risk_analysis',
            'competitor_analysis': 'competitive_analysis',
            'major_takeaways': 'takeaways',
            'news_summary': 'news_summary'
        }
        
        # Extract the text based on the response model with fallback
        try:
            field_name = field_mapping.get(text_type)
            if field_name and hasattr(result.final_output, field_name):
                return getattr(result.final_output, field_name)
            else:
                # Fallback: try to convert the output to string
                return str(result.final_output)
        except Exception as e:
            print(f"Warning: Error extracting field '{field_name}' from agent output: {e}")
            return str(result.final_output) if result.final_output else ""
