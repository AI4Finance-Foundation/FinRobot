# from IPython import get_ipython
from typing_extensions import Annotated
from config_api_keys import *

import finnhub
import pandas as pd
import yfinance as yf
from collections import defaultdict
from datetime import datetime

import random
import json

import autogen
from autogen.cache import Cache

from utils import *

config_list = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4"],# "gpt-3.5-turbo", "gpt-3.5-turbo-16k"],
    },
)
llm_config = {
    "config_list": config_list,
    "timeout": 120,
    "temperature": 0
}
analyst = autogen.AssistantAgent(
    name="Market_Analyst",
    system_message="As a Market Analyst, one must possess strong analytical and problem-solving abilities, collect necessary financial information and aggregate them based on client's requirement."
        "For coding tasks, only use the functions you have been provided with. Reply TERMINATE when the task is done.",
    llm_config=llm_config,
)

# create a UserProxyAgent instance named "user_proxy"
user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().rstrip(".").endswith("TERMINATE"),
    human_input_mode="NEVER",
    max_consecutive_auto_reply=10,
    code_execution_config={
        "work_dir": "coding",
        "use_docker": False,
    },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)

finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)


@user_proxy.register_for_execution()
@analyst.register_for_llm(name="get_company_profile", description="get a company's profile information")
def get_company_profile(symbol: Annotated[str, "ticker symbol"]) -> str:

    profile = finnhub_client.company_profile2(symbol=symbol)
    if not profile:
        return f"Failed to find company profile for symbol {symbol} from finnhub!"
        
    company_template = "[Company Introduction]:\n\n{name} is a leading entity in the {finnhubIndustry} sector. Incorporated and publicly traded since {ipo}, the company has established its reputation as one of the key players in the market. As of today, {name} has a market capitalization of {marketCapitalization:.2f} in {currency}, with {shareOutstanding:.2f} shares outstanding." \
        "\n\n{name} operates primarily in the {country}, trading under the ticker {ticker} on the {exchange}. As a dominant force in the {finnhubIndustry} space, the company continues to innovate and drive progress within the industry."

    formatted_str = company_template.format(**profile)
    
    return formatted_str


@user_proxy.register_for_execution()
@analyst.register_for_llm(name="get_stock_data", description="retrieve stock price data for designated ticker symbol")
def get_stock_data(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date for retrieving stock price data, YYYY-mm-dd"],
    end_date: Annotated[str, "end date for retrieving stock price data, YYYY-mm-dd"],
    ) -> str:

    end_date = min(end_date, get_curday())
    stock_data = yf.download(symbol, start_date)
    if len(stock_data) == 0:
        return "Failed to download stock price data for symbol {symbol} from yfinance!"
    
    dates, prices = [], []
    available_dates = stock_data.index.astype(str)
    
    for i in range(len(stock_data)):
        if available_dates[i] <= end_date:
            prices.append(round(stock_data.loc[available_dates[i], 'Close'], 2))
            dates.append(datetime.strptime(available_dates[i], "%Y-%m-%d"))

    return pd.DataFrame({"Date": dates, "Price": prices}).to_csv(index=False)


@user_proxy.register_for_execution()
@analyst.register_for_llm(name="get_company_news", description="retrieve market news related to designated company")
def get_company_news(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date for retrieving market news, YYYY-mm-dd"],
    end_date: Annotated[str, "end date for retrieving market news, YYYY-mm-dd"],
    max_news_num: Annotated[int, "max number of news fetched, default to 10"] = 10,
    ) -> str:

    news = finnhub_client.company_news(symbol, _from=start_date, to=end_date)
    if len(news) == 0:
        return f"No company news found for symbol {symbol} from finnhub!"
    news = [{
        "date": datetime.fromtimestamp(n['datetime']).strftime('%Y%m%d%H%M%S'),
        "headline": n['headline'],
        "summary": n['summary']
    } for n in news]
    
    if len(news) > max_news_num:
        news = random.choices(news, k=max_news_num)
    
    return json.dumps(sorted(news, key=lambda x: x['date']), indent=2)


@user_proxy.register_for_execution()
@analyst.register_for_llm(name="get_financial_basics", description="get latest financial basics for a designated company")
def get_financial_basics(symbol: Annotated[str, "ticker symbol"]) -> str:

    basic_financials = finnhub_client.company_basic_financials(symbol, 'all')
    if not basic_financials['series']:
        return f"Failed to find basic financials for symbol {symbol} from finnhub! Try a different symbol."
        
    basic_list, basic_dict = [], defaultdict(dict)
    for metric, value_list in basic_financials['series']['quarterly'].items():
        for value in value_list:
            basic_dict[value['period']].update({metric: value['v']})

    for k, v in basic_dict.items():
        v.update({'period': k})
        basic_list.append(v)
        
    basic_list.sort(key=lambda x: x['period'])
    for basics in basic_list[::-1]:
        if basics['period'] <= get_curday():
            break

    basics_output = "Some recent basic financials of {}, reported at {}, are presented below:\n\n[Basic Financials]:\n\n".format(
        symbol, basics['period']) + "\n".join(f"{k}: {v}" for k, v in basics.items() if k != 'period')
    
    return basics_output



# company = "Tesla"
company = "APPLE"

with Cache.disk() as cache:
    # start the conversation
    user_proxy.initiate_chat(
        analyst,
        message=f"Based on all the information available upon {get_curday()}, let's first analyze the positive developments and potential concerns for {company}. "
            "Come up with 2-4 most important factors respectively and keep them concise. Most factors should be inferred from company related news. "
            f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. Provide a summary analysis to support your prediction.",
        cache=cache,
    )