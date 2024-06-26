from finrobot.data_source.earnings_calls_src.earningsData import get_earnings_transcript
import re
from langchain.schema import Document
from tenacity import RetryError


def clean_speakers(speaker):
    speaker = re.sub("\n", "", speaker)
    speaker = re.sub(":", "", speaker)
    return speaker


def get_earnings_all_quarters_data(quarter: str, ticker: str, year: int):
    docs = []
    resp_dict = get_earnings_transcript(quarter, ticker, year)

    content = resp_dict["content"]
    pattern = re.compile(r"\n(.*?):")
    matches = pattern.finditer(content)

    speakers_list = []
    ranges = []
    for match_ in matches:
        # print(match.span())
        span_range = match_.span()
        # first_idx = span_range[0]
        # last_idx = span_range[1]
        ranges.append(span_range)
        speakers_list.append(match_.group())
    speakers_list = [clean_speakers(sl) for sl in speakers_list]

    for idx, speaker in enumerate(speakers_list[:-1]):
        start_range = ranges[idx][1]
        end_range = ranges[idx + 1][0]
        speaker_text = content[start_range + 1 : end_range]

        docs.append(
            Document(
                page_content=speaker_text,
                metadata={"speaker": speaker, "quarter": quarter},
            )
        )

    docs.append(
        Document(
            page_content=content[ranges[-1][1] :],
            metadata={"speaker": speakers_list[-1], "quarter": quarter},
        )
    )
    return docs, speakers_list


def get_earnings_all_docs(ticker: str, year: int):
    earnings_docs = []
    earnings_call_quarter_vals = []
    print("Earnings Call Q1")
    try:
        docs, speakers_list_1 = get_earnings_all_quarters_data("Q1", ticker, year)
        earnings_call_quarter_vals.append("Q1")
        earnings_docs.extend(docs)
    except RetryError:
        print(f"Don't have the data for Q1")
        speakers_list_1 = []

    print("Earnings Call Q2")
    try:
        docs, speakers_list_2 = get_earnings_all_quarters_data("Q2", ticker, year)
        earnings_call_quarter_vals.append("Q2")
        earnings_docs.extend(docs)
    except RetryError:
        print(f"Don't have the data for Q2")
        speakers_list_2 = []
    print("Earnings Call Q3")
    try:
        docs, speakers_list_3 = get_earnings_all_quarters_data("Q3", ticker, year)
        earnings_call_quarter_vals.append("Q3")
        earnings_docs.extend(docs)
    except RetryError:
        print(f"Don't have the data for Q3")
        speakers_list_3 = []
    print("Earnings Call Q4")
    try:
        docs, speakers_list_4 = get_earnings_all_quarters_data("Q4", ticker, year)
        earnings_call_quarter_vals.append("Q4")
        earnings_docs.extend(docs)
    except RetryError:
        print(f"Don't have the data for Q4")
        speakers_list_4 = []
    return (
        earnings_docs,
        earnings_call_quarter_vals,
        speakers_list_1,
        speakers_list_2,
        speakers_list_3,
        speakers_list_4,
    )
