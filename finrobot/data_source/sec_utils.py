import os
import requests
from sec_api import ExtractorApi, QueryApi, RenderApi
from functools import wraps
from typing import Annotated
from ..utils import SavePathType, decorate_all_methods
from ..data_source import FMPUtils
from .cache_utils import hybrid_cache, is_cache_valid, get_cache_path, read_disk_cache, write_disk_cache, TTL_CONFIG


CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# In-memory cache for SEC metadata to avoid redundant API calls
_sec_metadata_cache = {}
PDF_GENERATOR_API = "https://api.sec-api.io/filing-reader"


def init_sec_api(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global extractor_api, query_api, render_api
        if os.environ.get("SEC_API_KEY") is None:
            print("Please set the environment variable SEC_API_KEY to use sec_api.")
            return None
        else:
            extractor_api = ExtractorApi(os.environ["SEC_API_KEY"])
            query_api = QueryApi(os.environ["SEC_API_KEY"])
            render_api = RenderApi(os.environ["SEC_API_KEY"])
            print("Sec Api initialized")
            return func(*args, **kwargs)

    return wrapper


@decorate_all_methods(init_sec_api)
class SECUtils:

    def get_10k_metadata(
        ticker: Annotated[str, "ticker symbol"],
        start_date: Annotated[
            str, "start date of the 10-k file search range, in yyyy-mm-dd format"
        ],
        end_date: Annotated[
            str, "end date of the 10-k file search range, in yyyy-mm-dd format"
        ],
    ):
        """
        Search for 10-k filings within a given time period, and return the meta data of the latest one
        """
        # Check in-memory cache first
        cache_key = f"10k_metadata:{ticker}:{start_date}:{end_date}"
        if cache_key in _sec_metadata_cache:
            return _sec_metadata_cache[cache_key]

        # Check disk cache with TTL
        disk_cache_path = get_cache_path("sec", cache_key)
        ttl = TTL_CONFIG.get("sec_metadata", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _sec_metadata_cache[cache_key] = cached_data
                return cached_data

        query = {
            "query": f'ticker:"{ticker}" AND formType:"10-K" AND filedAt:[{start_date} TO {end_date}]',
            "from": 0,
            "size": 10,
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        response = query_api.get_filings(query)
        result = response["filings"][0] if response["filings"] else None

        # Cache the result
        if result is not None:
            _sec_metadata_cache[cache_key] = result
            write_disk_cache(disk_cache_path, result)

        return result

    def download_10k_filing(
        ticker: Annotated[str, "ticker symbol"],
        start_date: Annotated[
            str, "start date of the 10-k file search range, in yyyy-mm-dd format"
        ],
        end_date: Annotated[
            str, "end date of the 10-k file search range, in yyyy-mm-dd format"
        ],
        save_folder: Annotated[
            str, "name of the folder to store the downloaded filing"
        ],
    ) -> str:
        """Download the latest 10-K filing as htm for a given ticker within a given time period."""
        metadata = SECUtils.get_10k_metadata(ticker, start_date, end_date)
        if metadata:
            ticker = metadata["ticker"]
            url = metadata["linkToFilingDetails"]

            try:
                date = metadata["filedAt"][:10]
                file_name = date + "_" + metadata["formType"] + "_" + url.split("/")[-1]

                if not os.path.isdir(save_folder):
                    os.makedirs(save_folder)

                file_content = render_api.get_filing(url)
                file_path = os.path.join(save_folder, file_name)
                with open(file_path, "w") as f:
                    f.write(file_content)
                return f"{ticker}: download succeeded. Saved to {file_path}"
            except:
                return f"❌ {ticker}: downloaded failed: {url}"
        else:
            return f"No 2023 10-K filing found for {ticker}"

    def download_10k_pdf(
        ticker: Annotated[str, "ticker symbol"],
        start_date: Annotated[
            str, "start date of the 10-k file search range, in yyyy-mm-dd format"
        ],
        end_date: Annotated[
            str, "end date of the 10-k file search range, in yyyy-mm-dd format"
        ],
        save_folder: Annotated[
            str, "name of the folder to store the downloaded pdf filing"
        ],
    ) -> str:
        """Download the latest 10-K filing as pdf for a given ticker within a given time period."""
        metadata = SECUtils.get_10k_metadata(ticker, start_date, end_date)
        if metadata:
            ticker = metadata["ticker"]
            filing_url = metadata["linkToFilingDetails"]

            try:
                date = metadata["filedAt"][:10]
                print(filing_url.split("/")[-1])
                file_name = (
                    date
                    + "_"
                    + metadata["formType"].replace("/A", "")
                    + "_"
                    + filing_url.split("/")[-1]
                    + ".pdf"
                )

                if not os.path.isdir(save_folder):
                    os.makedirs(save_folder)

                api_url = f"{PDF_GENERATOR_API}?token={os.environ['SEC_API_KEY']}&type=pdf&url={filing_url}"
                response = requests.get(api_url, stream=True)
                response.raise_for_status()

                file_path = os.path.join(save_folder, file_name)
                with open(file_path, "wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                return f"{ticker}: download succeeded. Saved to {file_path}"
            except Exception as e:
                return f"❌ {ticker}: downloaded failed: {filing_url}, {e}"
        else:
            return f"No 2023 10-K filing found for {ticker}"

    def get_10k_url_from_sec_api(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
    ) -> str:
        """
        Get the 10-K filing URL directly from SEC API.
        """
        # Check in-memory cache first
        cache_key = f"10k_url:{ticker_symbol}:{fyear}"
        if cache_key in _sec_metadata_cache:
            return _sec_metadata_cache[cache_key]

        # Check disk cache with TTL
        disk_cache_path = get_cache_path("sec", cache_key)
        ttl = TTL_CONFIG.get("sec_metadata", TTL_CONFIG["default"])
        if is_cache_valid(disk_cache_path, ttl):
            cached_data = read_disk_cache(disk_cache_path)
            if cached_data is not None:
                _sec_metadata_cache[cache_key] = cached_data
                return cached_data

        # Calculate date range for the fiscal year
        # Most companies file 10-K within 60-90 days after fiscal year end
        start_date = f"{fyear}-01-01"
        end_date = f"{int(fyear)+1}-12-31"

        query = {
            "query": f'ticker:"{ticker_symbol}" AND formType:"10-K" AND filedAt:[{start_date} TO {end_date}]',
            "from": 0,
            "size": 5,
            "sort": [{"filedAt": {"order": "desc"}}],
        }

        result = None
        try:
            response = query_api.get_filings(query)
            if response and response.get("filings"):
                # Get the first (most recent) 10-K filing
                filing = response["filings"][0]
                result = filing.get("linkToFilingDetails", "")
        except Exception as e:
            print(f"Error querying SEC API: {e}")

        # Cache the result
        if result:
            _sec_metadata_cache[cache_key] = result
            write_disk_cache(disk_cache_path, result)

        return result

    def get_10k_section(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        section: Annotated[
            str | int,
            "Section of the 10-K report to extract, should be in [1, 1A, 1B, 2, 3, 4, 5, 6, 7, 7A, 8, 9, 9A, 9B, 10, 11, 12, 13, 14, 15]",
        ],
        report_address: Annotated[
            str,
            "URL of the 10-K report, if not specified, will get report url from SEC API",
        ] = None,
        save_path: SavePathType = None,
    ) -> str:
        """
        Get a specific section of a 10-K report from the SEC API.
        """
        if isinstance(section, int):
            section = str(section)
        if section not in [
            "1A",
            "1B",
            "7A",
            "9A",
            "9B",
        ] + [str(i) for i in range(1, 16)]:
            raise ValueError(
                "Section must be in [1, 1A, 1B, 2, 3, 4, 5, 6, 7, 7A, 8, 9, 9A, 9B, 10, 11, 12, 13, 14, 15]"
            )

        # Get report URL if not provided
        if report_address is None:
            # First try to get URL directly from SEC API
            report_address = SECUtils.get_10k_url_from_sec_api(ticker_symbol, fyear)
            
            # Fallback to FMP if SEC API fails
            if not report_address:
                fmp_result = FMPUtils.get_sec_report(ticker_symbol, fyear)
                if fmp_result.startswith("Link: "):
                    report_address = fmp_result.lstrip("Link: ").split()[0]
                else:
                    return f"SEC filings endpoint not available. Use SEC API for 10-K filings."

        if not report_address:
            return f"Could not find 10-K filing for {ticker_symbol} in fiscal year {fyear}"

        # Use hybrid caching with TTL for 10-K sections
        cache_key = f"10k_section:{ticker_symbol}:{fyear}:{section}"

        # Check in-memory cache first
        if cache_key in _sec_metadata_cache:
            section_text = _sec_metadata_cache[cache_key]
        else:
            # Check disk cache with TTL (30 days for 10-K data)
            disk_cache_path = get_cache_path("sec", cache_key)
            ttl = TTL_CONFIG.get("sec_10k", TTL_CONFIG["default"])

            if is_cache_valid(disk_cache_path, ttl):
                section_text = read_disk_cache(disk_cache_path)
                if section_text is not None:
                    _sec_metadata_cache[cache_key] = section_text
            else:
                # Fetch from API
                try:
                    section_text = extractor_api.get_section(report_address, section, "text")
                    # Cache the result
                    if section_text:
                        _sec_metadata_cache[cache_key] = section_text
                        write_disk_cache(disk_cache_path, section_text)
                except Exception as e:
                    return f"Error extracting section {section}: {e}"

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w") as f:
                f.write(section_text)

        return section_text
