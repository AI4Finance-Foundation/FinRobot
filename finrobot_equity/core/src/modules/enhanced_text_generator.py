#!/usr/bin/env python
# coding: utf-8
"""
增强文本生成器模块
扩展现有文本生成系统，提供更专业的报告内容生成
"""

import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TextGenerationConfig:
    """文本生成配置"""
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 2000
    language: str = "en"


class EnhancedTextGenerator:
    """增强文本生成器 - 生成专业的报告文本内容"""
    
    # 系统提示模板
    SYSTEM_PROMPTS = {
        'executive_summary': """You are a senior equity research analyst. Generate a concise executive summary 
that includes: key investment thesis, target price, rating recommendation, and main catalysts. 
Be specific with numbers and data references.""",
        
        'forecast_methodology': """You are a financial analyst explaining forecast methodology. 
Describe the assumptions, growth drivers, and key metrics used in the financial projections. 
Be transparent about limitations and uncertainties.""",
        
        'catalyst_analysis': """You are analyzing potential catalysts for a stock. 
Identify specific events, their expected timing, probability, and potential impact on stock price. 
Distinguish between upside catalysts and downside risks.""",
        
        'valuation_analysis': """You are a valuation expert. Explain the valuation methodology, 
compare different approaches, and justify the target price. Reference specific multiples and peer comparisons.""",
        
        'investment_recommendation': """You are providing an investment recommendation. 
Be specific about the rating, target price, key risks, and trigger conditions for rating changes. 
Support all conclusions with data references."""
    }
    
    def __init__(self, api_key: str = None, base_url: str = None):
        """
        初始化增强文本生成器
        
        Args:
            api_key: OpenAI API密钥
            base_url: API基础URL（可选）
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.base_url = base_url
        self.config = TextGenerationConfig()
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化OpenAI客户端"""
        try:
            from openai import OpenAI
            if self.base_url:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            else:
                self.client = OpenAI(api_key=self.api_key)
            logger.info("✅ OpenAI client initialized")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize OpenAI client: {e}")
            self.client = None

    def _generate_with_llm(self, system_prompt: str, user_prompt: str) -> str:
        """使用LLM生成文本"""
        if not self.client:
            logger.warning("LLM client not available, using fallback")
            return self._generate_fallback(user_prompt)
        
        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._generate_fallback(user_prompt)
    
    def _generate_fallback(self, context: str) -> str:
        """生成回退文本（当LLM不可用时）"""
        return f"[Content generation pending - Context: {context[:200]}...]"
    
    def _format_currency(self, value: float, billions: bool = True) -> str:
        """格式化货币值"""
        if billions:
            return f"${value/1e9:.1f}B" if value >= 1e9 else f"${value/1e6:.1f}M"
        return f"${value:,.0f}"
    
    def _format_percentage(self, value: float) -> str:
        """格式化百分比"""
        return f"{value:.1f}%"

    # =========================================================================
    # 执行摘要生成
    # =========================================================================
    def generate_executive_summary(self, data: Dict) -> str:
        """
        生成执行摘要
        
        Args:
            data: 包含公司数据、估值和建议的字典
        
        Returns:
            执行摘要文本
        """
        logger.info("Generating executive summary...")
        
        ticker = data.get('ticker', 'N/A')
        company_name = data.get('company_name', ticker)
        current_price = data.get('current_price', 0)
        target_price = data.get('target_price', 0)
        rating = data.get('rating', 'Hold')
        upside = ((target_price / current_price) - 1) * 100 if current_price > 0 else 0
        
        # 构建用户提示
        user_prompt = f"""
Generate an executive summary for {company_name} ({ticker}):

Key Data:
- Current Price: ${current_price:.2f}
- Target Price: ${target_price:.2f}
- Implied Upside: {upside:.1f}%
- Rating: {rating}
- Revenue (LTM): {self._format_currency(data.get('revenue', 0))}
- EBITDA Margin: {self._format_percentage(data.get('ebitda_margin', 0))}
- Key Catalysts: {', '.join(data.get('catalysts', ['N/A'])[:3])}
- Main Risks: {', '.join(data.get('risks', ['N/A'])[:3])}

Generate a 3-4 paragraph executive summary covering:
1. Investment thesis and rating justification
2. Key financial highlights and growth drivers
3. Valuation summary and target price rationale
4. Key risks and catalysts to watch
"""
        
        summary = self._generate_with_llm(
            self.SYSTEM_PROMPTS['executive_summary'],
            user_prompt
        )
        
        logger.info("✅ Executive summary generated")
        return summary

    # =========================================================================
    # 预测方法论生成
    # =========================================================================
    def generate_forecast_methodology(self, forecast_config: Dict) -> str:
        """
        生成预测方法论说明
        
        Args:
            forecast_config: 预测配置和假设
        
        Returns:
            方法论说明文本
        """
        logger.info("Generating forecast methodology...")
        
        user_prompt = f"""
Explain the forecast methodology for this equity analysis:

Forecast Assumptions:
- Revenue Growth Rate (Y1-Y3): {forecast_config.get('revenue_growth', 'N/A')}
- EBITDA Margin Target: {forecast_config.get('ebitda_margin', 'N/A')}
- CapEx as % of Revenue: {forecast_config.get('capex_ratio', 'N/A')}
- Working Capital Assumptions: {forecast_config.get('working_capital', 'N/A')}

Historical Context:
- 3-Year Revenue CAGR: {forecast_config.get('historical_cagr', 'N/A')}
- Average Historical Margin: {forecast_config.get('historical_margin', 'N/A')}

Industry Benchmarks:
- Peer Average Growth: {forecast_config.get('peer_growth', 'N/A')}
- Industry Margin Range: {forecast_config.get('industry_margin', 'N/A')}

Generate a methodology section that:
1. Explains the basis for growth assumptions
2. Describes margin expansion/contraction drivers
3. Notes key sensitivities and uncertainties
4. Compares assumptions to historical and peer benchmarks
"""
        
        methodology = self._generate_with_llm(
            self.SYSTEM_PROMPTS['forecast_methodology'],
            user_prompt
        )
        
        logger.info("✅ Forecast methodology generated")
        return methodology

    # =========================================================================
    # 催化剂分析文本生成
    # =========================================================================
    def generate_catalyst_analysis(self, catalysts: List[Dict]) -> str:
        """
        生成催化剂分析文本
        
        Args:
            catalysts: 催化剂列表
        
        Returns:
            催化剂分析文本
        """
        logger.info("Generating catalyst analysis...")
        
        if not catalysts:
            return "No significant catalysts identified in the analysis period."
        
        # 分类催化剂
        positive = [c for c in catalysts if c.get('sentiment') == 'positive']
        negative = [c for c in catalysts if c.get('sentiment') == 'negative']
        neutral = [c for c in catalysts if c.get('sentiment') == 'neutral']
        
        catalyst_summary = []
        for cat in catalysts[:5]:
            catalyst_summary.append(
                f"- {cat.get('description', 'N/A')} "
                f"(Type: {cat.get('type', 'N/A')}, "
                f"Impact: {cat.get('impact_level', 'N/A')}, "
                f"Date: {cat.get('expected_date', 'TBD')})"
            )
        
        user_prompt = f"""
Analyze the following catalysts for this stock:

Positive Catalysts ({len(positive)}):
{chr(10).join(catalyst_summary[:3]) if positive else 'None identified'}

Risk Factors ({len(negative)}):
{chr(10).join([f"- {c.get('description', 'N/A')}" for c in negative[:3]]) if negative else 'None identified'}

Events to Monitor ({len(neutral)}):
{chr(10).join([f"- {c.get('description', 'N/A')}" for c in neutral[:3]]) if neutral else 'None identified'}

Generate a catalyst analysis that:
1. Prioritizes the most impactful catalysts
2. Assesses probability and timing
3. Quantifies potential stock price impact where possible
4. Identifies key monitoring triggers
"""
        
        analysis = self._generate_with_llm(
            self.SYSTEM_PROMPTS['catalyst_analysis'],
            user_prompt
        )
        
        logger.info("✅ Catalyst analysis generated")
        return analysis

    # =========================================================================
    # 估值分析文本生成
    # =========================================================================
    def generate_valuation_analysis(self, valuation_data: Dict) -> str:
        """
        生成估值分析文本
        
        Args:
            valuation_data: 估值数据
        
        Returns:
            估值分析文本
        """
        logger.info("Generating valuation analysis...")
        
        methods = valuation_data.get('individual_results', [])
        target_price = valuation_data.get('target_price', 0)
        current_price = valuation_data.get('current_price', 0)
        upside = valuation_data.get('upside', 0)
        
        methods_summary = []
        for m in methods:
            methods_summary.append(
                f"- {m.get('method', 'N/A')}: ${m.get('target', 0):.2f} "
                f"(Range: ${m.get('range', (0,0))[0]:.2f} - ${m.get('range', (0,0))[1]:.2f})"
            )
        
        user_prompt = f"""
Analyze the valuation for this stock:

Valuation Summary:
- Current Price: ${current_price:.2f}
- Target Price: ${target_price:.2f}
- Implied Upside/Downside: {upside:.1f}%

Valuation Methods Used:
{chr(10).join(methods_summary) if methods_summary else 'N/A'}

Peer Comparison:
- Peer Average EV/EBITDA: {valuation_data.get('peer_ev_ebitda', 'N/A')}
- Company EV/EBITDA: {valuation_data.get('company_ev_ebitda', 'N/A')}

Generate a valuation analysis that:
1. Explains each valuation methodology
2. Compares results across methods
3. Justifies the target price selection
4. Discusses valuation relative to peers and history
"""
        
        analysis = self._generate_with_llm(
            self.SYSTEM_PROMPTS['valuation_analysis'],
            user_prompt
        )
        
        logger.info("✅ Valuation analysis generated")
        return analysis

    # =========================================================================
    # 投资建议生成
    # =========================================================================
    def generate_investment_recommendation(self, analysis_data: Dict) -> str:
        """
        生成投资建议
        包含数据引用、目标价计算方法和触发条件
        
        Args:
            analysis_data: 分析数据
        
        Returns:
            投资建议文本
        """
        logger.info("Generating investment recommendation...")
        
        ticker = analysis_data.get('ticker', 'N/A')
        rating = analysis_data.get('rating', 'Hold')
        target_price = analysis_data.get('target_price', 0)
        current_price = analysis_data.get('current_price', 0)
        upside = ((target_price / current_price) - 1) * 100 if current_price > 0 else 0
        
        # 关键财务数据引用
        financial_refs = analysis_data.get('financial_references', {})
        
        user_prompt = f"""
Generate an investment recommendation for {ticker}:

Rating: {rating}
Current Price: ${current_price:.2f}
Target Price: ${target_price:.2f}
Implied Return: {upside:.1f}%

Supporting Financial Data:
- Revenue Growth (FY+1): {financial_refs.get('revenue_growth', 'N/A')}
- EBITDA Margin: {financial_refs.get('ebitda_margin', 'N/A')}
- Free Cash Flow Yield: {financial_refs.get('fcf_yield', 'N/A')}
- ROE: {financial_refs.get('roe', 'N/A')}

Valuation Basis:
- Primary Method: {analysis_data.get('primary_valuation_method', 'EV/EBITDA')}
- Target Multiple: {analysis_data.get('target_multiple', 'N/A')}

Key Risks:
{chr(10).join(['- ' + r for r in analysis_data.get('risks', ['N/A'])[:3]])}

Generate an investment recommendation that:
1. Clearly states the rating and target price
2. References specific financial data supporting the thesis
3. Explains the target price calculation methodology
4. Provides specific triggers for rating upgrades/downgrades
5. Quantifies key risks and their potential impact
"""
        
        recommendation = self._generate_with_llm(
            self.SYSTEM_PROMPTS['investment_recommendation'],
            user_prompt
        )
        
        logger.info("✅ Investment recommendation generated")
        return recommendation

    # =========================================================================
    # 章节小结生成
    # =========================================================================
    def generate_section_summary(self, section_content: str, section_title: str = "") -> str:
        """
        生成章节小结
        
        Args:
            section_content: 章节内容
            section_title: 章节标题
        
        Returns:
            小结文本
        """
        if not section_content:
            return ""
        
        # 简单的摘要生成（提取关键句子）
        sentences = section_content.replace('\n', ' ').split('.')
        key_sentences = []
        
        # 选择包含关键词的句子
        keywords = ['key', 'important', 'significant', 'main', 'primary', 
                   'growth', 'margin', 'revenue', 'target', 'risk']
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20:
                if any(kw in sentence.lower() for kw in keywords):
                    key_sentences.append(sentence)
                    if len(key_sentences) >= 3:
                        break
        
        if not key_sentences and sentences:
            key_sentences = [s.strip() for s in sentences[:2] if len(s.strip()) > 20]
        
        summary = '. '.join(key_sentences)
        if summary and not summary.endswith('.'):
            summary += '.'
        
        return summary

    # =========================================================================
    # 风险因素生成
    # =========================================================================
    def generate_risk_factors(self, risks: List[Dict]) -> str:
        """
        生成风险因素分析
        
        Args:
            risks: 风险列表
        
        Returns:
            风险分析文本
        """
        logger.info("Generating risk factors analysis...")
        
        if not risks:
            return "No significant risk factors identified."
        
        risk_categories = {
            'market': [],
            'operational': [],
            'financial': [],
            'regulatory': [],
            'other': []
        }
        
        for risk in risks:
            category = risk.get('category', 'other').lower()
            if category in risk_categories:
                risk_categories[category].append(risk)
            else:
                risk_categories['other'].append(risk)
        
        risk_text = ["## Risk Factors\n"]
        
        category_names = {
            'market': 'Market Risks',
            'operational': 'Operational Risks',
            'financial': 'Financial Risks',
            'regulatory': 'Regulatory Risks',
            'other': 'Other Risks'
        }
        
        for category, category_risks in risk_categories.items():
            if category_risks:
                risk_text.append(f"\n### {category_names[category]}")
                for risk in category_risks[:3]:
                    risk_text.append(f"- **{risk.get('title', 'Risk')}**: {risk.get('description', 'N/A')}")
                    if risk.get('impact'):
                        risk_text.append(f"  - Potential Impact: {risk.get('impact')}")
                    if risk.get('mitigation'):
                        risk_text.append(f"  - Mitigation: {risk.get('mitigation')}")
        
        return '\n'.join(risk_text)

    # =========================================================================
    # 数据引用格式化
    # =========================================================================
    def format_data_reference(self, value: Any, metric: str, source: str = "FMP", 
                             date: str = None) -> str:
        """
        格式化数据引用
        
        Args:
            value: 数据值
            metric: 指标名称
            source: 数据来源
            date: 数据日期
        
        Returns:
            格式化的数据引用
        """
        date_str = f" as of {date}" if date else ""
        
        if isinstance(value, (int, float)):
            if 'margin' in metric.lower() or 'ratio' in metric.lower() or '%' in metric.lower():
                formatted_value = f"{value:.1f}%"
            elif value >= 1e9:
                formatted_value = f"${value/1e9:.1f}B"
            elif value >= 1e6:
                formatted_value = f"${value/1e6:.1f}M"
            else:
                formatted_value = f"${value:,.0f}"
        else:
            formatted_value = str(value)
        
        return f"{formatted_value} (Source: {source}{date_str})"


def create_enhanced_text_generator(api_key: str = None, base_url: str = None) -> EnhancedTextGenerator:
    """创建增强文本生成器实例"""
    return EnhancedTextGenerator(api_key, base_url)


if __name__ == "__main__":
    print("Enhanced Text Generator Module")
    print("Features:")
    print("- Executive summary generation")
    print("- Forecast methodology explanation")
    print("- Catalyst analysis")
    print("- Valuation analysis")
    print("- Investment recommendation with data references")
    print("- Section summaries")
    print("- Risk factors analysis")
