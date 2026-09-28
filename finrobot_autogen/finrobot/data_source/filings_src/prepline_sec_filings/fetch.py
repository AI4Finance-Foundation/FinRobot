"""Module for fetching data from the SEC EDGAR Archives"""

import json
import os
import re
import requests
from typing import List, Optional, Tuple, Union
import sys

if sys.version_info < (3, 8):
    from typing_extensions import Final
else:
    from typing import Final

import webbrowser

from ratelimit import limits, sleep_and_retry

from finrobot.data_source.filings_src.prepline_sec_filings.sec_document import VALID_FILING_TYPES

SEC_ARCHIVE_URL: Final[str] = "https://www.sec.gov/Archives/edgar/data"
SEC_SEARCH_URL: Final[str] = "http://www.sec.gov/cgi-bin/browse-edgar"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"


def get_filing(
    accession_number: Union[str, int], cik: Union[str, int], company: str, email: str
) -> str:
    """Fetches the specified filing from the SEC EDGAR Archives. Conforms to the rate
    limits specified on the SEC website.
    ref: https://www.sec.gov/os/accessing-edgar-data"""

    session = _get_session(company, email)
    return _get_filing(session, cik, accession_number)


@sleep_and_retry
@limits(calls=10, period=1)
def _get_filing(
    session: requests.Session, cik: Union[str, int], accession_number: Union[str, int]
) -> str:
    """Wrapped so filings can be retrieved with an existing session."""
    url = archive_url(cik, accession_number)
    # headers = {
    # 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    # }
    company = "Indiana-University-Bloomington"
    email = "athecolab@gmail.com"
    headers = {
        "User-Agent": f"{company} {email}",
        "Content-Type": "text/html",
    }
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.text


@sleep_and_retry
@limits(calls=2, period=1)
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


@sleep_and_retry
@limits(calls=10, period=1)
def get_forms_by_cik(session: requests.Session, cik: Union[str, int]) -> dict:
    """Gets retrieves dict of recent SEC form filings for a given cik number."""
    json_name = f"CIK{cik}.json"
    response = session.get(f"{SEC_SUBMISSIONS_URL}/{json_name}")
    response.raise_for_status()
    content = json.loads(response.content)
    recent_forms = content["filings"]["recent"]
    form_types = {
        k: v for k, v in zip(recent_forms["accessionNumber"], recent_forms["form"])
    }
    return form_types


def _get_recent_acc_num_by_cik(
    session: requests.Session, cik: Union[str, int], form_types: List[str]
) -> Tuple[str, str]:
    """Returns accession number and form type for the most recent filing for one of the
    given form_types (AKA filing types) for a given cik."""
    retrieved_form_types = get_forms_by_cik(session, cik)
    for acc_num, form_type_ in retrieved_form_types.items():
        if form_type_ in form_types:
            return _drop_dashes(acc_num), form_type_
    raise ValueError(f"No filings found for {cik}, looking for any of: {form_types}")


def get_recent_acc_by_cik(
    cik: str,
    form_type: str,
    company: Optional[str] = None,
    email: Optional[str] = None,
) -> Tuple[str, str]:
    """Returns (accession_number, retrieved_form_type) for the given cik and form_type.
    The retrieved_form_type may be an amended version of requested form_type, e.g. 10-Q/A for 10-Q.
    """
    session = _get_session(company, email)
    return _get_recent_acc_num_by_cik(session, cik, _form_types(form_type))


def get_recent_cik_and_acc_by_ticker(
    ticker: str,
    form_type: str,
    company: Optional[str] = None,
    email: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Returns (cik, accession_number, retrieved_form_type) for the given ticker and form_type.
    The retrieved_form_type may be an amended version of requested form_type, e.g. 10-Q/A for 10-Q.
    """
    session = _get_session(company, email)
    cik = get_cik_by_ticker(session, ticker)
    acc_num, retrieved_form_type = _get_recent_acc_num_by_cik(
        session, cik, _form_types(form_type)
    )
    return cik, acc_num, retrieved_form_type


def get_form_by_ticker(
    ticker: str,
    form_type: str,
    allow_amended_filing: Optional[bool] = True,
    company: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """For a given ticker, gets the most recent form of a given form_type."""
    session = _get_session(company, email)
    cik = get_cik_by_ticker(session, ticker)
    return get_form_by_cik(
        cik,
        form_type,
        allow_amended_filing=allow_amended_filing,
        company=company,
        email=email,
    )


def _form_types(form_type: str, allow_amended_filing: Optional[bool] = True):
    """Potentialy expand to include amended filing, e.g.:
    "10-Q" -> "10-Q/A"
    """
    assert form_type in VALID_FILING_TYPES
    if allow_amended_filing and not form_type.endswith("/A"):
        return [form_type, f"{form_type}/A"]
    else:
        return [form_type]


def get_form_by_cik(
    cik: str,
    form_type: str,
    allow_amended_filing: Optional[bool] = True,
    company: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """For a given CIK, returns the most recent form of a given form_type. By default
    an amended version of the form_type may be retrieved (allow_amended_filing=True).
    E.g., if form_type is "10-Q", the retrived form could be a 10-Q or 10-Q/A.
    """
    session = _get_session(company, email)
    acc_num, _ = _get_recent_acc_num_by_cik(
        session, cik, _form_types(form_type, allow_amended_filing)
    )
    text = _get_filing(session, cik, acc_num)
    return text


def open_form(cik, acc_num):
    """For a given cik and accession number, opens the index page in default browser for the
    associated SEC form"""
    acc_num = _drop_dashes(acc_num)
    webbrowser.open_new_tab(
        f"{SEC_ARCHIVE_URL}/{cik}/{acc_num}/{_add_dashes(acc_num)}-index.html"
    )


def open_form_by_ticker(
    ticker: str,
    form_type: str,
    allow_amended_filing: Optional[bool] = True,
    company: Optional[str] = None,
    email: Optional[str] = None,
):
    """For a given ticker, opens the index page in default browser for the most recent form of a
    given form_type."""
    session = _get_session(company, email)
    cik = get_cik_by_ticker(session, ticker)
    acc_num, _ = _get_recent_acc_num_by_cik(
        session, cik, _form_types(form_type, allow_amended_filing)
    )
    open_form(cik, acc_num)


def archive_url(cik: Union[str, int], accession_number: Union[str, int]) -> str:
    """Builds the archive URL for the SEC accession number. Looks for the .txt file for the
    filing, while follows a {accession_number}.txt format."""
    filename = f"{_add_dashes(accession_number)}.txt"
    accession_number = _drop_dashes(accession_number)
    return f"{SEC_ARCHIVE_URL}/{cik}/{accession_number}/{filename}"


def _search_url(cik: Union[str, int]) -> str:
    search_string = f"CIK={cik}&Find=Search&owner=exclude&action=getcompany"
    url = f"{SEC_SEARCH_URL}?{search_string}"
    return url


def _add_dashes(accession_number: Union[str, int]) -> str:
    """Adds the dashes back into the accession number"""
    accession_number = str(accession_number)
    return f"{accession_number[:10]}-{accession_number[10:12]}-{accession_number[12:]}"


def _drop_dashes(accession_number: Union[str, int]) -> str:
    """Converts the accession number to the no dash representation."""
    accession_number = str(accession_number).replace("-", "")
    return accession_number.zfill(18)


def _get_session(
    company: Optional[str] = "Indiana-University-Bloomington",
    email: Optional[str] = "athecolab@gmail.com",
) -> requests.Session:
    """Creates a requests sessions with the appropriate headers set. If these headers are not
    set, SEC will reject your request.
    ref: https://www.sec.gov/os/accessing-edgar-data"""
    if company is None:
        company = os.environ.get("SEC_API_ORGANIZATION")
    if email is None:
        email = os.environ.get("SEC_API_EMAIL")
    assert company
    assert email
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"{company} {email}",
            "Content-Type": "text/html",
        }
    )
    return session
