#!/usr/bin/env python
# coding: utf-8
"""
新闻整合器模块
增强新闻获取、分类、排序和影响分析功能
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """新闻文章数据类"""
    symbol: str
    title: str
    published_date: str
    text: str
    site: str
    url: str
    category: str = "general"
    importance: int = 3  # 1-5, 5最重要
    sentiment: str = "neutral"
    impact_analysis: str = ""


class NewsIntegrator:
    """新闻整合器 - 增强新闻获取、分类和分析"""
    
    # 新闻分类关键词
    CATEGORY_KEYWORDS = {
        'earnings': ['earnings', 'revenue', 'profit', 'quarterly', 'annual report', 
                    'guidance', 'eps', 'beat', 'miss', 'forecast'],
        'product': ['launch', 'product', 'release', 'unveil', 'announce', 'new', 
                   'innovation', 'technology', 'service'],
        'management': ['ceo', 'cfo', 'executive', 'board', 'leadership', 'appoint', 
                      'resign', 'hire', 'management'],
        'regulatory': ['fda', 'sec', 'regulation', 'compliance', 'lawsuit', 'legal', 
                      'investigation', 'settlement', 'approval'],
        'market': ['market', 'stock', 'share', 'price', 'analyst', 'upgrade', 
                  'downgrade', 'target', 'rating'],
        'acquisition': ['acquire', 'merger', 'acquisition', 'deal', 'buyout', 
                       'partnership', 'joint venture', 'stake'],
        'financial': ['debt', 'bond', 'dividend', 'buyback', 'capital', 'financing', 
                     'credit', 'loan']
    }
    
    # 重要性关键词
    IMPORTANCE_KEYWORDS = {
        5: ['breaking', 'major', 'significant', 'record', 'historic', 'unprecedented'],
        4: ['beat', 'miss', 'exceed', 'surge', 'plunge', 'acquisition', 'merger'],
        3: ['announce', 'report', 'update', 'launch', 'expand'],
        2: ['minor', 'slight', 'modest', 'routine'],
        1: ['rumor', 'speculation', 'unconfirmed']
    }
    
    # 情感关键词
    SENTIMENT_KEYWORDS = {
        'positive': ['growth', 'increase', 'beat', 'exceed', 'strong', 'positive',
                    'upgrade', 'success', 'win', 'gain', 'improve', 'record', 'surge',
                    'outperform', 'bullish', 'optimistic',
                    'initiate', 'initiates', 'overweight', 'accumulate', 'top pick'],
        'negative': ['decline', 'decrease', 'miss', 'weak', 'negative', 'downgrade',
                    'loss', 'fail', 'drop', 'concern', 'risk', 'challenge', 'plunge',
                    'underperform', 'bearish', 'pessimistic', 'warning',
                    'underweight', 'recall', 'investigation']
    }

    # 分析师动作短语（优先级匹配）
    ANALYST_POSITIVE_PATTERNS = [
        'initiates coverage', 'initiate coverage', 'initiates with',
        'starts coverage', 'begins coverage', 'upgrades to',
        'price target raised', 'raises target', 'overweight',
        'buy rating', 'outperform rating', 'top pick', 'conviction buy',
        'adds to', 'build position', 'maintains buy', 'reiterate buy',
    ]
    ANALYST_NEGATIVE_PATTERNS = [
        'downgrades to', 'cuts to', 'lowers to', 'underweight',
        'sell rating', 'underperform rating', 'removes from',
        'drops coverage', 'cuts target', 'lowers target', 'reduces target',
    ]

    def __init__(self, ticker: str, api_key: str = None, company_name: str = None):
        """
        初始化新闻整合器
        
        Args:
            ticker: 股票代码
            api_key: API密钥
        """
        self.ticker = ticker
        self.api_key = api_key
        self.company_name = company_name
        self.articles: List[NewsArticle] = []
        self.raw_news: List[Dict] = []

    def _is_relevant_to_ticker(self, title: str, text: str) -> bool:
        """检查新闻是否与目标公司相关"""
        search_terms = [self.ticker.upper()]
        if self.company_name:
            search_terms.append(self.company_name.lower())
            skip = {'inc', 'inc.', 'corp', 'corp.', 'ltd', 'ltd.', 'co', 'co.',
                    'the', 'and', 'of', 'group', 'holdings', 'plc'}
            for w in self.company_name.split():
                if w.lower() not in skip and len(w) > 2:
                    search_terms.append(w.lower())
        title_lower = title.lower()
        text_lower = (text[:500] if text else '').lower()
        return any(t.lower() in title_lower or t.lower() in text_lower for t in search_terms)

    def set_news_data(self, news_data: List[Dict]):
        """
        设置原始新闻数据
        
        Args:
            news_data: 从API获取的新闻列表
        """
        self.raw_news = news_data or []
        logger.info(f"Loaded {len(self.raw_news)} news articles for {self.ticker}")
    
    def _classify_category(self, text: str) -> str:
        """根据文本内容分类新闻类别"""
        text_lower = text.lower()
        
        category_scores = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                category_scores[category] = score
        
        if category_scores:
            return max(category_scores, key=category_scores.get)
        return 'general'
    
    def _assess_importance(self, text: str, category: str) -> int:
        """评估新闻重要性（1-5）"""
        text_lower = text.lower()
        
        # 基于关键词评估
        for importance, keywords in self.IMPORTANCE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return importance
        
        # 基于类别的默认重要性
        category_importance = {
            'earnings': 4,
            'acquisition': 4,
            'regulatory': 4,
            'management': 3,
            'product': 3,
            'market': 3,
            'financial': 3,
            'general': 2
        }
        
        return category_importance.get(category, 3)
    
    def _analyze_sentiment(self, text: str) -> str:
        """分析新闻情感，优先匹配分析师动作短语"""
        text_lower = text.lower()

        # 优先：分析师动作短语
        for p in self.ANALYST_POSITIVE_PATTERNS:
            if p in text_lower:
                return 'positive'
        for p in self.ANALYST_NEGATIVE_PATTERNS:
            if p in text_lower:
                return 'negative'

        positive_count = sum(1 for kw in self.SENTIMENT_KEYWORDS['positive']
                            if kw in text_lower)
        negative_count = sum(1 for kw in self.SENTIMENT_KEYWORDS['negative']
                            if kw in text_lower)

        if positive_count > negative_count + 1:
            return 'positive'
        elif negative_count > positive_count + 1:
            return 'negative'
        return 'neutral'
    
    def _is_within_time_window(self, published_date: str, days: int = 5) -> bool:
        """检查新闻是否在时间窗口内"""
        try:
            # 解析日期（支持多种格式）
            date_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']
            pub_date = None
            
            for fmt in date_formats:
                try:
                    pub_date = datetime.strptime(published_date[:19], fmt)
                    break
                except:
                    continue
            
            if not pub_date:
                return True  # 无法解析时默认包含
            
            cutoff_date = datetime.now() - timedelta(days=days)
            return pub_date >= cutoff_date
            
        except Exception:
            return True
    
    def process_news(self, days_window: int = 5) -> List[NewsArticle]:
        """
        处理和分类新闻
        
        Args:
            days_window: 时间窗口（天）
        
        Returns:
            处理后的新闻文章列表
        """
        logger.info(f"Processing {len(self.raw_news)} news articles...")
        
        self.articles = []
        
        for article in self.raw_news:
            title = article.get('title', '')
            text = article.get('text', '')
            published_date = article.get('publishedDate', '')
            
            # 检查时间窗口
            if not self._is_within_time_window(published_date, days_window):
                continue

            # 过滤无关公司新闻
            if not self._is_relevant_to_ticker(title, text):
                continue

            combined_text = f"{title} {text}"
            
            # 分类和评估
            category = self._classify_category(combined_text)
            importance = self._assess_importance(combined_text, category)
            sentiment = self._analyze_sentiment(combined_text)
            
            news_article = NewsArticle(
                symbol=article.get('symbol', self.ticker),
                title=title,
                published_date=published_date,
                text=text[:500] if text else '',  # 截断长文本
                site=article.get('site', ''),
                url=article.get('url', ''),
                category=category,
                importance=importance,
                sentiment=sentiment
            )
            
            self.articles.append(news_article)
        
        logger.info(f"✅ Processed {len(self.articles)} articles within {days_window}-day window")
        return self.articles
    
    def get_sorted_news(self, sort_by: str = 'importance') -> List[NewsArticle]:
        """
        获取排序后的新闻
        
        Args:
            sort_by: 排序方式 ('importance', 'date', 'category')
        
        Returns:
            排序后的新闻列表
        """
        if not self.articles:
            self.process_news()
        
        if sort_by == 'importance':
            return sorted(self.articles, key=lambda x: x.importance, reverse=True)
        elif sort_by == 'date':
            return sorted(self.articles, key=lambda x: x.published_date, reverse=True)
        elif sort_by == 'category':
            return sorted(self.articles, key=lambda x: (x.category, -x.importance))
        
        return self.articles
    
    def get_news_by_category(self) -> Dict[str, List[NewsArticle]]:
        """
        按类别获取新闻
        
        Returns:
            按类别分组的新闻字典
        """
        if not self.articles:
            self.process_news()
        
        categorized = {}
        for article in self.articles:
            if article.category not in categorized:
                categorized[article.category] = []
            categorized[article.category].append(article)
        
        # 每个类别内按重要性排序
        for category in categorized:
            categorized[category].sort(key=lambda x: x.importance, reverse=True)
        
        return categorized

    def analyze_news_impact(self, article: NewsArticle) -> str:
        """
        分析单条新闻对投资观点的影响
        
        Args:
            article: 新闻文章
        
        Returns:
            影响分析文本
        """
        impact_templates = {
            ('earnings', 'positive'): "Positive earnings news may support near-term stock performance and validate growth thesis.",
            ('earnings', 'negative'): "Negative earnings news could pressure stock price and may require thesis reassessment.",
            ('earnings', 'neutral'): "Earnings-related news warrants monitoring for potential impact on estimates.",
            ('product', 'positive'): "Product news suggests potential revenue growth opportunities.",
            ('product', 'negative'): "Product challenges may impact future revenue expectations.",
            ('regulatory', 'positive'): "Favorable regulatory development reduces risk profile.",
            ('regulatory', 'negative'): "Regulatory concerns increase risk and may impact valuation.",
            ('acquisition', 'positive'): "M&A activity could drive strategic value creation.",
            ('acquisition', 'negative'): "Deal-related concerns may create near-term uncertainty.",
            ('management', 'positive'): "Leadership changes may bring fresh strategic direction.",
            ('management', 'negative'): "Management transition creates execution uncertainty.",
            ('market', 'positive'): "Positive market sentiment supports current valuation.",
            ('market', 'negative'): "Negative market sentiment may create buying opportunity if fundamentals intact."
        }
        
        key = (article.category, article.sentiment)
        impact = impact_templates.get(key, "News warrants monitoring for potential investment impact.")
        
        article.impact_analysis = impact
        return impact
    
    def generate_news_summary(self) -> str:
        """
        生成新闻摘要
        
        Returns:
            新闻摘要文本
        """
        if not self.articles:
            return f"No recent news found for {self.ticker} in the analysis period."
        
        categorized = self.get_news_by_category()
        
        summary_parts = [f"## Recent News Summary for {self.ticker}\n"]
        summary_parts.append(f"*{len(self.articles)} articles analyzed*\n")
        
        # 按类别生成摘要
        category_names = {
            'earnings': '📊 Earnings & Financial Results',
            'product': '🚀 Product & Innovation',
            'management': '👔 Management & Leadership',
            'regulatory': '⚖️ Regulatory & Legal',
            'market': '📈 Market & Analyst Coverage',
            'acquisition': '🤝 M&A & Partnerships',
            'financial': '💰 Financial & Capital',
            'general': '📰 General News'
        }
        
        for category, articles in categorized.items():
            if articles:
                category_name = category_names.get(category, category.title())
                summary_parts.append(f"\n### {category_name}")
                
                for article in articles[:3]:  # 每类最多3条
                    sentiment_icon = {'positive': '🟢', 'negative': '🔴', 'neutral': '⚪'}.get(article.sentiment, '⚪')
                    importance_stars = '⭐' * min(article.importance, 5)
                    
                    summary_parts.append(f"\n**{article.title}**")
                    summary_parts.append(f"- Source: {article.site} | Date: {article.published_date[:10]}")
                    summary_parts.append(f"- Sentiment: {sentiment_icon} {article.sentiment.title()} | Importance: {importance_stars}")
                    
                    # 添加影响分析
                    impact = self.analyze_news_impact(article)
                    summary_parts.append(f"- Impact: {impact}")
        
        # 整体情感分析
        sentiments = [a.sentiment for a in self.articles]
        positive_count = sentiments.count('positive')
        negative_count = sentiments.count('negative')
        
        summary_parts.append(f"\n### Overall News Sentiment")
        summary_parts.append(f"- Positive: {positive_count} ({positive_count/len(self.articles)*100:.0f}%)")
        summary_parts.append(f"- Negative: {negative_count} ({negative_count/len(self.articles)*100:.0f}%)")
        summary_parts.append(f"- Neutral: {len(self.articles) - positive_count - negative_count}")
        
        return '\n'.join(summary_parts)
    
    def get_high_impact_news(self, min_importance: int = 4) -> List[NewsArticle]:
        """
        获取高影响力新闻
        
        Args:
            min_importance: 最低重要性阈值
        
        Returns:
            高影响力新闻列表
        """
        if not self.articles:
            self.process_news()
        
        return [a for a in self.articles if a.importance >= min_importance]
    
    def get_news_for_catalyst_analysis(self) -> List[Dict]:
        """
        获取用于催化剂分析的新闻数据
        
        Returns:
            格式化的新闻数据列表
        """
        if not self.articles:
            self.process_news()
        
        return [
            {
                'title': a.title,
                'text': a.text,
                'publishedDate': a.published_date,
                'site': a.site,
                'category': a.category,
                'sentiment': a.sentiment,
                'importance': a.importance
            }
            for a in self.articles
        ]


# 增强版新闻获取函数
def get_enhanced_company_news(ticker: str, api_key: str, days_back: int = 5, 
                              limit: int = 50) -> Dict[str, Any]:
    """
    增强版公司新闻获取函数
    
    Args:
        ticker: 股票代码
        api_key: FMP API密钥
        days_back: 回溯天数
        limit: 最大文章数
    
    Returns:
        包含分类和分析的新闻数据字典
    """
    import requests
    from datetime import datetime, timedelta
    
    try:
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        from_date = start_date.strftime('%Y-%m-%d')
        to_date = end_date.strftime('%Y-%m-%d')
        
        # 获取新闻
        url = "https://financialmodelingprep.com/api/v3/stock_news"
        params = {
            'tickers': ticker,
            'from': from_date,
            'to': to_date,
            'limit': limit,
            'apikey': api_key
        }
        
        logger.info(f"Fetching enhanced news for {ticker}...")
        response = requests.get(url, params=params)
        response.raise_for_status()
        raw_news = response.json()
        
        if not raw_news:
            logger.warning(f"No news found for {ticker}")
            return {
                'ticker': ticker,
                'articles': [],
                'summary': f"No recent news found for {ticker}.",
                'categorized': {},
                'sentiment_overview': {'positive': 0, 'negative': 0, 'neutral': 0}
            }
        
        # 使用NewsIntegrator处理
        integrator = NewsIntegrator(ticker, api_key)
        integrator.set_news_data(raw_news)
        integrator.process_news(days_back)
        
        # 生成结果
        categorized = integrator.get_news_by_category()
        summary = integrator.generate_news_summary()
        
        sentiments = [a.sentiment for a in integrator.articles]
        
        return {
            'ticker': ticker,
            'articles': integrator.get_news_for_catalyst_analysis(),
            'summary': summary,
            'categorized': {k: [{'title': a.title, 'sentiment': a.sentiment, 
                                'importance': a.importance} for a in v] 
                          for k, v in categorized.items()},
            'sentiment_overview': {
                'positive': sentiments.count('positive'),
                'negative': sentiments.count('negative'),
                'neutral': sentiments.count('neutral')
            },
            'high_impact': [{'title': a.title, 'category': a.category, 
                           'sentiment': a.sentiment} 
                          for a in integrator.get_high_impact_news()]
        }
        
    except Exception as e:
        logger.error(f"Error fetching enhanced news: {e}")
        return {
            'ticker': ticker,
            'articles': [],
            'summary': f"Error fetching news for {ticker}: {str(e)}",
            'categorized': {},
            'sentiment_overview': {'positive': 0, 'negative': 0, 'neutral': 0}
        }


def create_news_integrator(ticker: str, api_key: str = None) -> NewsIntegrator:
    """创建新闻整合器实例"""
    return NewsIntegrator(ticker, api_key)


if __name__ == "__main__":
    print("News Integrator Module")
    print("Features:")
    print("- News categorization (earnings, product, regulatory, etc.)")
    print("- Importance ranking (1-5 scale)")
    print("- Sentiment analysis (positive/negative/neutral)")
    print("- Time window filtering")
    print("- Impact analysis")
    print("- News summary generation")
