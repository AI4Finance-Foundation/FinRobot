from finrobot.data_source import RedditUtils, FinnHubUtils, FMPUtils, YFinanceUtils

group_config = {
    "CIO": {
        "title": "Chief Investment Officer",
        "responsibilities": [
            "Oversee the entire investment analysis process.",
            "Integrate insights from various groups.",
            "Make the final decision on portfolio composition and adjustments.",
        ],
    },
    "groups": {
        "Market Sentiment Analysts": {
            "responsibilities": [
                "Track and interpret market trends and news.",
                "Analyze social media, news articles, and market reports for market sentiment.",
                "Provide insights on market sentiment and its potential impact on investments.",
            ],
            "with_leader": {
                "leader": {
                    "title": "Senior Market Sentiment Analyst",
                    "responsibilities": [
                        "Oversee the collection and analysis of market sentiment data.",
                        "Guide and coordinate the work of the team.",
                        "Present findings to the CIO.",
                    ],
                },
                "employees": [
                    {
                        "title": "Market Sentiment Analyst",
                        "responsibilities": [
                            "Track and interpret market trends and news.",
                            "Analyze social media and news articles for market sentiment.",
                        ],
                        "toolkits": [
                            FinnHubUtils.get_company_news,
                            RedditUtils.get_reddit_posts,
                        ],
                    },
                    {
                        "title": "Junior Market Sentiment Analyst",
                        "responsibilities": [
                            "Assist in data collection and preliminary analysis.",
                            "Support the senior analyst in preparing reports.",
                        ],
                        "toolkits": [
                            FinnHubUtils.get_company_news,
                            RedditUtils.get_reddit_posts,
                        ],
                    },
                ],
            },
            "without_leader": {
                "employees": [
                    {
                        "title": "Market Sentiment Analyst",
                        "responsibilities": [
                            "Track and interpret market trends and news.",
                            "Analyze social media and news articles for market sentiment.",
                        ],
                        "toolkits": [
                            FinnHubUtils.get_company_news,
                            RedditUtils.get_reddit_posts,
                        ],
                    },
                    {
                        "title": "Market Sentiment Analyst",
                        "responsibilities": [
                            "Conduct sentiment analysis and contribute to reports.",
                            "Collaborate with peers to ensure comprehensive coverage.",
                        ],
                    },
                    {
                        "title": "Market Sentiment Analyst",
                        "responsibilities": [
                            "Gather and process data on market sentiment.",
                            "Collaborate with peers on analysis and reporting.",
                        ],
                        "toolkits": [
                            FinnHubUtils.get_company_news,
                            RedditUtils.get_reddit_posts,
                        ],
                    },
                ]
            },
        },
        "Risk Assessment Analysts": {
            "responsibilities": [
                "Identify and quantify potential risks in the portfolio.",
                "Develop risk assessment models and tools.",
                "Monitor and report on risk exposure.",
                "Propose risk mitigation strategies.",
            ],
            "with_leader": {
                "leader": {
                    "title": "Senior Risk Analyst",
                    "responsibilities": [
                        "Oversee risk assessment and management activities.",
                        "Guide and coordinate the work of the team.",
                        "Present findings to the CIO.",
                    ],
                },
                "employees": [
                    {
                        "title": "Risk Analyst",
                        "responsibilities": [
                            "Identify and quantify potential risks in the portfolio.",
                            "Develop risk assessment models.",
                        ],
                    },
                    {
                        "title": "Junior Risk Analyst",
                        "responsibilities": [
                            "Assist in data collection and preliminary risk analysis.",
                            "Support the senior analyst in preparing reports.",
                        ],
                    },
                ],
            },
            "without_leader": {
                "employees": [
                    {
                        "title": "Risk Analyst",
                        "responsibilities": [
                            "Identify and quantify potential risks in the portfolio.",
                            "Develop risk assessment models.",
                        ],
                    },
                    {
                        "title": "Risk Analyst",
                        "responsibilities": [
                            "Conduct risk analysis and contribute to risk reports.",
                            "Collaborate with peers to ensure comprehensive risk coverage.",
                        ],
                    },
                    {
                        "title": "Risk Analyst",
                        "responsibilities": [
                            "Gather and process risk-related data.",
                            "Collaborate with peers on risk assessment and mitigation strategies.",
                        ],
                    },
                ]
            },
        },
        "Fundamental Analysts": {
            "responsibilities": [
                "Review and interpret company financial statements.",
                "Summarize key financial metrics and trends.",
                "Provide forecasts and financial health assessments.",
                "Collaborate with data scientists for deeper insights.",
            ],
            "with_leader": {
                "leader": {
                    "title": "Senior Fundamental Analyst",
                    "responsibilities": [
                        "Oversee the analysis of financial statements and annual reports.",
                        "Guide and coordinate the work of the team.",
                        "Present findings to the CIO.",
                    ],
                },
                "employees": [
                    {
                        "title": "Fundamental Analyst",
                        "responsibilities": [
                            "Review and interpret company financial statements.",
                            "Summarize key financial metrics and trends.",
                        ],
                        "toolkits": [
                            YFinanceUtils.get_stock_data,
                            FMPUtils.get_financial_metrics,
                            FMPUtils.get_historical_bvps,
                            FMPUtils.get_historical_market_cap,
                        ],
                    },
                    {
                        "title": "Junior Fundamental Analyst",
                        "responsibilities": [
                            "Assist in data collection and preliminary financial analysis.",
                            "Support the senior analyst in preparing reports.",
                        ],
                        "toolkits": [
                            YFinanceUtils.get_stock_data,
                            FMPUtils.get_financial_metrics,
                            FMPUtils.get_historical_bvps,
                            FMPUtils.get_historical_market_cap,
                        ],
                    },
                ],
            },
            "without_leader": {
                "employees": [
                    {
                        "title": "Fundamental Analyst",
                        "responsibilities": [
                            "Review and interpret company financial statements.",
                            "Summarize key financial metrics and trends.",
                            "Ask for advice from Fundamental_Analyst_2 and Fundamental_Analyst_3 when you make any conclusion.",
                            "Inspect analysis delivered by Fundamental_Analyst_2 and Fundamental_Analyst_3 and give out advices.",
                            "Reach a consensus with Fundamental_Analyst_2 and Fundamental_Analyst_3 and provide the final analysis results.",
                        ],
                        "toolkits": [
                            YFinanceUtils.get_stock_data,
                            FMPUtils.get_financial_metrics,
                            FMPUtils.get_historical_bvps,
                            FMPUtils.get_historical_market_cap,
                        ],
                    },
                    {
                        "title": "Fundamental Analyst",
                        "responsibilities": [
                            "Conduct financial analysis and contribute to reports.",
                            "Collaborate with peers to ensure thorough analysis.",
                            "Ask for advice from Fundamental_Analyst_1 and Fundamental_Analyst_3  when you make any conclusion.",
                            "Inspect analysis delivered by Fundamental_Analyst_1 and Fundamental_Analyst_3 and give out advices.",
                            "Reach a consensus with Fundamental_Analyst_1 and Fundamental_Analyst_3 and provide the final analysis results.",
                        ],
                    },
                    {
                        "title": "Fundamental Analyst",
                        "responsibilities": [
                            "Gather and process financial data.",
                            "Collaborate with peers on financial analysis and reporting.",
                            "Ask for advice from Fundamental_Analyst_1 and Fundamental_Analyst_2  when you make any conclusion.",
                            "Inspect analysis delivered by Fundamental_Analyst_1 and Fundamental_Analyst_2 and give out advices.",
                            "Reach a consensus with Fundamental_Analyst_1 and Fundamental_Analyst_2 and provide the final analysis results.",
                        ],
                        "toolkits": [
                            YFinanceUtils.get_stock_data,
                            FMPUtils.get_financial_metrics,
                            FMPUtils.get_historical_bvps,
                            FMPUtils.get_historical_market_cap,
                        ],
                    },
                ]
            },
        },
    },
}
