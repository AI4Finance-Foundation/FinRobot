"""SEC EDGAR Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.providers.sec_provider import (
    SECEdgarProvider,
    _MDNA_MAX_CHARS,
    _extract_mdna,
)


@pytest.fixture
def provider():
    return SECEdgarProvider(user_agent="TestAgent test@test.com")


def _sec_company_tickers_response() -> dict:
    """Mock SEC company_tickers.json — used by _resolve_cik()."""
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc"},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }


def _sec_submissions_response() -> dict:
    """Mock SEC EDGAR /submissions/ response."""
    return {
        "cik": "0000320193",
        "entityType": "operating",
        "name": "Apple Inc",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000081"],
                "filingDate": ["2024-11-01"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20240928.htm"],
            }
        },
    }


def _sec_submissions_no_10k_response() -> dict:
    """Mock SEC EDGAR response with no 10-K filings."""
    return {
        "cik": "0000320193",
        "name": "Apple Inc",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000099"],
                "filingDate": ["2024-06-01"],
                "form": ["10-Q"],
                "primaryDocument": ["aapl-20240601.htm"],
            }
        },
    }


_SAMPLE_10K_HTML = """
<html><body>
<h1>Annual Report</h1>
<p>Some preamble text about the company.</p>

<h2>Item 6. Selected Financial Data</h2>
<p>Revenue was $394 billion.</p>

<h2>Item 7. Management's Discussion and Analysis of Financial Condition</h2>
<p>The following discussion should be read in conjunction with the consolidated
financial statements.</p>
<p>Revenue increased 8% year over year driven by strong iPhone sales.
Operating expenses grew 3% reflecting disciplined cost management.
Gross margin expanded to 46.2% from 44.1% in the prior year.</p>
<p>We expect continued growth in Services revenue.</p>

<h2>Item 8. Financial Statements and Supplementary Data</h2>
<p>See consolidated financial statements on page 42.</p>
</body></html>
"""


def _mock_response(json_data=None, text_data=None, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    else:
        resp.text = ""
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestSECEdgarFetch:
    async def test_fetch_filings_returns_10k_info(self, provider):
        """_fetch_filings calls _get: _resolve_cik, submissions, then 10-K content."""
        responses = [
            _mock_response(_sec_company_tickers_response()),  # _resolve_cik
            _mock_response(_sec_submissions_response()),  # submissions
            _mock_response(text_data=_SAMPLE_10K_HTML),  # 10-K content
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.provider == "sec_edgar"
        assert result.data_type == "filings"
        assert result.data["latest_10k_date"] == "2024-11-01"
        assert result.data["has_10k"] is True

    async def test_fetch_returns_mdna_text(self, provider):
        """MD&A section is extracted from 10-K content."""
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=_SAMPLE_10K_HTML),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.data["mdna_available"] is True
        assert "Management" in result.data["mdna_text"]
        assert "Revenue increased 8%" in result.data["mdna_text"]
        # MD&A should NOT include Item 8 content
        assert "consolidated financial statements on page 42" not in result.data["mdna_text"]

    async def test_fetch_no_10k_returns_warning(self, provider):
        """When no 10-K is found, mdna_available is False and warning is set."""
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_no_10k_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.data["has_10k"] is False
        assert result.data["mdna_available"] is False
        assert result.data["mdna_text"] == ""
        assert any("No 10-K" in w for w in result.warnings)

    async def test_mdna_extraction_graceful_degradation(self, provider):
        """If 10-K download fails, metadata is still returned with a warning."""
        cik_resp = _mock_response(_sec_company_tickers_response())
        sub_resp = _mock_response(_sec_submissions_response())

        call_count = 0

        async def side_effect_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return cik_resp
            elif call_count == 2:
                return sub_resp
            else:
                # 10-K download fails
                raise httpx.TimeoutException("10-K download timeout")

        with patch.object(provider, "_get", AsyncMock(side_effect=side_effect_fn)):
            result = await provider.fetch("AAPL", "filings")

        # Metadata still present
        assert result.data["has_10k"] is True
        assert result.data["latest_10k_date"] == "2024-11-01"
        # MD&A degraded
        assert result.data["mdna_available"] is False
        assert result.data["mdna_text"] == ""
        assert any("MD&A" in w for w in result.warnings)

    async def test_mdna_no_item7_returns_empty(self, provider):
        """If 10-K has no Item 7, MD&A is empty with a warning."""
        html_no_item7 = "<html><body><p>Some filing content with no MD&amp;A section.</p></body></html>"
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=html_no_item7),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.data["has_10k"] is True
        assert result.data["mdna_available"] is False
        assert result.data["mdna_text"] == ""
        assert any("MD&A section not found" in w for w in result.warnings)

    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    async def test_user_agent_in_headers(self, provider):
        """SEC EDGAR requires User-Agent header."""
        assert provider._user_agent == "TestAgent test@test.com"

    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "filings")

    async def test_rate_limit_403_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403",
                    request=MagicMock(),
                    response=MagicMock(status_code=403),
                )
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")


class TestExtractMdna:
    """Tests for the _extract_mdna pure function."""

    def test_extracts_item7_content(self):
        text = (
            "Item 6. Selected Data\n"
            "Some financial data.\n\n"
            "Item 7. Management's Discussion and Analysis\n"
            "Revenue grew 10%. Margins expanded.\n"
            "We see strong momentum.\n\n"
            "Item 8. Financial Statements\n"
            "See page 50."
        )
        mdna = _extract_mdna(text)
        assert "Revenue grew 10%" in mdna
        assert "Margins expanded" in mdna
        assert "See page 50" not in mdna

    def test_handles_various_item7_formats(self):
        # "ITEM 7" uppercase
        text = "ITEM 7 MANAGEMENT'S DISCUSSION\nGood stuff here.\nITEM 8 FINANCIALS\n"
        assert "Good stuff here" in _extract_mdna(text)

        # "Item 7." with period
        text = "Item 7. Management's Discussion and Analysis\nContent.\nItem 8. Financial Statements\n"
        assert "Content" in _extract_mdna(text)

        # em-dash separator
        text = "Item 7\u2014Management's Discussion\nAnalysis text.\nItem 8\u2014Financial Statements\n"
        assert "Analysis text" in _extract_mdna(text)

    def test_returns_empty_when_no_item7(self):
        text = "This filing has no management discussion section. Just general information."
        assert _extract_mdna(text) == ""

    def test_truncates_long_mdna(self):
        # Create MD&A text that exceeds the limit
        header = "Item 7. Management's Discussion and Analysis\n"
        long_content = "x" * (_MDNA_MAX_CHARS + 10000)
        text = header + long_content + "\nItem 8. Financial Statements\n"

        mdna = _extract_mdna(text)
        assert len(mdna) <= _MDNA_MAX_CHARS + 100  # allow for truncation marker
        assert "[... truncated for length ...]" in mdna

    def test_extracts_until_end_when_no_item8(self):
        """If Item 8 is missing, extract until end of document."""
        text = "Item 7. Management's Discussion\nAll the content goes here."
        mdna = _extract_mdna(text)
        assert "All the content goes here" in mdna

    def test_strips_html_artifacts_from_extracted_text(self):
        """After HTML stripping, extracted MD&A should be clean text."""
        # Simulate already-stripped text (as _fetch_10k_content would produce)
        text = (
            "Item 7. Management's Discussion and Analysis "
            "Revenue increased by 15% to $50 billion. "
            "Item 8. Financial Statements"
        )
        mdna = _extract_mdna(text)
        assert "Revenue increased by 15%" in mdna
        assert "Financial Statements" not in mdna


class TestSECEdgarInterface:
    def test_name(self, provider):
        assert provider.name == "sec_edgar"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "filings" in caps
        assert "financials" not in caps
