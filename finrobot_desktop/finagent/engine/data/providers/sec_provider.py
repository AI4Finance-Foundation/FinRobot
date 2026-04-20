from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.types import DataType

logger = logging.getLogger(__name__)

_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
_SUPPORTED = [DataType.FILINGS, DataType.RAG_10K]
_TIMEOUT = 15.0
_FILING_TIMEOUT = 30.0  # 10-K documents can be large (1-5MB)
_MIN_REQUEST_INTERVAL = 0.11  # SEC rate limit: 10 req/s -> at least 100ms between requests
_MDNA_MAX_CHARS = 50_000  # ~12k tokens — prevents context window overflow


class SECEdgarProvider(DataProvider):
    """DataProvider for SEC EDGAR (10-K/10-Q filings).

    Free, no API key required, but requires a User-Agent header
    (SEC policy: 'CompanyName AdminEmail').
    Rate limit: 10 requests/second.

    Returns filing metadata and, when available, the MD&A (Item 7)
    section extracted from the latest 10-K.
    """

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "sec_edgar"

    def capabilities(self) -> list[str | DataType]:
        return list(_SUPPORTED)

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type not in _SUPPORTED:
            raise ProviderError(
                f"data_type '{data_type}' is not supported by SEC EDGAR. Supported: {_SUPPORTED}"
            )
        if data_type == DataType.RAG_10K:
            return await self._fetch_10k_rag(ticker)
        try:
            data, warnings = await self._fetch_filings(ticker)
        except httpx.TimeoutException as e:
            raise ProviderError(f"SEC EDGAR timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"SEC EDGAR API error for '{ticker}': {e}") from e
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"SEC EDGAR fetch failed for '{ticker}': {e}") from e

        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    async def _fetch_filings(self, ticker: str) -> tuple[dict[str, Any], list[str]]:
        """Fetch latest 10-K filing metadata and MD&A from SEC EDGAR.

        Returns:
            Tuple of (data dict, warnings list).
        """
        warnings: list[str] = []
        cik = await self._resolve_cik(ticker)
        submissions = (await self._get(f"{_SUBMISSIONS_URL}/CIK{cik}.json")).json()

        filings = submissions.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])

        # Find latest 10-K
        latest_10k_idx = None
        for i, form in enumerate(forms):
            if form == "10-K":
                latest_10k_idx = i
                break

        if latest_10k_idx is None:
            return {
                "company_name": submissions.get("name"),
                "cik": cik,
                "latest_10k_date": None,
                "latest_10k_accession": None,
                "has_10k": False,
                "mdna_text": "",
                "mdna_available": False,
            }, ["No 10-K filing found"]

        accession = accessions[latest_10k_idx]
        primary_doc = primary_docs[latest_10k_idx] if latest_10k_idx < len(primary_docs) else ""

        # Attempt multi-section extraction — graceful degradation on failure
        items: dict[str, str] = {key: "" for key, _ in _ITEM_PATTERNS}
        if primary_doc:
            try:
                full_text = await self._fetch_10k_content(cik, accession, primary_doc)
                items = _extract_items(full_text)
            except (
                ValueError, KeyError, IndexError, AttributeError,
                httpx.HTTPStatusError, httpx.TimeoutException,
            ) as e:
                logger.warning("Failed to extract 10-K sections for %s: %s", ticker, e)
                warnings.append(f"MD&A extraction failed: {e}")

        mdna_text = items.get("item_7_mdna", "")
        if not mdna_text:
            warnings.append("MD&A section not found in 10-K filing")

        return {
            "company_name": submissions.get("name"),
            "cik": cik,
            "latest_10k_date": dates[latest_10k_idx],
            "latest_10k_accession": accession,
            "has_10k": True,
            "primary_document": primary_doc,
            "items": items,
            "mdna_text": mdna_text,
            "mdna_available": bool(mdna_text),
        }, warnings

    async def _fetch_10k_rag(self, ticker: str) -> DataResult:
        """Fetch 10-K sections and build a BM25 index for RAG queries.

        Merges all non-empty extracted sections (Item 1/1A/7/8) into a
        single text corpus with section labels, then indexes it.

        Returns DataResult with:
            data["rag_index"] — BM25Index instance (not JSON-serializable; in-memory only)
            data["mdna_text"] — raw MD&A text (for backward compatibility)
            data["chunk_count"] — number of chunks indexed
        """
        from finagent.engine.compute.rag import BM25Index, chunk_text

        _SECTION_LABELS: dict[str, str] = {
            "item_1_business": "Item 1 - Business",
            "item_1a_risks": "Item 1A - Risk Factors",
            "item_7_mdna": "Item 7 - MD&A",
            "item_8_financials": "Item 8 - Financial Statements",
        }

        # Reuse existing filing fetch for multi-section extraction
        data, warnings = await self._fetch_filings(ticker)
        items: dict[str, str] = data.get("items", {})
        mdna_text: str = data.get("mdna_text", "")

        # Merge all non-empty sections for RAG indexing
        merged_sections: list[str] = []
        for key, label in _SECTION_LABELS.items():
            section_text = items.get(key, "")
            if section_text:
                merged_sections.append(f"[{label}]\n{section_text}")

        if not merged_sections:
            logger.warning("10k_rag: No 10-K sections available for %s — empty index", ticker)
            chunks = []
        else:
            merged_text = "\n\n".join(merged_sections)
            source_label = f"10-K/{data.get('latest_10k_date', 'unknown')}"
            chunks = chunk_text(merged_text, chunk_size=300, overlap=30, source=source_label)

        rag_index = BM25Index(chunks)
        return DataResult(
            data={
                "rag_index": rag_index,
                "mdna_text": mdna_text,
                "chunk_count": len(chunks),
            },
            provider=self.name,
            ticker=ticker,
            data_type=DataType.RAG_10K,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    async def _fetch_10k_content(self, cik: str, accession: str, primary_doc: str) -> str:
        """Download and extract text content from a 10-K filing.

        Args:
            cik: Zero-padded CIK number.
            accession: Accession number (e.g. '0000320193-24-000081').
            primary_doc: Primary document filename (e.g. 'aapl-20240928.htm').

        Returns:
            Plain text content of the filing with HTML tags stripped.
        """
        # SEC EDGAR URL format uses accession without dashes in the path
        accession_path = accession.replace("-", "")
        url = f"{_ARCHIVES_URL}/{cik.lstrip('0')}/{accession_path}/{primary_doc}"
        resp = await self._get(url, accept="text/html", timeout=_FILING_TIMEOUT)
        html = resp.text

        # Strip HTML tags — simple regex, no BeautifulSoup dependency
        text = re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse multiple newlines but preserve paragraph breaks
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def _resolve_cik(self, ticker: str) -> str:
        """Resolve ticker to zero-padded CIK."""
        tickers = (await self._get("https://www.sec.gov/files/company_tickers.json")).json()
        for entry in tickers.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        raise ProviderError(f"Could not resolve CIK for ticker '{ticker}'")

    async def _get(
        self,
        url: str,
        accept: str = "application/json",
        timeout: float = _TIMEOUT,
    ) -> httpx.Response:
        """Make rate-limited GET request with required User-Agent.

        Args:
            url: Target URL.
            accept: Accept header value.
            timeout: Request timeout in seconds.
        """
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request
            if elapsed < _MIN_REQUEST_INTERVAL:
                await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)

            headers = {
                "User-Agent": self._user_agent,
                "Accept": accept,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers)
                self._last_request = asyncio.get_event_loop().time()
                resp.raise_for_status()
                return resp


_ITEM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("item_1_business", re.compile(r"(?i)item\s+1[.\s\u2014\u2013\-]+business")),
    ("item_1a_risks", re.compile(r"(?i)item\s+1a[.\s\u2014\u2013\-]+risk\s+factor")),
    ("item_7_mdna", re.compile(r"(?i)item\s+7[.\s\u2014\u2013\-]+management")),
    ("item_8_financials", re.compile(r"(?i)item\s+8[.\s\u2014\u2013\-]+financial\s+statement")),
]


def _extract_items(full_text: str) -> dict[str, str]:
    """Extract multiple 10-K sections by regex pattern matching.

    Extracts Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A),
    and Item 8 (Financial Statements) from SEC 10-K filing text.

    For each item, finds the section header and reads until the next
    item header (any ``Item N`` pattern, not just the next expected one).
    Missing sections return empty string.
    Each section truncated to ``_MDNA_MAX_CHARS`` individually.

    **What this code does that raw LLM cannot**: deterministic regex-based
    section boundary detection with guaranteed truncation — an LLM cannot
    reliably parse multi-megabyte filings or enforce length limits.
    """
    # Find positions of our target sections
    all_positions: list[tuple[str, int]] = []
    for key, pattern in _ITEM_PATTERNS:
        match = pattern.search(full_text)
        if match:
            all_positions.append((key, match.start()))

    # Find all "Item N" headers for boundary detection (including ours)
    other_items = re.finditer(r"(?i)\bitem\s+\d+[a-z]?[.\s\u2014\u2013\-]", full_text)
    boundaries = sorted(set(m.start() for m in other_items))

    # Sort found items by position
    all_positions.sort(key=lambda x: x[1])

    result: dict[str, str] = {key: "" for key, _ in _ITEM_PATTERNS}

    for _i, (key, start) in enumerate(all_positions):
        # Find end: next item header position after start (skip self-match)
        end = len(full_text)
        for b in boundaries:
            if b > start + 50:  # skip self-match — header is shorter than 50 chars
                end = b
                break

        section = full_text[start:end].strip()
        if len(section) > _MDNA_MAX_CHARS:
            section = section[:_MDNA_MAX_CHARS]
        result[key] = section

    return result


def _extract_mdna(full_text: str) -> str:
    """Extract Item 7 (MD&A) section from 10-K text.

    Searches for the Item 7 header and extracts content until Item 8.
    Returns empty string if extraction fails (graceful degradation).

    This is a module-level pure function for easy testing.
    """
    # Item 7 start patterns — ordered from most specific to broadest
    start_patterns = [
        r"(?i)item\s+7[.\s\u2014\u2013\-]+\s*management.s\s+discussion\s+and\s+analysis",
        r"(?i)item\s+7[.\s\u2014\u2013\-]+\s*management.s\s+discussion",
        r"(?i)item\s+7[.\s\u2014\u2013\-]+\s*md&a",
        r"(?i)\bitem\s+7\b",
    ]
    start = -1
    for pattern in start_patterns:
        match = re.search(pattern, full_text)
        if match:
            start = match.start()
            break

    if start == -1:
        return ""

    # Item 8 end patterns — search after skipping the Item 7 header itself
    search_offset = start + 50  # skip past "Item 7" header text
    end_patterns = [
        r"(?i)item\s+8[.\s\u2014\u2013\-]+\s*financial\s+statements",
        r"(?i)\bitem\s+8\b",
    ]
    end = len(full_text)
    for pattern in end_patterns:
        match = re.search(pattern, full_text[search_offset:])
        if match:
            end = search_offset + match.start()
            break

    mdna = full_text[start:end].strip()

    # Truncate if too long — prevents LLM context window overflow
    if len(mdna) > _MDNA_MAX_CHARS:
        mdna = mdna[:_MDNA_MAX_CHARS] + "\n\n[... truncated for length ...]"

    return mdna
