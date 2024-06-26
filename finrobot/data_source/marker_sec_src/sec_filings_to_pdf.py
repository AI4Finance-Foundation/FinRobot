from typing import List
import re
import pandas as pd
from datetime import datetime
from typing import Union, Final
import requests
import pdfkit
import os
import json

SEC_SEARCH_URL: Final[str] = "http://www.sec.gov/cgi-bin/browse-edgar"


def _search_url(cik: Union[str, int]) -> str:
    search_string = f"CIK={cik}&Find=Search&owner=exclude&action=getcompany"
    url = f"{SEC_SEARCH_URL}?{search_string}"
    return url


def get_cik_by_ticker(ticker: str) -> str:
    """Gets a CIK number from a stock ticker by running a search on the SEC website."""
    cik_re = re.compile(r".*CIK=(\d{10}).*")
    url = _search_url(ticker)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    # headers =  {
    # 'authority': 'www.google.com',
    # 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    # 'accept-language': 'en-US,en;q=0.9',
    # 'cache-control': 'max-age=0',
    # 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    # # Add more headers as needed
    # }
    company = "Indiana-University-Bloomington"
    email = "athecolab@gmail.com"
    headers = {
        "User-Agent": f"{company} {email}",
        "Content-Type": "text/html",
    }
    response = requests.get(url, stream=True, headers=headers)
    # response = requests.get(url, headers=headers)
    # response = requests.get(url)
    response.raise_for_status()
    results = cik_re.findall(response.text)
    return str(results[0])


SEC_EDGAR_URL = "https://www.sec.gov/Archives/edgar/data"

BASE_DIR = "output/SEC_EDGAR_FILINGS"
os.makedirs(BASE_DIR, exist_ok=True)


def sec_save_pdfs(
    ticker: str,
    year: str,
    filing_types: List[str] = ["10-K", "10-Q"],
    include_amends=True,
):
    cik = get_cik_by_ticker(ticker)
    rgld_cik = int(cik.lstrip("0"))
    ticker_year_path = os.path.join(BASE_DIR, f"{ticker}-{year}")
    os.makedirs(ticker_year_path, exist_ok=True)
    forms = []
    if include_amends:
        for ft in filing_types:
            forms.append(ft)
            forms.append(ft + "/A")

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    # Send a GET request to the URL with headers
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        json_data = response.json()
    else:
        print(f"Error: Unable to fetch data. Status code: {response.status_code}")

    form_lists = []
    filings = json_data["filings"]
    recent_filings = filings["recent"]
    sec_form_names = []
    for acc_num, form_name, filing_date, report_date in zip(
        recent_filings["accessionNumber"],
        recent_filings["form"],
        recent_filings["filingDate"],
        recent_filings["reportDate"],
    ):
        if form_name in forms and report_date.startswith(str(year)):
            if form_name == "10-Q":
                datetime_obj = datetime.strptime(report_date, "%Y-%m-%d")
                quarter = pd.Timestamp(datetime_obj).quarter
                form_name += str(quarter)
                if form_name in sec_form_names:
                    form_name += "-1"
            no_dashes_acc_num = re.sub("-", "", acc_num)
            form_lists.append([no_dashes_acc_num, form_name, filing_date, report_date])
            sec_form_names.append(form_name)
    process_links = lambda x: "".join(x.split("-"))

    acc_nums_list = [[fl[0], fl[1], process_links(fl[-1])] for fl in form_lists]

    html_urls = [
        [
            f"{SEC_EDGAR_URL}/{rgld_cik}/{acc}/{ticker.lower()}-{report_date}.htm",
            filing_type,
        ]
        for acc, filing_type, report_date in acc_nums_list
    ]

    metadata_json = _convert_html_to_pdfs(html_urls, ticker_year_path)
    metadata_file_path = os.path.join(ticker_year_path,'metadata.json') 
    with open(metadata_file_path, 'w') as f:
        json.dump(metadata_json, f)
    return html_urls, metadata_json, metadata_file_path,ticker_year_path


def _convert_html_to_pdfs(html_urls, base_path: str):
    metadata_json = {}
    for html_url in html_urls:
        pdf_path = html_url[0].split("/")[-1]
        # Add the filing type
        pdf_path = pdf_path.replace(".htm", f"-{html_url[1]}.pdf")
        # /A for amended is not a valid path
        pdf_path = pdf_path.replace("10-K/A", "10-KA")
        metadata_json[pdf_path] = {"languages": ["English"]}
        pdf_path = os.path.join(base_path, pdf_path)
        pdfkit.from_url(html_url[0], pdf_path)
    return metadata_json
