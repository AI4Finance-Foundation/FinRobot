import os
from sec_api import ExtractorApi
from functools import wraps
from typing import Annotated
from ..utils import SavePathType
from ..data_source import FMPUtils


CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def init_sec_api(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global extractor
        if os.environ.get("SEC_API_KEY") is None:
            print("Please set the environment variable SEC_API_KEY to use sec_api.")
            return None
        else:
            extractor = ExtractorApi(os.environ["SEC_API_KEY"])
            print("Sec Api initialized")
            return func(*args, **kwargs)

    return wrapper


class SECUtils:

    @init_sec_api
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
        
        cache_path = os.path.join(CACHE_PATH, f"sec_utils/{ticker_symbol}_{fyear}_{section}.txt")
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                section_text = f.read()
        else:
            section_text = extractor.get_section(report_address, section, "text")
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                f.write(section_text)

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w") as f:
                f.write(section_text)

        return section_text
