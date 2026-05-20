"""SEC EDGAR Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.providers.sec_provider import (
    SECEdgarProvider,
    _MDNA_MAX_CHARS,
    _extract_items,
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
        html_no_item7 = (
            "<html><body><p>Some filing content with no MD&amp;A section.</p></body></html>"
        )
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


class TestSECNetworkErrors:
    """New catch branches: ConnectError on filings + RAG_10K paths."""

    async def test_connect_error_on_filings_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")

    async def test_connect_error_on_rag_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "10k_rag")

    async def test_cik_map_load_failure_does_not_cache_empty_map(self, provider):
        """If _load_ticker_cik_map fails, _ticker_cik_map must remain None so next
        request retries instead of hitting a permanently empty map."""
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("down")),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")
        # Map must not be cached — next call will retry
        assert provider._ticker_cik_map is None

    async def test_remote_protocol_error_on_filings_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.RemoteProtocolError("EOF")),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")


class TestExtractMdna:
    """Tests for Item 7 extraction via _extract_items."""

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
        items = _extract_items(text)
        mdna = items["item_7_mdna"]
        assert "Revenue grew 10%" in mdna
        assert "Margins expanded" in mdna
        assert "See page 50" not in mdna

    def test_handles_various_item7_formats(self):
        # "Item 7." with period
        text = (
            "Item 7. Management's Discussion and Analysis\nContent.\nItem 8. Financial Statements\n"
        )
        items = _extract_items(text)
        assert "Content" in items["item_7_mdna"]

        # em-dash separator
        text = "Item 7\u2014Management's Discussion\nAnalysis text.\nItem 8\u2014Financial Statements\n"
        items = _extract_items(text)
        assert "Analysis text" in items["item_7_mdna"]

    def test_returns_empty_when_no_item7(self):
        text = "This filing has no management discussion section. Just general information."
        items = _extract_items(text)
        assert items["item_7_mdna"] == ""

    def test_truncates_long_mdna(self):
        # Create MD&A text that exceeds the limit
        header = "Item 7. Management's Discussion and Analysis\n"
        long_content = "x" * (_MDNA_MAX_CHARS + 10000)
        text = header + long_content + "\nItem 8. Financial Statements\n"

        items = _extract_items(text)
        mdna = items["item_7_mdna"]
        assert len(mdna) <= _MDNA_MAX_CHARS + 100  # allow for header margin

    def test_extracts_until_end_when_no_item8(self):
        """If Item 8 is missing, extract until end of document."""
        text = "Item 7. Management's Discussion\nAll the content goes here."
        items = _extract_items(text)
        assert "All the content goes here" in items["item_7_mdna"]

    def test_strips_html_artifacts_from_extracted_text(self):
        """After HTML stripping, extracted MD&A should be clean text."""
        # Simulate already-stripped text (as _fetch_10k_content would produce)
        text = (
            "Item 7. Management's Discussion and Analysis "
            "Revenue increased by 15% to $50 billion. "
            "Item 8. Financial Statements"
        )
        items = _extract_items(text)
        mdna = items["item_7_mdna"]
        assert "Revenue increased by 15%" in mdna
        assert "Financial Statements" not in mdna


class TestExtractItems:
    """P6-T14: Tests for _extract_items multi-section extraction."""

    def test_extract_items_finds_all_four_sections(self):
        """P6-T14: _extract_items extracts Item 1, 1A, 7, 8."""
        text = (
            "Some preamble text\n"
            "Item 1. Business\n"
            "We are a technology company.\n"
            "Item 1A. Risk Factors\n"
            "We face market risks.\n"
            "Item 7. Management's Discussion and Analysis\n"
            "Revenue grew 10%.\n"
            "Item 8. Financial Statements and Supplementary Data\n"
            "See consolidated statements.\n"
            "Item 9. Changes in Disagreements\n"
        )
        items = _extract_items(text)
        assert "item_1_business" in items
        assert "technology company" in items["item_1_business"]
        assert "item_1a_risks" in items
        assert "market risks" in items["item_1a_risks"]
        assert "item_7_mdna" in items
        assert "Revenue grew" in items["item_7_mdna"]
        assert "item_8_financials" in items
        assert "consolidated statements" in items["item_8_financials"]

    def test_extract_items_missing_section_returns_empty(self):
        """P6-T14: missing sections return empty string, not error."""
        text = "Item 7. Management's Discussion\nSome analysis.\nItem 8. Financial Statements\nNumbers."
        items = _extract_items(text)
        assert items.get("item_1_business") == ""
        assert items.get("item_1a_risks") == ""
        assert "analysis" in items["item_7_mdna"]
        assert "Numbers" in items["item_8_financials"]

    def test_extract_items_truncates_long_sections(self):
        """P6-T14: each section truncated to _MDNA_MAX_CHARS individually."""
        long_text = "x" * 100_000
        text = f"Item 7. Management's Discussion\n{long_text}\nItem 8. Financial Statements\nShort."
        items = _extract_items(text)
        assert len(items["item_7_mdna"]) <= _MDNA_MAX_CHARS + 100  # header + some margin


class TestFetch10kRag:
    """P6-T15: Tests for _fetch_10k_rag multi-section RAG indexing."""

    _SAMPLE_10K_ALL_SECTIONS = (
        "<html><body>"
        "<h2>Item 1. Business</h2>"
        "<p>We are a global technology company specializing in consumer electronics.</p>"
        "<h2>Item 1A. Risk Factors</h2>"
        "<p>We face significant supply chain concentration risk.</p>"
        "<h2>Item 7. Management's Discussion and Analysis</h2>"
        "<p>Revenue increased 12% driven by services growth.</p>"
        "<h2>Item 8. Financial Statements and Supplementary Data</h2>"
        "<p>Total assets were $352 billion at year end.</p>"
        "<h2>Item 9. Changes in and Disagreements With Accountants</h2>"
        "<p>None.</p>"
        "</body></html>"
    )

    async def test_fetch_10k_rag_indexes_all_sections(self, provider):
        """P6-T15: RAG chunks should include content from all four sections."""
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=self._SAMPLE_10K_ALL_SECTIONS),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "10k_rag")

        assert result.data_type == "10k_rag"
        assert result.data["chunk_count"] > 0

        # All four sections should be represented in the chunks
        rag_index = result.data["rag_index"]
        all_chunk_text = " ".join(c.text for c in rag_index._chunks)
        assert "consumer electronics" in all_chunk_text
        assert "supply chain" in all_chunk_text
        assert "services growth" in all_chunk_text
        assert "352 billion" in all_chunk_text

        # Backward compatibility: mdna_text is still available
        assert "Management" in result.data["mdna_text"] or "Revenue" in result.data["mdna_text"]

    async def test_rag_chunks_have_section_labels(self, provider):
        """P6-T15: Each chunk in the RAG index should contain [Item N - Label] prefixes."""
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=self._SAMPLE_10K_ALL_SECTIONS),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "10k_rag")

        rag_index = result.data["rag_index"]
        all_chunk_text = " ".join(c.text for c in rag_index._chunks)

        # Section label prefixes should appear in the chunked text
        assert "[Item 1 - Business]" in all_chunk_text
        assert "[Item 1A - Risk Factors]" in all_chunk_text
        assert "[Item 7 - MD&A]" in all_chunk_text
        assert "[Item 8 - Financial Statements]" in all_chunk_text

    async def test_rag_empty_sections_excluded(self, provider):
        """P6-T15: Sections missing from the filing should not produce labeled chunks."""
        # HTML with only Item 7 and Item 8
        html_partial = (
            "<html><body>"
            "<h2>Item 7. Management's Discussion and Analysis</h2>"
            "<p>Revenue grew 5%.</p>"
            "<h2>Item 8. Financial Statements and Supplementary Data</h2>"
            "<p>See statements.</p>"
            "<h2>Item 9. Changes in Disagreements</h2>"
            "</body></html>"
        )
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=html_partial),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "10k_rag")

        rag_index = result.data["rag_index"]
        all_chunk_text = " ".join(c.text for c in rag_index._chunks)

        # Only Item 7 and 8 should have labels
        assert "[Item 7 - MD&A]" in all_chunk_text
        assert "[Item 8 - Financial Statements]" in all_chunk_text
        # Item 1 and 1A should NOT appear since they weren't in the filing
        assert "[Item 1 - Business]" not in all_chunk_text
        assert "[Item 1A - Risk Factors]" not in all_chunk_text

    async def test_rag_no_sections_yields_empty_index(self, provider):
        """P6-T15: If no sections extracted, chunk_count is 0."""
        html_empty = "<html><body><p>No recognizable sections.</p></body></html>"
        responses = [
            _mock_response(_sec_company_tickers_response()),
            _mock_response(_sec_submissions_response()),
            _mock_response(text_data=html_empty),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "10k_rag")

        assert result.data["chunk_count"] == 0
        assert result.data["mdna_text"] == ""


class TestRagSectionLabelMerging:
    """P6-T15: Pure-function test for section label merging logic."""

    _SECTION_LABELS = {
        "item_1_business": "Item 1 - Business",
        "item_1a_risks": "Item 1A - Risk Factors",
        "item_7_mdna": "Item 7 - MD&A",
        "item_8_financials": "Item 8 - Financial Statements",
    }

    def test_rag_chunks_have_section_labels(self):
        """P6-T15: RAG chunks from multi-section should have [Item N] prefixes."""
        text = (
            "Item 1. Business\nWe make widgets.\n"
            "Item 7. Management's Discussion\nRevenue grew.\n"
        )
        items = _extract_items(text)
        # Simulate what _fetch_10k_rag does: merge with labels
        merged_parts = []
        for key, label in self._SECTION_LABELS.items():
            section_text = items.get(key, "")
            if section_text:
                merged_parts.append(f"[{label}]\n{section_text}")
        merged = "\n\n".join(merged_parts)
        assert "[Item 1 - Business]" in merged
        assert "[Item 7 - MD&A]" in merged
        assert "widgets" in merged

    def test_empty_sections_excluded_from_merge(self):
        """P6-T15: Only non-empty sections appear in merged text."""
        text = "Item 7. Management's Discussion\nAnalysis here.\n"
        items = _extract_items(text)
        merged_parts = []
        for key, label in self._SECTION_LABELS.items():
            section_text = items.get(key, "")
            if section_text:
                merged_parts.append(f"[{label}]\n{section_text}")
        merged = "\n\n".join(merged_parts)
        assert "[Item 7 - MD&A]" in merged
        assert "[Item 1 - Business]" not in merged
        assert "[Item 1A - Risk Factors]" not in merged
        assert "[Item 8 - Financial Statements]" not in merged


class TestSECEdgarInterface:
    def test_name(self, provider):
        assert provider.name == "sec_edgar"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "filings" in caps
        assert "financials" not in caps
