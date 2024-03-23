import os
import sys
sys.path.append("FinNLP")
from typing import Annotated
from pandas import DataFrame

from finnlp.data_sources.news.cnbc_streaming import CNBC_Streaming
from finnlp.data_sources.news.yicai_streaming import Yicai_Streaming
from finnlp.data_sources.news.investorplace_streaming import InvestorPlace_Streaming
# from finnlp.data_sources.news.eastmoney_streaming import Eastmoney_Streaming

US_Proxy = {
    "use_proxy": "us_free",
    "max_retry": 5,
    "proxy_pages": 5,
}
CN_Proxy = {
    "use_proxy": "china_free",
    "max_retry": 5,
    "proxy_pages": 5,
}


def streaming_download(streaming, config, tag, keyword, rounds, selected_columns, verbose, save_path):
    downloader = streaming(config)
    if hasattr(downloader, 'download_streaming_search'):
        downloader.download_streaming_search(keyword, rounds)
    elif hasattr(downloader, 'download_streaming_stock'):
        downloader.download_streaming_stock(keyword, rounds)
    else:
        downloader.download_streaming_all(rounds)
    print(downloader.dataframe.columns)
    selected = downloader.dataframe[selected_columns]
    if verbose:
        print(selected.to_csv(index=False))
    if save_path:
        selected.to_csv(save_path, index=False)
        print(f"{tag} saved to {save_path}")
    return selected


def date_range_download(date_range, config, tag, start_date, end_date, stock, selected_columns, verbose, save_path):
    downloader = date_range(config)
    if hasattr(downloader, 'download_date_range_all'):
        downloader.download_date_range_all(start_date, end_date)
    else:
        downloader.download_date_range_stock(start_date, end_date, stock)
    downloader.gather_content()
    print(downloader.dataframe.columns)
    selected_news = downloader.dataframe[selected_columns]
    if verbose:
        print(selected_news.to_csv(index=False))
    if save_path:
        selected_news.to_csv(save_path, index=False)
        print(f"{tag} saved to {save_path}")
    return selected_news


"""
Streaming News Download
"""

def cnbc_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 1"] = 1,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'description', 'cn:lastPubDate', 'dateModified', 'cn:dateline', 'cn:branding', 'section', 'cn:type', 'author', 'cn:source', 'cn:subtype', 'duration', 'summary', 'expires', 'cn:sectionSubType', 'cn:contentClassification', 'pubdateunix', 'url', 'datePublished', 'cn:promoImage', 'cn:title', 'cn:keyword', 'cn:liveURL', 'brand', 'hint', 'hint_detail'. Default to ['author', 'datePublished', 'description' ,'section', 'cn:title', 'summary']"] = ["author", "datePublished", "description" ,"section", "cn:title", "summary"],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return streaming_download(CNBC_Streaming, {}, "CNBC News", keyword, rounds, selected_columns, verbose, save_path)


def yicai_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 1"] = 1,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'author','channelid','creationDate','desc','id','previewImage','source','tags','title','topics','typeo','url','weight'. Default to ['author', 'creationDate', 'desc' ,'source', 'title']"] = ["author", "creationDate", "desc" ,"source", "title"],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return streaming_download(Yicai_Streaming, {}, "Yicai News", keyword, rounds, selected_columns, verbose, save_path)


def investor_place_news_download(
    keyword: Annotated[str, "Keyword to search in news stream"],
    rounds: Annotated[int, "Number of rounds to search. Default to 1"] = 1,
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'title', 'time', 'author', 'summary'. Default to ['title', 'time', 'author', 'summary']"] = ['title', 'time', 'author', 'summary'],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return streaming_download(InvestorPlace_Streaming, {}, "Investor Place News", keyword, rounds, selected_columns, verbose, save_path)


# def eastmoney_news_download(
#     stock: Annotated[str, "stock id, e.g. 600519"],
#     pages: Annotated[int, "Number of pages to retrieve. Default to 1"] = 1,
#     selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'title', 'time', 'author', 'summary'. Default to ['title', 'time', 'author', 'summary']"] = ['title', 'time', 'author', 'summary'],
#     verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
#     save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path, otherwise the news will be returned as a string. Default to None"] = None,
# ) -> str:
#     return streaming_download(Eastmoney_Streaming, "Eastmoney", stock, pages, selected_columns, verbose, save_path)


"""
Date Range News Download
"""

from finnlp.data_sources.news.sina_finance_date_range import Sina_Finance_Date_Range
from finnlp.data_sources.news.finnhub_date_range import Finnhub_Date_Range

def sina_finance_news_download(
    start_date: Annotated[str, "Start date of the news to retrieve, YYYY-mm-dd"],
    end_date: Annotated[str, "End date of the news to retrieve, YYYY-mm-dd"],
    selected_columns: Annotated[list[str], """
        List of column names of news to return, should be chosen from 
        'mediaid', 'productid', 'summary', 'ctime', 'url', 'author', 'stitle',
        'authoruid', 'wapsummary', 'images', 'level', 'keywords', 'mlids',
        'wapurl', 'columnid', 'oid', 'img', 'subjectid', 'commentid',
        'ipad_vid', 'vid', 'video_id', 'channelid', 'intime',
        'video_time_length', 'categoryid', 'hqChart', 'intro', 'is_cre_manual',
        'icons', 'mtime', 'media_name', 'title', 'docid', 'urls', 'templateid', 
        'lids', 'wapurls', 'ext', 'comment_reply', 'comment_show', 'comment_total', 'praise',
        'dispraise', 'important', 'content'. Default to ['title', 'author', 'content']
        """
    ] = ['title', 'author', 'content'],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return date_range_download(Sina_Finance_Date_Range, {}, "Sina Finance News", start_date, end_date, None, selected_columns, verbose, save_path)


def finnhub_news_download(
    start_date: Annotated[str, "Start date of the news to retrieve, YYYY-mm-dd"],
    end_date: Annotated[str, "End date of the news to retrieve, YYYY-mm-dd"],
    stock: Annotated[str, "Stock symbol, e.g. AAPL"],
    selected_columns: Annotated[list[str], "List of column names of news to return, should be chosen from 'category', 'datetime', 'headline', 'id', 'image', 'related', 'source', 'summary', 'url', 'content'. Default to ['headline', 'datetime', 'source', 'summary']"] = ['headline', 'datetime', 'source', 'summary'],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return date_range_download(Finnhub_Date_Range, {"token": os.environ['FINNHUB_API_KEY']}, "Finnhub News", start_date, end_date, stock, selected_columns, verbose, save_path)


"""
Social Media
"""
from finnlp.data_sources.social_media.xueqiu_streaming import Xueqiu_Streaming
from finnlp.data_sources.social_media.stocktwits_streaming import Stocktwits_Streaming
# from finnlp.data_sources.social_media.reddit_streaming import Reddit_Streaming


def xueqiu_social_media_download(
    stock: Annotated[str, "Stock symbol, e.g. 'AAPL'"],
    rounds: Annotated[int, "Number of rounds to search. Default to 1"] = 1,
    selected_columns: Annotated[list[str], """
        List of column names of news to return, should be chosen from blocked', 
        'blocking', 'canEdit', 'commentId', 'controversial',
        'created_at', 'description', 'donate_count', 'donate_snowcoin',
        'editable', 'expend', 'fav_count', 'favorited', 'flags', 'flagsObj',
        'hot', 'id', 'is_answer', 'is_bonus', 'is_refused', 'is_reward',
        'is_ss_multi_pic', 'legal_user_visible', 'like_count', 'liked', 'mark',
        'pic', 'promotion_id', 'reply_count', 'retweet_count',
        'retweet_status_id', 'reward_count', 'reward_user_count', 'rqid',
        'source', 'source_feed', 'source_link', 'target', 'text', 'timeBefore',
        'title', 'trackJson', 'truncated', 'truncated_by', 'type', 'user',
        'user_id', 'view_count', 'firstImg', 'pic_sizes', 'edited_at'. 
        Default to ['created_at', 'description', 'title', 'text', 'target', 'source']
    """] = ['created_at', 'description', 'title', 'text', 'target', 'source'],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return streaming_download(Xueqiu_Streaming, {}, "Xueqiu Social Media", stock, rounds, selected_columns, verbose, save_path)


def stocktwits_social_media_download(
    stock: Annotated[str, "Stock symbol, e.g. 'AAPL'"],
    rounds: Annotated[int, "Number of rounds to search. Default to 1"] = 1,
    selected_columns: Annotated[list[str], """
        List of column names of news to return, should be chosen from 'id', 
        'body', 'created_at', 'user', 'source', 'symbols', 'prices',
        'mentioned_users', 'entities', 'liked_by_self', 'reshared_by_self',
        'conversation', 'links', 'likes', 'reshare_message', 'structurable',
        'reshares'. Default to ['created_at', 'body']
    """] = ['created_at', 'body'],
    verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
    save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
) -> DataFrame:
    return streaming_download(Stocktwits_Streaming, {}, "Stocktwits Social Media", stock, rounds, selected_columns, verbose, save_path)


# def reddit_social_media_download(
#     pages: Annotated[int, "Number of pages to retrieve. Default to 1"] = 1,
#     selected_columns: Annotated[list[str], """
#         List of column names of news to return, should be chosen from 'id', 
#         'body', 'created_at', 'user', 'source', 'symbols', 'prices',
#         'mentioned_users', 'entities', 'liked_by_self', 'reshared_by_self',
#         'conversation', 'links', 'likes', 'reshare_message', 'structurable',
#         'reshares'. Default to ['created_at', 'body']
#     """] = ['created_at', 'body'],
#     verbose: Annotated[bool, "Whether to print downloaded news to console. Default to True"] = True,
#     save_path: Annotated[str, "If specified (recommended if the amount of news is large), the downloaded news will be saved to save_path. Default to None"] = None,
# ) -> DataFrame:
#     return streaming_download(Reddit_Streaming, {}, "Reddit Social Media", None, pages, selected_columns, verbose, save_path)


"""
Company Announcements
"""



if __name__ == "__main__":

    os.environ['FINNHUB_API_KEY'] = "ckrn2mpr01qiu0ijr9hgckrn2mpr01qiu0ijr9i0"

    # print(yicai_news_download("茅台", save_path="yicai_maotai.csv"))
    # print(cnbc_news_download("tesla", save_path="cnbc_tesla.csv"))
    # investor_place_news_download("tesla", save_path="invpl_tesla.csv")
    # eastmoney_news_download("600519", save_path="estmny_maotai.csv")
    # sina_finance_news_download("2024-03-02", "2024-03-02", save_path="sina_news.csv")
    # finnhub_news_download("2024-03-02", "2024-03-02", "AAPL", save_path="finnhub_aapl_news.csv")
    # stocktwits_social_media_download("AAPL", save_path="stocktwits_aapl.csv")
    # xueqiu_social_media_download("茅台", save_path="xueqiu_maotai.csv")
    # reddit_social_media_download(save_path="reddit_social_media.csv")
