import importlib.util
from pathlib import Path


FMP_UTILS_PATH = Path(__file__).parents[1] / "finrobot" / "data_source" / "fmp_utils.py"
SPEC = importlib.util.spec_from_file_location(
    "finrobot.data_source.fmp_utils", FMP_UTILS_PATH
)
fmp_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fmp_utils)
FMPUtils = fmp_utils.FMPUtils


class MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_get_sec_report_uses_stable_symbol_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return MockResponse(
            [
                {
                    "formType": "10-Q",
                    "filingDate": "2024-05-03",
                    "link": "https://www.sec.gov/Archives/example-10q.htm",
                },
                {
                    "formType": "10-K",
                    "filingDate": "2024-02-02",
                    "link": "https://www.sec.gov/Archives/example-10k.htm",
                },
            ]
        )

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_utils.requests, "get", fake_get)

    result = FMPUtils.get_sec_report("AAPL")

    assert captured["url"] == (
        "https://financialmodelingprep.com/stable/sec-filings-search/symbol"
    )
    assert captured["params"]["symbol"] == "AAPL"
    assert captured["params"]["from"] == "1990-01-01"
    assert captured["params"]["apikey"] == "test-key"
    assert result == (
        "Link: https://www.sec.gov/Archives/example-10k.htm\n"
        "Filing Date: 2024-02-02"
    )


def test_get_sec_report_filters_year_and_supports_legacy_fields(monkeypatch):
    captured = {}

    def fake_get(url, params=None):
        captured["params"] = params
        return MockResponse(
            [
                {
                    "type": "10-K",
                    "fillingDate": "2023-02-03",
                    "finalLink": "https://www.sec.gov/Archives/legacy-10k.htm",
                }
            ]
        )

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_utils.requests, "get", fake_get)

    result = FMPUtils.get_sec_report("MSFT", "2023")

    assert captured["params"]["from"] == "2023-01-01"
    assert captured["params"]["to"] == "2023-12-31"
    assert result == (
        "Link: https://www.sec.gov/Archives/legacy-10k.htm\n"
        "Filing Date: 2023-02-03"
    )


def test_get_sec_report_checks_next_page_for_annual_report(monkeypatch):
    calls = []

    def fake_get(url, params=None):
        calls.append(params.copy())
        if params["page"] == 0:
            return MockResponse(
                [
                    {
                        "formType": "4",
                        "filingDate": "2025-01-02",
                        "link": "https://www.sec.gov/Archives/insider.htm",
                    }
                    for _ in range(params["limit"])
                ]
            )

        return MockResponse(
            [
                {
                    "formType": "10-K",
                    "filingDate": "2024-11-01",
                    "link": "https://www.sec.gov/Archives/page-two-10k.htm",
                }
            ]
        )

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_utils.requests, "get", fake_get)

    result = FMPUtils.get_sec_report("AAPL")

    assert [call["page"] for call in calls] == [0, 1]
    assert result == (
        "Link: https://www.sec.gov/Archives/page-two-10k.htm\n"
        "Filing Date: 2024-11-01"
    )
