import os
import requests
from sec_api import ExtractorApi, QueryApi, RenderApi
from functools import wraps
from typing import Annotated
from ..utils import SavePathType, decorate_all_methods
from ..data_source import FMPUtils


CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
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
        query = {
            "query": f'ticker:"{ticker}" AND formType:"10-K" AND filedAt:[{start_date} TO {end_date}]',
            "from": 0,
            "size": 10,
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        response = query_api.get_filings(query)
        if response["filings"]:
            return response["filings"][0]
        return None

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

    def get_10k_section(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        section: Annotated[
            str | int,
            "Section of the 10-K report to extract, should be in [1, 1A, 1B, 2, 3, 4, 5, 6, 7, 7A, 8, 9, 9A, 9B, 10, 11, 12, 13, 14, 15]",
        ],
        report_address: Annotated[
            str,
            "URL of the 10-K report, if not specified, will get report url from fmp api",
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

        # os.makedirs(f"{self.project_dir}/10k", exist_ok=True)

        # report_name = f"{self.project_dir}/10k/section_{section}.txt"

        # if USE_CACHE and os.path.exists(report_name):
        #     with open(report_name, "r") as f:
        #         section_text = f.read()
        # else:
        if report_address is None:
            report_address = FMPUtils.get_sec_report(ticker_symbol, fyear)
            if report_address.startswith("Link: "):
                report_address = report_address.lstrip("Link: ").split()[0]
            else:
                return report_address  # debug info

        cache_path = os.path.join(
            CACHE_PATH, f"sec_utils/{ticker_symbol}_{fyear}_{section}.txt"
        )
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                section_text = f.read()
        else:
            section_text = extractor_api.get_section(report_address, section, "text")
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                f.write(section_text)

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w") as f:
                f.write(section_text)

        return section_text
