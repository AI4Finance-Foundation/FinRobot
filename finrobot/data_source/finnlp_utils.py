from config_api_keys import FINNHUB_API_KEY
import sys
sys.path.append("FinNLP")

from typing import Annotated

# Finnhub (Yahoo Finance, Reuters, SeekingAlpha, CNBC...)
# from finnlp.data_sources.news.finnhub_date_range import Finnhub_Date_Range
from finnlp.data_sources.news.cnbc_streaming import CNBC_Streaming
from finnlp.data_sources.news.yicai_streaming import Yicai_Streaming
from finnlp.data_sources.news.investorplace_streaming import InvestorPlace_Streaming


def cnbc_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 3"] = 3,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'description', 'cn:lastPubDate', 'dateModified', 'cn:dateline', 'cn:branding', 'section', 'cn:type', 'author', 'cn:source', 'cn:subtype', 'duration', 'summary', 'expires', 'cn:sectionSubType', 'cn:contentClassification', 'pubdateunix', 'url', 'datePublished', 'cn:promoImage', 'cn:title', 'cn:keyword', 'cn:liveURL', 'brand', 'hint', 'hint_detail'. Default to ['author', 'datePublished', 'description' ,'section', 'cn:title', 'summary']"] = ["author", "datePublished", "description" ,"section", "cn:title", "summary"],
    save_path: Annotated[bool, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path, otherwise the news will be returned as a string. Default to None"] = None,
) -> str:
    """
    Download news from CNBC
    """
    news_downloader = CNBC_Streaming()
    news_downloader.download_streaming_search(keyword, rounds)
    df = news_downloader.dataframe[selected_columns]
    if save_path:
        df.to_csv(save_path, index=False)
        return f"CNBC News saved to {save_path}" 
    else:
        return df.to_csv(index=False)


def yicai_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 3"] = 3,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'author','channelid','creationDate','desc','id','previewImage','source','tags','title','topics','typeo','url','weight'. Default to ['author', 'creationDate', 'desc' ,'source', 'title']"] = ["author", "creationDate", "desc" ,"source", "title"],
    save_path: Annotated[bool, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path, otherwise the news will be returned as a string. Default to None"] = None,
) -> str:
    """
    Download news from Yicai
    """
    news_downloader = Yicai_Streaming()
    news_downloader.download_streaming_search(keyword, rounds)
    df = news_downloader.dataframe[selected_columns]
    if save_path:
        df.to_csv(save_path, index=False)
        return f"Yicai News saved to {save_path}" 
    else:
        return df.to_csv(index=False)


def yicai_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 3"] = 3,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'author','channelid','creationDate','desc','id','previewImage','source','tags','title','topics','typeo','url','weight'. Default to ['author', 'creationDate', 'desc' ,'source', 'title']"] = ["author", "creationDate", "desc" ,"source", "title"],
    save_path: Annotated[bool, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path, otherwise the news will be returned as a string. Default to None"] = None,
) -> str:
    """
    Download news from Yicai
    """
    news_downloader = Yicai_Streaming()
    news_downloader.download_streaming_search(keyword, rounds)
    df = news_downloader.dataframe[selected_columns]
    if save_path:
        df.to_csv(save_path, index=False)
        return f"Yicai News saved to {save_path}" 
    else:
        return df.to_csv(index=False)

if __name__ == "__main__":
    # print(yicai_news_download("茅台", save_path="yicai_maotai.csv"))
    print(cnbc_news_download("tesla", save_path="cnbc_tesla.csv"))
