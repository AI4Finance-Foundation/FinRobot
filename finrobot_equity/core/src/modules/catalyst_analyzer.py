#!/usr/bin/env python
# coding: utf-8
"""
催化剂分析器模块
识别和评估可能影响股价的催化事件
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CatalystData:
    """催化剂数据类"""
    event_type: str  # 'product_launch', 'earnings', 'regulatory', 'acquisition', 'other'
    description: str
    expected_date: str
    impact_level: str  # 'high', 'medium', 'low'
    probability: float  # 0.0 - 1.0
    sentiment: str  # 'positive', 'negative', 'neutral'
    source: str = ""
    details: str = ""


class CatalystAnalyzer:
    """催化剂分析器 - 识别和评估潜在催化事件"""
    
    # 催化剂类型关键词
    CATALYST_KEYWORDS = {
        'product_launch': ['launch', 'release', 'unveil', 'introduce', 'new product', 
                          'announcement', 'debut', 'rollout'],
        'earnings': ['earnings', 'quarterly results', 'financial results', 'revenue', 
                    'profit', 'guidance', 'forecast', 'outlook'],
        'regulatory': ['fda', 'approval', 'regulation', 'compliance', 'lawsuit', 
                      'investigation', 'antitrust', 'settlement'],
        'acquisition': ['acquire', 'merger', 'acquisition', 'buyout', 'deal', 
                       'partnership', 'joint venture', 'stake'],
        'management': ['ceo', 'cfo', 'executive', 'leadership', 'board', 
                      'appointment', 'resignation', 'restructuring'],
        'market': ['market share', 'expansion', 'growth', 'competition', 
                  'pricing', 'demand', 'supply']
    }
    
    # 情感关键词
    SENTIMENT_KEYWORDS = {
        'positive': ['growth', 'increase', 'beat', 'exceed', 'strong', 'positive', 
                    'upgrade', 'success', 'win', 'gain', 'improve', 'record'],
        'negative': ['decline', 'decrease', 'miss', 'weak', 'negative', 'downgrade', 
                    'loss', 'fail', 'drop', 'concern', 'risk', 'challenge']
    }
    
    def __init__(self, ticker: str, api_key: str = None):
        """
        初始化催化剂分析器
        
        Args:
            ticker: 股票代码
            api_key: API密钥（用于获取新闻和日历数据）
        """
        self.ticker = ticker
        self.api_key = api_key
        self.catalysts: List[CatalystData] = []
        self.news_data: List[Dict] = []
    
    def set_news_data(self, news_data: List[Dict]):
        """设置新闻数据"""
        self.news_data = news_data or []
        logger.info(f"Loaded {len(self.news_data)} news articles for analysis")
    
    def _classify_event_type(self, text: str) -> str:
        """根据文本内容分类事件类型"""
        text_lower = text.lower()
        
        for event_type, keywords in self.CATALYST_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return event_type
        
        return 'other'
    
    def _analyze_sentiment(self, text: str) -> str:
        """分析文本情感"""
        text_lower = text.lower()
        
        positive_count = sum(1 for kw in self.SENTIMENT_KEYWORDS['positive'] 
                            if kw in text_lower)
        negative_count = sum(1 for kw in self.SENTIMENT_KEYWORDS['negative'] 
                            if kw in text_lower)
        
        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        return 'neutral'
    
    def _assess_impact_level(self, event_type: str, sentiment: str) -> str:
        """评估影响程度"""
        high_impact_types = ['earnings', 'acquisition', 'regulatory']
        medium_impact_types = ['product_launch', 'management']
        
        if event_type in high_impact_types:
            return 'high'
        elif event_type in medium_impact_types:
            return 'medium'
        return 'low'
    
    def _estimate_probability(self, event_type: str, source: str) -> float:
        """估算事件发生概率"""
        # 基于事件类型和来源估算概率
        base_probability = {
            'earnings': 0.95,  # 财报几乎确定会发布
            'product_launch': 0.70,
            'regulatory': 0.50,
            'acquisition': 0.40,
            'management': 0.60,
            'market': 0.50,
            'other': 0.50
        }
        
        prob = base_probability.get(event_type, 0.50)
        
        # 根据来源调整
        if 'official' in source.lower() or 'company' in source.lower():
            prob = min(prob + 0.2, 1.0)
        
        return prob
    
    def identify_catalysts(self, news_data: List[Dict] = None, 
                          financial_calendar: Dict = None) -> List[CatalystData]:
        """
        识别潜在催化剂
        
        Args:
            news_data: 新闻数据列表
            financial_calendar: 财务日历数据
        
        Returns:
            催化剂列表
        """
        logger.info(f"Identifying catalysts for {self.ticker}...")
        
        if news_data:
            self.news_data = news_data
        
        self.catalysts = []
        
        # 从新闻中识别催化剂
        for article in self.news_data:
            title = article.get('title', '')
            text = article.get('text', '')
            date = article.get('publishedDate', '')
            source = article.get('site', '')
            
            combined_text = f"{title} {text}"
            
            event_type = self._classify_event_type(combined_text)
            sentiment = self._analyze_sentiment(combined_text)
            impact = self._assess_impact_level(event_type, sentiment)
            probability = self._estimate_probability(event_type, source)
            
            # 只保留有意义的催化剂
            if event_type != 'other' or impact == 'high':
                catalyst = CatalystData(
                    event_type=event_type,
                    description=title[:200] if title else text[:200],
                    expected_date=date[:10] if date else 'TBD',
                    impact_level=impact,
                    probability=probability,
                    sentiment=sentiment,
                    source=source,
                    details=text[:500] if text else ''
                )
                self.catalysts.append(catalyst)
        
        # 添加标准财务日历事件
        if financial_calendar:
            self._add_calendar_events(financial_calendar)
        else:
            self._add_default_calendar_events()
        
        logger.info(f"✅ Identified {len(self.catalysts)} potential catalysts")
        return self.catalysts
    
    def _add_calendar_events(self, calendar: Dict):
        """添加财务日历事件"""
        if 'earnings_date' in calendar:
            self.catalysts.append(CatalystData(
                event_type='earnings',
                description=f'{self.ticker} Quarterly Earnings Release',
                expected_date=calendar['earnings_date'],
                impact_level='high',
                probability=0.95,
                sentiment='neutral',
                source='Financial Calendar'
            ))
    
    def _add_default_calendar_events(self):
        """添加默认的财务日历事件"""
        # 估算下一个财报日期（假设每季度）
        today = datetime.now()
        next_quarter_end = today + timedelta(days=90)
        
        self.catalysts.append(CatalystData(
            event_type='earnings',
            description=f'{self.ticker} Expected Quarterly Earnings',
            expected_date=next_quarter_end.strftime('%Y-%m-%d'),
            impact_level='high',
            probability=0.95,
            sentiment='neutral',
            source='Estimated Calendar'
        ))
    
    def assess_catalyst_impact(self, catalyst: CatalystData) -> Dict:
        """
        评估单个催化剂的影响
        
        Args:
            catalyst: 催化剂数据
        
        Returns:
            影响评估字典
        """
        impact_scores = {
            'high': 3,
            'medium': 2,
            'low': 1
        }
        
        sentiment_multiplier = {
            'positive': 1.0,
            'negative': -1.0,
            'neutral': 0.0
        }
        
        base_score = impact_scores.get(catalyst.impact_level, 1)
        multiplier = sentiment_multiplier.get(catalyst.sentiment, 0)
        
        weighted_impact = base_score * catalyst.probability * multiplier
        
        return {
            'catalyst': catalyst.description,
            'type': catalyst.event_type,
            'impact_score': base_score,
            'probability': catalyst.probability,
            'sentiment': catalyst.sentiment,
            'weighted_impact': weighted_impact,
            'expected_date': catalyst.expected_date
        }
    
    def categorize_catalysts(self, catalysts: List[CatalystData] = None) -> Dict[str, List[CatalystData]]:
        """
        将催化剂分类为正面/负面/中性
        
        Args:
            catalysts: 催化剂列表（默认使用已识别的）
        
        Returns:
            分类后的催化剂字典
        """
        if catalysts is None:
            catalysts = self.catalysts
        
        categorized = {
            'positive': [],
            'negative': [],
            'neutral': []
        }
        
        for catalyst in catalysts:
            categorized[catalyst.sentiment].append(catalyst)
        
        logger.info(f"Categorized catalysts: {len(categorized['positive'])} positive, "
                   f"{len(categorized['negative'])} negative, {len(categorized['neutral'])} neutral")
        
        return categorized
    
    def generate_catalyst_summary(self) -> str:
        """
        生成催化剂分析摘要
        
        Returns:
            摘要文本
        """
        if not self.catalysts:
            return f"No significant catalysts identified for {self.ticker} in the analysis period."
        
        categorized = self.categorize_catalysts()
        
        summary_parts = [f"## Catalyst Analysis for {self.ticker}\n"]
        
        # 正面催化剂
        if categorized['positive']:
            summary_parts.append("### Positive Catalysts (Upside Potential)")
            for cat in categorized['positive'][:5]:  # 最多5个
                summary_parts.append(f"- **{cat.event_type.replace('_', ' ').title()}** "
                                   f"({cat.expected_date}): {cat.description}")
                summary_parts.append(f"  - Impact: {cat.impact_level.upper()}, "
                                   f"Probability: {cat.probability*100:.0f}%")
            summary_parts.append("")
        
        # 负面催化剂/风险
        if categorized['negative']:
            summary_parts.append("### Risk Factors (Downside Risks)")
            for cat in categorized['negative'][:5]:
                summary_parts.append(f"- **{cat.event_type.replace('_', ' ').title()}** "
                                   f"({cat.expected_date}): {cat.description}")
                summary_parts.append(f"  - Impact: {cat.impact_level.upper()}, "
                                   f"Probability: {cat.probability*100:.0f}%")
            summary_parts.append("")
        
        # 中性/待观察
        if categorized['neutral']:
            summary_parts.append("### Events to Monitor")
            for cat in categorized['neutral'][:3]:
                summary_parts.append(f"- {cat.description} ({cat.expected_date})")
        
        return "\n".join(summary_parts)
    
    def get_top_catalysts(self, n: int = 5) -> List[Dict]:
        """
        获取最重要的N个催化剂
        
        Args:
            n: 返回数量
        
        Returns:
            催化剂列表（按影响排序）
        """
        if not self.catalysts:
            return []
        
        # 计算综合得分
        scored_catalysts = []
        for cat in self.catalysts:
            impact = self.assess_catalyst_impact(cat)
            score = abs(impact['weighted_impact'])
            scored_catalysts.append((score, cat, impact))
        
        # 按得分排序
        scored_catalysts.sort(key=lambda x: x[0], reverse=True)
        
        return [item[2] for item in scored_catalysts[:n]]


def create_catalyst_analyzer(ticker: str, api_key: str = None) -> CatalystAnalyzer:
    """创建催化剂分析器实例"""
    return CatalystAnalyzer(ticker, api_key)


if __name__ == "__main__":
    print("Catalyst Analyzer Module")
    print("Features:")
    print("- News-based catalyst identification")
    print("- Event type classification")
    print("- Sentiment analysis")
    print("- Impact assessment")
    print("- Probability estimation")
    print("- Catalyst categorization (positive/negative/neutral)")
