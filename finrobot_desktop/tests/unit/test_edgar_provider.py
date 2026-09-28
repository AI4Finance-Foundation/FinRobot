"""EdgarToolsProvider — adapter unit tests (mock-only, no SEC network).

Strategy (per spec v4 §4 门 2 testing section):
  - Mock the edgar module's Company / get_filings via monkeypatch.setattr.
  - Stub Filing / TenK / TenQ / CurrentReport / Form4 / ProxyStatement /
    EntityFacts with MagicMock that returns probe-verified shapes.
  - The provider's _ADAPTER_CATCH must NOT swallow assertion errors from
    tests — that's why we use AttributeError sparingly inside mocks (mocks
    return None / "" by default, which exercises the empty-value paths).

Out of scope:
  - Real edgartools parsing (probe script does that).
  - 13F local cache integration (covered in test_sec_holdings_cache).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from finrobot.engine.data.interface import (
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.providers.edgar_provider import (
    EdgarToolsProvider,
    _MIN_VALID_SECTION_CHARS,
    _is_valid_identity,
    _sec_header_identity,
)
from finrobot.engine.data.types import DataType


# ---------------------------------------------------------------------------
# Local identity gate
# ---------------------------------------------------------------------------


class TestIsValidIdentity:
    """Sealed in spec v4 §4 门 1 local-identity-gate test set."""

    def test_rejects_empty(self) -> None:
        assert _is_valid_identity("") is False
        assert _is_valid_identity(None) is False  # type: ignore[arg-type]

    def test_rejects_default_config_value(self) -> None:
        assert _is_valid_identity("FinRobot admin@example.com") is False

    def test_rejects_no_email(self) -> None:
        assert _is_valid_identity("foobar") is False
        assert _is_valid_identity("FirstLast Person") is False

    def test_rejects_no_space(self) -> None:
        assert _is_valid_identity("no-space@example.com") is False

    def test_accepts_valid_english(self) -> None:
        assert _is_valid_identity("Jane Doe jane@example.com") is True

    def test_accepts_valid_chinese(self) -> None:
        assert _is_valid_identity("张三 zhangsan@example.com") is True

    def test_strips_whitespace(self) -> None:
        assert _is_valid_identity("  John j@x.io  ") is True

    def test_chinese_identity_gets_ascii_header(self) -> None:
        assert _sec_header_identity("郭嘉祺 17696026747@163.com") == (
            "FinRobot 17696026747@163.com"
        )


# ---------------------------------------------------------------------------
# Provider construction
# ---------------------------------------------------------------------------


class TestEdgarToolsProviderConstruction:
    def test_init_does_not_raise_on_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # set_identity is the only SEC-related call in __init__
        # (and it's purely local — it sets a module-level identity string).
        calls: list[str] = []
        monkeypatch.setattr(
            "finrobot.engine.data.providers.edgar_provider.set_identity",
            lambda s: calls.append(s),
        )
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        assert calls == ["Jane Doe jane@example.com"]
        assert p.name == "edgar_tools"

    def test_init_sanitizes_unicode_identity_for_http_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "finrobot.engine.data.providers.edgar_provider.set_identity",
            lambda s: calls.append(s),
        )
        p = EdgarToolsProvider("郭嘉祺 17696026747@163.com")
        assert calls == ["FinRobot 17696026747@163.com"]
        assert p.name == "edgar_tools"

    def test_capabilities_includes_legacy_aliases(self) -> None:
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        caps = p.capabilities()
        # New + legacy must both be advertised so DataLayer routes both
        # FILINGS and FILINGS_10K to this provider.
        assert DataType.FILINGS_10K in caps
        assert DataType.FILINGS in caps
        assert DataType.RAG_10K in caps
        assert DataType.INSIDER_TRADES in caps
        assert DataType.INSTITUTIONAL_HOLDINGS in caps


# ---------------------------------------------------------------------------
# _fetch_10k — happy path + 10-K/A fallback + financial-institution fallback
# ---------------------------------------------------------------------------


def _stub_company_with_10k(
    *,
    business: str = "AAPL business text" * 100,
    risk_factors: str = "Risk text " * 200,
    management_discussion: str = "MD&A text " * 500,
    form: str = "10-K",
) -> MagicMock:
    tenk = MagicMock()
    tenk.business = business
    tenk.risk_factors = risk_factors
    tenk.management_discussion = management_discussion
    tenk.directors_officers_and_governance = "Governance content " * 50
    tenk.subsidiaries = "Apple Sales International..."
    tenk.notes = "Note 1 — Significant Accounting Policies..."

    filing = MagicMock()
    filing.form = form
    filing.accession_no = "0000320193-26-000001"
    filing.filing_date = date(2026, 5, 1)
    filing.period_of_report = date(2026, 3, 28)
    filing.homepage_url = "https://www.sec.gov/cgi-bin/...accession..."
    filing.obj.return_value = tenk
    filing.text.return_value = "Full text fallback content " * 1000

    c = MagicMock()
    c.name = "Apple Inc."
    c.cik = 320193
    c.latest.return_value = filing
    return c


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("The read operation timed out"),
        httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known"),
    ],
)
@pytest.mark.asyncio
async def test_fetch_wraps_httpx_error_into_provider_error(
    exc: httpx.HTTPError, monkeypatch: pytest.MonkeyPatch
) -> None:
    """edgartools runs its OWN httpx client inside our to_thread call; a slow or
    unreachable SEC raises a raw httpx error that is NOT an OSError. fetch() must
    map it to ProviderError so _fetch_optional_sec / _gather_data degrade to
    "SEC unavailable" — the un-wrapped httpx.ReadTimeout / ConnectError observed
    tanking an entire equity_research run from _gather_data is the regression
    this guards (edgar_provider._ADAPTER_CATCH now includes httpx.HTTPError)."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")

    def _boom(_ticker: str) -> Any:
        raise exc

    monkeypatch.setattr("finrobot.engine.data.providers.edgar_provider.Company", _boom)
    with pytest.raises(ProviderError, match="edgartools"):
        await p.fetch("AAPL", DataType.FILINGS_8K, n=10)


@pytest.mark.asyncio
async def test_fetch_http_429_raises_typed_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapped HTTP 429 from edgartools' own httpx client must surface as the
    TYPED RateLimitedProviderError (primary classification path) so the
    circuit-breaker / quote-batch recognise throttling structurally. ONLY a
    literal 429 maps — SEC's 403 stays a plain ProviderError because 403 is
    also the generic forbidden/missing-identity status."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    request = httpx.Request("GET", "https://www.sec.gov/cgi-bin/browse-edgar")

    def _boom_429(_ticker: str) -> Any:
        raise httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=request,
            response=httpx.Response(429, request=request),
        )

    monkeypatch.setattr("finrobot.engine.data.providers.edgar_provider.Company", _boom_429)
    with pytest.raises(RateLimitedProviderError, match="edgartools") as exc_info:
        await p.fetch("AAPL", DataType.FILINGS_8K, n=10)
    assert is_rate_limit_error(exc_info.value)

    def _boom_403(_ticker: str) -> Any:
        raise httpx.HTTPStatusError(
            "403 Forbidden",
            request=request,
            response=httpx.Response(403, request=request),
        )

    monkeypatch.setattr("finrobot.engine.data.providers.edgar_provider.Company", _boom_403)
    with pytest.raises(ProviderError, match="edgartools") as exc_info_403:
        await p.fetch("AAPL", DataType.FILINGS_8K, n=10)
    assert not isinstance(exc_info_403.value, RateLimitedProviderError)
    assert not is_rate_limit_error(exc_info_403.value)


@pytest.mark.asyncio
async def test_fetch_10k_happy_path() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    c = _stub_company_with_10k()
    data, warnings = p._fetch_10k(c, want_rag=False)
    assert data["has_10k"] is True
    assert data["sections_extraction_quality"] == "ok"
    # Each canonical_id present with non-trivial text
    items = data["items"]
    assert items["item_1_business"].startswith("AAPL business")
    assert items["item_1a_risk_factors"].startswith("Risk text")
    assert items["item_7_mdna"].startswith("MD&A text")
    # No warnings on clean path
    assert warnings == []


@pytest.mark.asyncio
async def test_fetch_10k_amended_triggers_redirect() -> None:
    """10-K/A detection: adapter re-fetches with amendments=False.

    Probe 2026-05-27: TSLA latest 10-K is 10-K/A (Tornetta amendment),
    edgartools' fallback parser returns empty section attrs. We MUST
    re-fetch the original 10-K to get usable section text.
    """
    p = EdgarToolsProvider("Jane Doe jane@example.com")

    # First call returns 10-K/A with empty sections
    amended = MagicMock()
    amended.form = "10-K/A"
    amended.accession_no = "0001104659-26-053166"
    amended.filing_date = date(2026, 4, 30)
    amended.period_of_report = date(2025, 12, 31)
    amended.homepage_url = None
    amended_tenk = MagicMock()
    for attr in (
        "business",
        "risk_factors",
        "management_discussion",
        "directors_officers_and_governance",
        "subsidiaries",
        "notes",
    ):
        setattr(amended_tenk, attr, "")
    amended.obj.return_value = amended_tenk
    amended.text.return_value = ""

    # Second call (with amendments=False) returns the proper original 10-K
    original = MagicMock()
    original.form = "10-K"
    original.accession_no = "0001628280-26-021345"
    original.filing_date = date(2026, 1, 30)
    original.period_of_report = date(2025, 12, 31)
    original.homepage_url = "https://sec.gov/..."
    original_tenk = MagicMock()
    original_tenk.business = "Tesla business " * 200
    original_tenk.risk_factors = "Tesla risks " * 500
    original_tenk.management_discussion = "Tesla MD&A " * 800
    original_tenk.directors_officers_and_governance = ""
    original_tenk.subsidiaries = ""
    original_tenk.notes = ""
    original.obj.return_value = original_tenk

    c = MagicMock()
    c.name = "Tesla, Inc."
    c.cik = 1318605
    c.latest.return_value = amended
    fallback_filings = MagicMock()
    fallback_filings.latest.return_value = original
    c.get_filings.return_value = fallback_filings

    data, warnings = p._fetch_10k(c, want_rag=False)
    # The redirect message is in warnings
    assert any("amended" in w for w in warnings)
    # And the resulting form is the original 10-K, not 10-K/A
    assert data["form"] == "10-K"
    assert data["is_amended"] is False
    assert data["sections_extraction_quality"] == "amended_redirected"
    assert data["items"]["item_7_mdna"].startswith("Tesla MD&A")


@pytest.mark.asyncio
async def test_fetch_10k_short_mdna_falls_back_to_full_text() -> None:
    """JPM-style edge case: edgartools MD&A parser returns < 1000 chars."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    short_mdna = "Brief MD&A text"  # well under _MIN_VALID_SECTION_CHARS
    assert len(short_mdna) < _MIN_VALID_SECTION_CHARS
    c = _stub_company_with_10k(management_discussion=short_mdna)
    data, warnings = p._fetch_10k(c, want_rag=False)
    assert any("too short" in w for w in warnings)
    assert data["sections_extraction_quality"] == "fallback_to_full_text"
    # MD&A should now contain the full filing text (much longer)
    assert len(data["items"]["item_7_mdna"]) > _MIN_VALID_SECTION_CHARS
    # And the matching section's extracted_via flag is updated
    mdna_section = next(s for s in data["sections"] if s["canonical_id"] == "item_7_mdna")
    assert mdna_section["extracted_via"] == "filing_text_fallback"


@pytest.mark.asyncio
async def test_fetch_10k_returns_empty_when_no_filing() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    c = MagicMock()
    c.latest.return_value = None
    data, warnings = p._fetch_10k(c, want_rag=False)
    assert data == {"has_10k": False, "items": {}, "mdna_text": ""}
    assert warnings == ["No 10-K filing found"]


# ---------------------------------------------------------------------------
# _fetch_10q
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_10q_returns_n_filings() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    filings = []
    for i in range(4):
        f = MagicMock()
        f.form = "10-Q"
        f.accession_no = f"acc-{i}"
        f.filing_date = date(2026, 3 - i, 1) if 3 - i > 0 else date(2025, 12, 1)
        f.period_of_report = date(2026, 2 - i, 28) if 2 - i > 0 else date(2025, 11, 30)
        f.homepage_url = None
        tenq = MagicMock()
        tenq.management_discussion = f"Q{4 - i} MD&A " * 50
        f.obj.return_value = tenq
        filings.append(f)
    qfilings = MagicMock()
    qfilings.latest.return_value = filings  # already a list
    c = MagicMock()
    c.get_filings.return_value = qfilings
    data, _ = p._fetch_10q(c, n=4)
    assert len(data["quarterly_filings"]) == 4
    assert all("Q" in q["mdna_text"] for q in data["quarterly_filings"])


# ---------------------------------------------------------------------------
# _fetch_8k (CurrentReport — items is list[str])
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_8k_extracts_items_list() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    f = MagicMock()
    f.filing_date = date(2026, 4, 22)
    f.period_of_report = date(2026, 4, 22)
    f.accession_no = "0001628280-26-026551"
    f.homepage_url = None
    f.text.return_value = "8-K body text..."
    report = MagicMock()
    report.items = ["Item 2.02", "Item 9.01"]  # probe-verified shape
    f.obj.return_value = report
    eightk_filings = MagicMock()
    eightk_filings.latest.return_value = [f]
    c = MagicMock()
    c.get_filings.return_value = eightk_filings
    data, _ = p._fetch_8k(c, n=5)
    assert len(data["events"]) == 1
    assert data["events"][0]["items"] == ["Item 2.02", "Item 9.01"]
    assert data["events"][0]["text"].startswith("8-K body")


# ---------------------------------------------------------------------------
# _fetch_insider (Form 4 — uses get_transaction_activities)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_insider_flattens_transaction_activities() -> None:
    """One Form 4 with 2 TransactionActivity entries → 2 InsiderTransaction rows."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    # Activity 1: CFO sale of 3000 shares at $450 (matches probe TSLA fixture)
    act1 = MagicMock()
    act1.transaction_type = "sale"
    act1.code = "S"
    act1.shares = 3000
    act1.value = 1_350_000.0
    act1.price_per_share = 450.0
    act1.security_type = "non-derivative"
    act1.security_title = "Common Stock"
    act1.underlying_security = ""
    act1.exercise_date = None
    act1.expiration_date = None
    act1.footnote_ids = "F1"
    act1.footnotes_text = "Pursuant to 10b5-1 plan adopted 2025-11-17"
    # Activity 2: Musk forfeit 96M shares (zero value, code D)
    act2 = MagicMock()
    act2.transaction_type = "other_disposition"
    act2.code = "D"
    act2.shares = 96_000_000
    act2.value = 0
    act2.price_per_share = 0
    act2.security_type = "non-derivative"
    act2.security_title = "Common Stock"
    act2.underlying_security = ""
    act2.exercise_date = None
    act2.expiration_date = None
    act2.footnote_ids = "F1"
    act2.footnotes_text = "Tornetta Decision Event"
    # Activity 3: option exercise whose price_per_share is a FOOTNOTE MARKER
    # ("[F1]") rather than a number — a real Form 4 shape. bare float("[F1]")
    # used to raise ValueError and drop EVERY transaction; it must now parse to
    # None and leave the other rows intact. value=0 mirrors REAL edgartools
    # output: get_transaction_activities computes shares*price only when a usable
    # price exists and otherwise hard-codes ``else 0`` — so a footnoted price
    # surfaces as a fabricated value=0 (NOT None). It must abstain to None.
    act3 = MagicMock()
    act3.transaction_type = "exercise"
    act3.code = "M"
    act3.shares = 1000
    act3.value = 0  # edgartools' no-price sentinel (footnoted price)
    act3.price_per_share = "[F1]"
    act3.security_type = "non-derivative"
    act3.security_title = "Common Stock"
    act3.underlying_security = ""
    act3.exercise_date = None
    act3.expiration_date = None
    act3.footnote_ids = "F1"
    act3.footnotes_text = "Exercise price disclosed in footnote"

    form4 = MagicMock()
    form4.insider_name = "Elon Musk"
    form4.position = "CEO"
    form4.get_transaction_activities.return_value = [act1, act2, act3]

    f = MagicMock()
    f.filing_date = date.today() - timedelta(days=10)
    f.accession_no = "0001104659-26-062860"
    f.obj.return_value = form4
    filings = MagicMock()
    filings.latest.return_value = [f]
    c = MagicMock()
    c.get_filings.return_value = filings

    data, _ = p._fetch_insider(c, days=90)
    # All 3 rows survive — the "[F1]" price no longer crashes the whole parse.
    assert len(data["transactions"]) == 3
    # Real open-market sale: a genuinely computed positive value passes through.
    sale = next(t for t in data["transactions"] if t["code"] == "S")
    assert sale["value"] == 1_350_000.0
    assert sale["price_per_share"] == 450.0
    # Forfeit row preserves price=None when price_per_share=0; its edgartools
    # value=0 is the no-price sentinel, so value abstains to None (NOT $0 moved).
    forfeit = next(t for t in data["transactions"] if t["code"] == "D")
    assert forfeit["shares"] == 96_000_000
    assert forfeit["price_per_share"] is None  # 0 coerced to None
    assert forfeit["value"] is None  # None ≠ 0: no priced value, not a real $0
    assert "Tornetta" in forfeit["footnotes_text"]
    # Footnote-marker price → None (parse gap), not a crash. Its fabricated
    # value=0 (edgartools else-branch) must NOT read as "$0 of stock moved".
    exercise = next(t for t in data["transactions"] if t["code"] == "M")
    assert exercise["price_per_share"] is None
    assert exercise["shares"] == 1000
    assert exercise["value"] is None  # fabricated 0 abstains to None


@pytest.mark.asyncio
async def test_fetch_insider_drops_filings_outside_window() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    # One in-window + one out-of-window
    fresh = MagicMock()
    fresh.filing_date = date.today() - timedelta(days=10)
    fresh.accession_no = "fresh-acc"
    f4_fresh = MagicMock()
    f4_fresh.insider_name = "Fresh Insider"
    f4_fresh.position = "CFO"
    act = MagicMock()
    for attr in (
        "transaction_type",
        "code",
        "security_type",
        "security_title",
        "underlying_security",
        "footnote_ids",
        "footnotes_text",
    ):
        setattr(act, attr, "")
    act.shares = 100
    act.value = 1000.0
    act.price_per_share = 10.0
    act.exercise_date = None
    act.expiration_date = None
    f4_fresh.get_transaction_activities.return_value = [act]
    fresh.obj.return_value = f4_fresh

    stale = MagicMock()
    stale.filing_date = date.today() - timedelta(days=200)
    stale.accession_no = "stale-acc"

    filings = MagicMock()
    filings.latest.return_value = [fresh, stale]
    c = MagicMock()
    c.get_filings.return_value = filings

    data, _ = p._fetch_insider(c, days=90)
    # Only the fresh filing contributes; stale breaks the loop
    assert all(t["accession_no"] == "fresh-acc" for t in data["transactions"])
    # Specifically: stale filing's obj() was never called (loop broke before)
    stale.obj.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_insider_coerces_footnote_ref_dates_to_none() -> None:
    """Form 4 derivative rows often footnote exerciseDate/expirationDate (e.g.
    option grants with conditional vesting). edgartools surfaces those as
    strings like "[F4]" — they must be coerced to None at the provider
    boundary so downstream date parsing doesn't crash with
    ``Invalid isoformat string: '[F4]'``.
    """
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    act = MagicMock()
    act.transaction_type = "grant"
    act.code = "A"
    act.shares = 10_000
    act.value = 0
    act.price_per_share = 0
    act.security_type = "derivative"
    act.security_title = "Non-Qualified Stock Option"
    act.underlying_security = "Common Stock"
    act.exercise_date = "[F4]"
    act.expiration_date = "[F2]"
    act.footnote_ids = "F2,F4"
    act.footnotes_text = "Vests in equal annual installments per F4 schedule."

    form4 = MagicMock()
    form4.insider_name = "Jane Insider"
    form4.position = "Director"
    form4.get_transaction_activities.return_value = [act]

    f = MagicMock()
    f.filing_date = date.today() - timedelta(days=10)
    f.accession_no = "0000000000-26-000001"
    f.obj.return_value = form4
    filings = MagicMock()
    filings.latest.return_value = [f]
    c = MagicMock()
    c.get_filings.return_value = filings

    data, _ = p._fetch_insider(c, days=90)
    assert len(data["transactions"]) == 1
    tx = data["transactions"][0]
    assert tx["exercise_date"] is None
    assert tx["expiration_date"] is None
    # Footnote semantics are preserved — only the date stand-in is dropped
    assert tx["footnote_ids"] == "F2,F4"
    assert "F4 schedule" in tx["footnotes_text"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Shape 1: plain ISO date — passes through
        ("2025-04-15", "2025-04-15"),
        # Shape 2a: single footnote ref — canonical form
        ("[F4]", None),
        # Shape 2b: multi-digit footnote ref (TSLA Tornetta filings cite F17/F18)
        ("[F17]", None),
        # Shape 2c: comma-separated multi-footnote ref
        ("[F1,F2]", None),
        # Shape 3: date with trailing footnote suffix — strip the suffix,
        # keep the date
        ("2025-04-15 [F4]", "2025-04-15"),
        ("2025-04-15 [F1,F2]", "2025-04-15"),
        # Shape 4: empty string — collapse to None
        ("", None),
        ("   ", None),
        # Shape 5: filer free-text — collapse to None
        ("See footnote", None),
        ("N/A", None),
        # None passthrough
        (None, None),
    ],
)
def test_coerce_form4_date_handles_all_edgartools_shapes(
    raw: str | None, expected: str | None
) -> None:
    """edgartools' value_with_footnotes() produces five real shapes for Form 4
    date fields. The provider boundary collapses non-date shapes to None so
    downstream ``date.fromisoformat`` never sees garbage.
    """
    from finrobot.engine.data.providers.edgar_provider import _coerce_form4_date

    assert _coerce_form4_date(raw) == expected


def test_slice_proxy_text_splices_sct_window_past_intro() -> None:
    """Large proxies are 300k+ chars; the real Summary Compensation Table sits
    200k+ chars deep, well past the 50k governance-intro head cap. The slicer
    keeps the intro AND splices in a 90k window anchored on the table's column
    header "Name and Principal Position" — NOT a TOC/cross-reference mention of
    "Summary Compensation Table" — so the SCT row + pay-ratio extractors have
    the actual table AND the pay-ratio disclosure that follows it.
    """
    from finrobot.engine.data.providers.edgar_provider import _slice_proxy_text

    # Build a 50k intro that includes a TOC line near char 30k — the TOC
    # mention must NOT be treated as the real SCT anchor.
    toc_line = "Summary Compensation Table .... 143\n"
    filler_a = "x" * 30_000
    filler_b = "y" * (50_000 - len(filler_a) - len(toc_line))
    intro = "INTRO " + filler_a + toc_line + filler_b
    intro = intro[:50_000]  # ensure exact 50k
    assert len(intro) == 50_000

    body_gap = "z" * 60_000  # 60k chars between intro and real SCT
    # SCT + pay-ratio body, then a long filler so the tail lands BEYOND the
    # 90k window and is excluded.
    sct = (
        "Summary Compensation Table\n"
        "Name and Principal Position    Year   Salary    Total\n"
        "Elon Musk Chief Executive Officer 2024 0 100,000,000\n"
    ) + ("w" * 100_000)
    tail = "TAIL_BEYOND_SCT_WINDOW" * 5_000

    full = intro + body_gap + sct + tail
    sliced = _slice_proxy_text(full)

    # Intro is preserved verbatim
    assert sliced.startswith("INTRO ")
    # The real table (anchored on its column header) is present
    assert "Elon Musk Chief Executive Officer" in sliced
    # Bounded: intro (50k) + gap marker + 90k SCT window ≈ 140k
    assert 130_000 < len(sliced) < 145_000
    # Tail beyond the 90k SCT window is dropped
    assert "TAIL_BEYOND_SCT_WINDOW" not in sliced


def test_slice_proxy_text_returns_intro_only_when_no_sct_found() -> None:
    """If a proxy is short or doesn't contain an SCT heading past the
    intro window, return just the intro — don't drag along useless tail
    bytes."""
    from finrobot.engine.data.providers.edgar_provider import _slice_proxy_text

    short = "GOV intro " * 1_000  # well under 50k
    assert _slice_proxy_text(short) == short

    long_no_sct = "x" * 200_000
    sliced = _slice_proxy_text(long_no_sct)
    assert len(sliced) == 50_000


# ---------------------------------------------------------------------------
# _fetch_xbrl (typed getters)
# ---------------------------------------------------------------------------


class _FakeFinancialFact:
    """Minimal stand-in for edgartools ``FinancialFact``.

    Only the fields ``_select_latest_fact`` reads: ``concept`` (the REAL matched
    us-gaap tag — BUG-009), ``numeric_value``, ``period_end``, ``unit``.
    """

    def __init__(
        self,
        concept: str,
        numeric_value: float,
        period_end: date,
        unit: str = "USD",
    ) -> None:
        self.concept = concept
        self.numeric_value = numeric_value
        self.period_end = period_end
        self.unit = unit


class _FakeLatestFacts:
    """Fake EntityFacts serving ``get_ttm`` + ``get_annual_fact``/``get_fact``.

    ``annual_by_concept`` / ``recent_by_concept`` map a taxonomy-prefixed concept
    (e.g. ``us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax``) to a
    ``_FakeFinancialFact``. ``get_annual_fact`` consults the annual map (FY pref);
    ``get_fact`` consults the recent map. Absent concept → None (the getters'
    not-found contract), so the provider walks to the next variant.
    """

    def __init__(
        self,
        *,
        ttm: dict[str, _FakeTTMMetric] | None = None,
        annual: dict[str, _FakeFinancialFact] | None = None,
        recent: dict[str, _FakeFinancialFact] | None = None,
    ) -> None:
        self._ttm = ttm or {}
        self._annual = annual or {}
        self._recent = recent or {}

    def get_ttm(self, concept: str) -> _FakeTTMMetric:
        if concept not in self._ttm:
            raise KeyError(concept)
        return self._ttm[concept]

    def get_annual_fact(self, concept: str) -> _FakeFinancialFact | None:
        return self._annual.get(concept)

    def get_fact(self, concept: str) -> _FakeFinancialFact | None:
        return self._recent.get(concept)


@pytest.mark.asyncio
async def test_fetch_xbrl_selects_live_concept_via_get_ttm() -> None:
    """ADR-0008: _fetch_xbrl drives TTM through concept-aware ``get_ttm`` (latest
    period_end + structural gate), NOT the first-match ``get_ttm_revenue`` getter
    that latched abandoned concepts. A valid live-concept window is surfaced as a
    typed dict; absent net-income concepts (KeyError) → None. BUG-009:
    ``latest_revenue`` carries the REAL matched concept, not a bare float."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    pe = date(2025, 9, 27)
    facts = _FakeLatestFacts(
        ttm={
            "Revenues": _FakeTTMMetric(
                "us-gaap:Revenues",
                451_442_000_000,
                [(2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2")],
                date.today() - timedelta(days=30),  # recent → passes recency gate
            )
        },
        annual={
            # Post-ASC-606: AAPL reports revenue under RFCWCEAT, NOT Revenues —
            # the snapshot concept must reflect that, not a hardcoded label.
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": _FakeFinancialFact(
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                416_161_000_000,
                pe,
            ),
            "us-gaap:NetIncomeLoss": _FakeFinancialFact(
                "us-gaap:NetIncomeLoss", 96_995_000_000, pe
            ),
            "us-gaap:GrossProfit": _FakeFinancialFact("us-gaap:GrossProfit", 184_103_000_000, pe),
            "us-gaap:OperatingIncomeLoss": _FakeFinancialFact(
                "us-gaap:OperatingIncomeLoss", 123_216_000_000, pe
            ),
        },
        recent={
            "us-gaap:Assets": _FakeFinancialFact("us-gaap:Assets", 364_980_000_000, pe),
            "us-gaap:Liabilities": _FakeFinancialFact("us-gaap:Liabilities", 308_030_000_000, pe),
            "us-gaap:StockholdersEquity": _FakeFinancialFact(
                "us-gaap:StockholdersEquity", 56_950_000_000, pe
            ),
        },
    )

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)
    assert data["facts_available"] is True
    # BUG-009: latest_revenue is now a dict carrying the REAL matched concept.
    assert data["latest_revenue"]["value"] == 416_161_000_000
    assert data["latest_revenue"]["concept"] == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert data["latest_revenue"]["period_end"] == pe
    assert data["latest_revenue"]["units"] == "USD"
    assert data["ttm_revenue"]["concept"] == "us-gaap:Revenues"
    assert data["ttm_revenue"]["value"] == 451_442_000_000
    # BUG-010: periods are list[str] matching XBRLTTMMetric.periods.
    assert data["ttm_revenue"]["periods"][0] == "Q3 2025"
    assert data["ttm_net_income"] is None


@pytest.mark.asyncio
async def test_fetch_xbrl_balance_sheet_prefers_latest_period_over_latest_annual() -> None:
    """Reproduces the 2026-05-28 TSLA balance-sheet staleness bug: when the
    issuer has both a FY 10-K and a more recent 10-Q on file, the artifact
    must surface the 10-Q values. Balance-sheet getters use ``annual=False`` —
    so ``_select_latest_fact`` consults the most-recent point (``get_fact``),
    NOT the FY annual (``get_annual_fact``). Here only the recent map carries
    the Q1 10-Q values; the annual map (FY 10-K) is never consulted for BS items."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    q1_pe = date(2026, 3, 31)
    facts = _FakeLatestFacts(
        # No TTM, no P&L annuals — isolate the balance-sheet path.
        annual={
            # FY 10-K values present but MUST be ignored for BS (annual=False).
            "us-gaap:Assets": _FakeFinancialFact(
                "us-gaap:Assets", 137_806_000_000, date(2025, 12, 31)
            ),
        },
        recent={
            "us-gaap:Assets": _FakeFinancialFact("us-gaap:Assets", 143_724_000_000, q1_pe),
            "us-gaap:Liabilities": _FakeFinancialFact("us-gaap:Liabilities", 58_922_000_000, q1_pe),
            "us-gaap:StockholdersEquity": _FakeFinancialFact(
                "us-gaap:StockholdersEquity", 84_116_000_000, q1_pe
            ),
        },
    )

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)

    # Must surface the Q1 10-Q values, not the FY 10-K.
    assert data["latest_total_assets"]["value"] == 143_724_000_000
    assert data["latest_total_assets"]["period_end"] == q1_pe
    assert data["latest_total_liabilities"]["value"] == 58_922_000_000
    assert data["latest_shareholders_equity"]["value"] == 84_116_000_000


def test_select_latest_fact_revenue_prefers_total_on_same_period() -> None:
    """Financial-issuer revenue-subset bug (2026-06-29): MET reports total
    ``Revenues`` (77B) and the ASC-606 contract-revenue subset (2.4B) at the SAME
    annual period_end. prefer_recent resolves the tie to the total via concept
    rank — first-match used to latch the 2.4B subset (31× understated, fed to the
    LLM thesis prompt)."""
    from finrobot.engine.data.providers.edgar_provider import (
        _LATEST_REVENUE_CONCEPTS,
        _select_latest_fact,
    )

    pe = date(2025, 12, 31)
    facts = _FakeLatestFacts(
        annual={
            "us-gaap:Revenues": _FakeFinancialFact("us-gaap:Revenues", 77_084_000_000, pe),
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": _FakeFinancialFact(
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 2_436_000_000, pe
            ),
        }
    )
    out = _select_latest_fact(facts, _LATEST_REVENUE_CONCEPTS, annual=True, prefer_recent=True)
    assert out is not None
    assert out["concept"] == "us-gaap:Revenues"
    assert out["value"] == 77_084_000_000


def test_select_latest_fact_revenue_recency_beats_rank() -> None:
    """AAPL counter-case: ``Revenues`` froze at FY2018 (265B); live revenue is the
    ASC-606 concept at FY2025 (416B). Recency wins ACROSS periods even though the
    total outranks the subset — concept rank only breaks SAME-period ties, so a
    blind reorder-to-front would have regressed AAPL to the stale 265B."""
    from finrobot.engine.data.providers.edgar_provider import (
        _LATEST_REVENUE_CONCEPTS,
        _select_latest_fact,
    )

    facts = _FakeLatestFacts(
        annual={
            "us-gaap:Revenues": _FakeFinancialFact(
                "us-gaap:Revenues", 265_595_000_000, date(2018, 9, 29)
            ),
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": _FakeFinancialFact(
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                416_161_000_000,
                date(2025, 9, 27),
            ),
        }
    )
    out = _select_latest_fact(facts, _LATEST_REVENUE_CONCEPTS, annual=True, prefer_recent=True)
    assert out is not None
    assert out["value"] == 416_161_000_000
    assert "RevenueFromContractWithCustomer" in out["concept"]


@pytest.mark.asyncio
async def test_fetch_xbrl_suppresses_foreign_currency_filer() -> None:
    """BUG-037 end-to-end: a 20-F foreign private issuer (functional currency GBP)
    files XBRL in its native currency and edgartools applies NO FX. ``_fetch_xbrl``
    must NOT surface those native-GBP magnitudes as USD — both the TTM path and
    the ``latest_*`` getters suppress non-USD facts to None (so the compute layer
    falls back to the FX-normalized FMP base) and emit a warning. GBP≈1.27 is a
    near-parity currency whose un-converted value would slip under the 35%
    divergence gate, which is exactly why suppression must happen here, upstream
    of the gate.
    """
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    recent = date.today() - timedelta(days=30)
    facts = _FakeLatestFacts(
        ttm={
            # Structurally valid + recent, but reported in GBP — must be dropped.
            "Revenues": _FakeTTMMetric(
                "ifrs-full:Revenue",
                40_000_000_000.0,  # £40B, NOT FX-converted
                [(2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2")],
                recent,
                unit="GBP",
            ),
            "NetIncomeLoss": _FakeTTMMetric(
                "ifrs-full:ProfitLoss",
                5_000_000_000.0,
                [(2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2")],
                recent,
                unit="GBP",
            ),
        },
        annual={
            "ifrs-full:Revenue": _FakeFinancialFact(
                "ifrs-full:Revenue", 40_000_000_000.0, date(2025, 12, 31), unit="GBP"
            ),
            "us-gaap:NetIncomeLoss": _FakeFinancialFact(
                "us-gaap:NetIncomeLoss", 5_000_000_000.0, date(2025, 12, 31), unit="GBP"
            ),
        },
    )

    c = MagicMock()
    c.get_facts.return_value = facts
    data, warnings = p._fetch_xbrl(c)

    # No native-currency value leaks through as USD.
    assert data["ttm_revenue"] is None
    assert data["ttm_net_income"] is None
    assert data["latest_revenue"] is None
    assert data["latest_net_income"] is None
    # The suppression is surfaced honestly so the analyst knows we fell back.
    assert any("GBP" in w and "USD" in w for w in warnings)


@pytest.mark.asyncio
async def test_fetch_xbrl_periods_str_list_matches_model() -> None:
    """BUG-010: tuple periods → ``list[str]`` (e.g. "Q3 2025") matching
    ``XBRLTTMMetric.periods``, not a typed dict or repr tuple string."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    facts = _FakeLatestFacts(
        ttm={
            "NetIncomeLoss": _FakeTTMMetric(
                "us-gaap:NetIncomeLoss",
                96_995_000_000,
                [(2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2")],
                date.today() - timedelta(days=25),
            )
        },
        annual={
            "us-gaap:NetIncomeLoss": _FakeFinancialFact(
                "us-gaap:NetIncomeLoss", 96_995_000_000, date(2025, 9, 27)
            )
        },
    )

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)

    ni_ttm = data["ttm_net_income"]
    assert ni_ttm is not None
    assert ni_ttm["periods"] == ["Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"]
    # Must NOT be Python repr tuple string nor a dict.
    for period_entry in ni_ttm["periods"]:
        assert isinstance(period_entry, str)
        assert "(" not in period_entry, "period must not be a Python repr tuple string"


@pytest.mark.asyncio
async def test_fetch_xbrl_surfaces_ttm_calculated_q4_and_warning() -> None:
    """BUG-010: edgartools' ``has_calculated_q4`` (Q4 derived from FY−9M) and
    ``warning`` (gaps / thin history) must reach DataResult.warnings so the UI
    can caveat the TTM honestly, plus ``period_end`` (as_of_date) is threaded."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    as_of = date.today() - timedelta(days=20)
    facts = _FakeLatestFacts(
        ttm={
            "Revenues": _FakeTTMMetric(
                "us-gaap:Revenues",
                100.0,
                [(2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2")],
                as_of,
                has_calculated_q4=True,
                warning="Gaps detected in quarterly data.",
            )
        },
    )

    c = MagicMock()
    c.get_facts.return_value = facts
    data, warnings = p._fetch_xbrl(c)

    assert data["ttm_revenue"]["period_end"] == as_of
    assert data["ttm_revenue"]["has_calculated_q4"] is True
    assert data["ttm_revenue"]["warning"] == "Gaps detected in quarterly data."
    assert any("calculated Q4" in w for w in warnings)
    assert any("Gaps detected" in w for w in warnings)


@pytest.mark.asyncio
async def test_xbrl_concept_snapshot_net_income_dual_key() -> None:
    """xbrl_concept_snapshot splits NetIncomeLoss into :annual and :ttm keys."""
    from finrobot.engine.compute.operators.xbrl_aligned_comps import xbrl_concept_snapshot

    raw_xbrl = {
        "ttm_net_income": {
            "concept": "us-gaap:NetIncomeLoss",
            "value": 100_000_000,
            "periods": ["Q3 2025", "Q4 2025"],
        },
        # BUG-009: latest_* is now the provider's recovered-concept dict.
        "latest_net_income": {
            "concept": "us-gaap:NetIncomeLoss",
            "value": 90_000_000,
            "period_end": "2025-09-27",
            "units": "USD",
        },
    }
    snapshot = xbrl_concept_snapshot(raw_xbrl)

    # No bare us-gaap:NetIncomeLoss key — both records are disambiguated
    assert "us-gaap:NetIncomeLoss" not in snapshot, (
        "bare NetIncomeLoss key must not exist; use :annual/:ttm suffixes"
    )
    assert "us-gaap:NetIncomeLoss:ttm" in snapshot
    assert "us-gaap:NetIncomeLoss:annual" in snapshot

    ttm_entries = snapshot["us-gaap:NetIncomeLoss:ttm"]
    assert len(ttm_entries) == 1
    assert ttm_entries[0]["value"] == 100_000_000
    assert ttm_entries[0]["concept"] == "us-gaap:NetIncomeLoss:ttm"

    annual_entries = snapshot["us-gaap:NetIncomeLoss:annual"]
    assert len(annual_entries) == 1
    assert annual_entries[0]["value"] == 90_000_000
    assert annual_entries[0]["concept"] == "us-gaap:NetIncomeLoss:annual"
    # The REAL matched concept is preserved alongside the stable :annual key.
    assert annual_entries[0]["matched_concept"] == "us-gaap:NetIncomeLoss"


@pytest.mark.asyncio
async def test_fetch_xbrl_when_facts_unavailable() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    c = MagicMock()
    c.get_facts.return_value = None
    data, warnings = p._fetch_xbrl(c)
    assert data == {"facts_available": False}
    assert warnings == ["EntityFacts unavailable"]


# ---------------------------------------------------------------------------
# _fetch_proxy (DEF 14A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_proxy_returns_text_capped_at_50k() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    proxy = MagicMock()
    proxy.filing_date = date(2026, 1, 8)
    proxy.accession_no = "0001308179-26-000008"
    proxy.homepage_url = "https://sec.gov/..."
    proxy.text.return_value = "A" * 100_000  # 100 KB; adapter must cap
    c = MagicMock()
    c.latest.return_value = proxy
    data, _ = p._fetch_proxy(c)
    assert data["accession_no"] == "0001308179-26-000008"
    assert len(data["text"]) == 50_000


@pytest.mark.asyncio
async def test_fetch_proxy_returns_none_when_no_filing() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    c = MagicMock()
    c.latest.return_value = None
    data, warnings = p._fetch_proxy(c)
    assert data == {"proxy": None}
    assert warnings == ["No DEF 14A found"]


# ---------------------------------------------------------------------------
# fetch (top-level async wrapping) — confirms ProviderError translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_translates_edgar_exception_to_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any underlying _ADAPTER_CATCH error becomes ProviderError, not 500."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")

    # Force the dispatcher to raise an AttributeError (e.g. edgartools schema drift)
    def _broken(*args: Any, **kwargs: Any) -> Any:
        raise AttributeError("edgartools API moved")

    monkeypatch.setattr(p, "_fetch_sync", _broken)
    with pytest.raises(ProviderError) as exc:
        await p.fetch("AAPL", DataType.FILINGS_10K)
    assert "edgartools" in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_returns_well_formed_data_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    monkeypatch.setattr(
        p,
        "_fetch_sync",
        lambda ticker, data_type, kwargs: ({"foo": "bar"}, ["one warning"]),
    )
    result = await p.fetch("aapl", DataType.FILINGS_10K)
    assert result.ticker == "AAPL"
    assert result.provider == "edgar_tools"
    assert result.data == {"foo": "bar"}
    assert result.warnings == ["one warning"]
    assert result.timestamp.tzinfo is not None  # UTC tz-aware


# ---------------------------------------------------------------------------
# TTM concept selection + validity gate (ADR-0008)
# ---------------------------------------------------------------------------

from datetime import date as _date  # noqa: E402

from finrobot.engine.data.providers.edgar_provider import (  # noqa: E402
    _TTM_REVENUE_CONCEPTS,
    _select_recent_ttm,
    _validate_ttm_periods,
)


class _FakePeriodFact:
    def __init__(self, period_end: _date) -> None:
        self.period_end = period_end


class _FakeTTMMetric:
    """Mimics edgartools' TTMMetric: concept, value, periods, as_of_date + caveats.

    ``as_of_date`` is the TTM window's latest-quarter ``period_end`` (the
    calculator sets it to ``ttm_quarters[-1].period_end``); the provider ranks
    candidates and gates recency on it (BUG-010). ``has_calculated_q4`` / ``warning``
    carry edgartools' quarterization quality caveats.
    """

    def __init__(
        self,
        concept: str,
        value: float,
        periods: list[tuple[int, str]],
        latest_end: _date,
        *,
        has_calculated_q4: bool = False,
        warning: str | None = None,
        unit: str = "USD",
    ) -> None:
        self.concept = concept
        self.value = value
        self.periods = periods
        self.as_of_date = latest_end
        self.period_facts = [_FakePeriodFact(latest_end)]
        self.has_calculated_q4 = has_calculated_q4
        self.warning = warning
        self.unit = unit


class _FakeFacts:
    """Fake EntityFacts whose get_ttm(concept) serves canned metrics; absent
    concepts raise KeyError like the real API."""

    def __init__(self, by_concept: dict[str, _FakeTTMMetric]) -> None:
        self._by_concept = by_concept

    def get_ttm(self, concept: str) -> _FakeTTMMetric:
        if concept not in self._by_concept:
            raise KeyError(concept)
        return self._by_concept[concept]


class TestValidateTTMPeriods:
    def test_accepts_four_consecutive_distinct_quarters(self) -> None:
        assert _validate_ttm_periods([(2026, "Q2"), (2026, "Q3"), (2026, "Q4"), (2027, "Q1")])

    def test_rejects_repeated_annual_frame(self) -> None:
        # NVDA's frozen dead concept: same FY period four times.
        assert not _validate_ttm_periods([(2020, "FY"), (2020, "FY"), (2020, "FY"), (2020, "FY")])

    def test_rejects_cumulative_ytd_frame(self) -> None:
        # An H1 (year-to-date) frame leaking in would double-count.
        assert not _validate_ttm_periods([(2026, "Q1"), (2026, "H1"), (2026, "Q3"), (2026, "Q4")])

    def test_rejects_gap_in_quarters(self) -> None:
        assert not _validate_ttm_periods([(2026, "Q1"), (2026, "Q2"), (2026, "Q4"), (2027, "Q1")])

    def test_rejects_wrong_count(self) -> None:
        assert not _validate_ttm_periods([(2026, "Q1"), (2026, "Q2"), (2026, "Q3")])

    def test_rejects_empty(self) -> None:
        assert not _validate_ttm_periods([])
        assert not _validate_ttm_periods(None)


class TestSelectRecentTTM:
    def test_picks_live_concept_over_frozen_one(self) -> None:
        """The NVDA bug: a dead concept with stale facts must NOT win over the
        live concept just because it appears first in the candidate list."""
        facts = _FakeFacts(
            {
                # First in _TTM_REVENUE_CONCEPTS, but frozen at FY2020 — degenerate.
                "RevenueFromContractWithCustomerExcludingAssessedTax": _FakeTTMMetric(
                    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                    10_918_000_000.0,
                    [(2020, "FY"), (2020, "FY"), (2020, "FY"), (2020, "FY")],
                    _date(2020, 1, 26),
                ),
                # Live concept with recent, valid quarters.
                "Revenues": _FakeTTMMetric(
                    "us-gaap:Revenues",
                    253_491_000_000.0,
                    [(2026, "Q2"), (2026, "Q3"), (2026, "Q4"), (2027, "Q1")],
                    _date(2026, 4, 26),
                ),
            }
        )
        out = _select_recent_ttm(facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1))
        assert out is not None
        assert out["concept"] == "us-gaap:Revenues"
        assert out["value"] == 253_491_000_000.0

    def test_returns_none_when_only_stale_concept_present(self) -> None:
        """All candidates stale/degenerate → None, so the compute layer falls
        back to the FMP TTM."""
        facts = _FakeFacts(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _FakeTTMMetric(
                    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                    10_918_000_000.0,
                    [(2020, "FY"), (2020, "FY"), (2020, "FY"), (2020, "FY")],
                    _date(2020, 1, 26),
                ),
            }
        )
        out = _select_recent_ttm(facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1))
        assert out is None

    def test_rejects_recent_but_structurally_invalid_window(self) -> None:
        """A recent concept whose window has a gap is rejected (returns None)."""
        facts = _FakeFacts(
            {
                "Revenues": _FakeTTMMetric(
                    "us-gaap:Revenues",
                    100.0,
                    [(2026, "Q1"), (2026, "Q2"), (2026, "Q4"), (2027, "Q1")],
                    _date(2026, 4, 26),
                ),
            }
        )
        out = _select_recent_ttm(facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1))
        assert out is None

    def test_suppresses_foreign_currency_ttm_and_warns(self) -> None:
        """BUG-037: a 20-F foreign private issuer reports TTM revenue in its
        functional currency (EUR here) — edgartools returns the native magnitude
        with a non-USD ``unit`` and applies no FX. ``_select_recent_ttm`` must
        refuse it (→ None, so the compute layer falls back to the FX-normalized
        FMP TTM) and surface a warning, rather than letting a near-parity EUR
        value (EUR≈1.08) sail through the 35% divergence gate as if it were USD.
        """
        warnings: list[str] = []
        facts = _FakeFacts(
            {
                # Structurally valid + recent — ONLY the non-USD unit must reject it.
                "Revenues": _FakeTTMMetric(
                    "ifrs-full:Revenue",
                    50_000_000_000.0,  # €50B reported, NOT FX-converted
                    [(2026, "Q1"), (2026, "Q2"), (2026, "Q3"), (2026, "Q4")],
                    _date(2026, 4, 26),
                    unit="EUR",
                ),
            }
        )
        out = _select_recent_ttm(
            facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1), warnings=warnings
        )
        assert out is None
        assert any("EUR" in w and "USD" in w for w in warnings)

    def test_keeps_usd_ttm(self) -> None:
        """The USD fast path is unaffected by the BUG-037 currency guard."""
        warnings: list[str] = []
        facts = _FakeFacts(
            {
                "Revenues": _FakeTTMMetric(
                    "us-gaap:Revenues",
                    253_491_000_000.0,
                    [(2026, "Q1"), (2026, "Q2"), (2026, "Q3"), (2026, "Q4")],
                    _date(2026, 4, 26),
                    unit="USD",
                ),
            }
        )
        out = _select_recent_ttm(
            facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1), warnings=warnings
        )
        assert out is not None
        assert out["value"] == 253_491_000_000.0
        assert warnings == []

    def test_revenue_prefers_total_over_asc606_subset_same_period(self) -> None:
        """Financial-issuer revenue-subset bug (2026-06-29): an insurer reports
        BOTH total ``Revenues`` (77B) and the ASC-606 contract-revenue subset
        (2.4B) as a structurally valid TTM at the SAME latest quarter. With totals
        ranked ahead of the subset in _TTM_REVENUE_CONCEPTS, the strict-``>`` tie
        keeps the total — the subset must never win (was 31× understated)."""
        pe = _date(2026, 3, 31)
        quarters = [(2025, "Q2"), (2025, "Q3"), (2025, "Q4"), (2026, "Q1")]
        facts = _FakeFacts(
            {
                "Revenues": _FakeTTMMetric("us-gaap:Revenues", 77_000_000_000.0, quarters, pe),
                "RevenueFromContractWithCustomerExcludingAssessedTax": _FakeTTMMetric(
                    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                    2_436_000_000.0,
                    quarters,
                    pe,
                ),
            }
        )
        out = _select_recent_ttm(facts, _TTM_REVENUE_CONCEPTS, today=_date(2026, 6, 1))
        assert out is not None
        assert out["concept"] == "us-gaap:Revenues"
        assert out["value"] == 77_000_000_000.0


# ---------------------------------------------------------------------------
# Schedule 13D/13G (5%+ beneficial owners)
# ---------------------------------------------------------------------------


def _sched13_helpers():
    from finrobot.engine.data.providers.edgar_provider import (
        _issuer_token,
        _schedule13_pct,
        _schedule13_shares,
    )

    return _issuer_token, _schedule13_shares, _schedule13_pct


def test_schedule13_shares_parses_amount_beneficially_owned() -> None:
    _, shares, _ = _sched13_helpers()
    # FMR LLC NVDA 13G/A 2024-11-12 Item 4(a) prose form (probe-verified text).
    txt = "Item 4. Ownership\n(a) Amount Beneficially Owned: 998,190,803\n(b) Percent of Class: 4.069%"
    assert shares(txt) == 998_190_803
    # "Aggregate Amount Beneficially Owned" variant also matches.
    assert shares("Aggregate Amount Beneficially Owned 12,345,678 shares") == 12_345_678
    # No share figure → None (caller must NOT fabricate a 0).
    assert shares("No ownership table here") is None
    # A bare item number must not match (needs >=4 digits).
    assert shares("Item 4. Ownership (a) 123") is None


def test_schedule13_shares_binds_row9_aggregate_not_row7_subtotal() -> None:
    """REGRESSION: the FIRST loose "Amount Beneficially Owned" must NOT win.

    Modeled on the GameStop SC 13D/A (acc 0000921895-24-001394) extracted layout,
    where the cover-table left-margin caption ("...AMOUNT BENEFICIALLY OWNED BY
    EACH REPORTING PERSON WITH") is split line-by-line and the Row-7 SOLE VOTING
    POWER subtotal (36,847,842 in that real filing) renders adjacent to the
    caption words. The OLD parser bound that subtotal; the parser must anchor on
    the Row-9 "Aggregate Amount Beneficially Owned" label and return the true
    aggregate instead.
    """
    _, shares, _ = _sched13_helpers()
    # First loose "AMOUNT ... BENEFICIALLY OWNED" abuts the Row-7 SOLE VOTING
    # subtotal 36,847,842; the real aggregate (Row 9) is the DIFFERENT 11,200,000.
    cover = (
        "   7   SOLE VOTING POWER\n"
        " AMOUNT\n"
        " BENEFICIALLY OWNED   36,847,842\n"
        " BY EACH\n"
        "   8   SHARED VOTING POWER\n"
        " REPORTING   - 0 -\n"
        " PERSON WITH\n"
        "   9   AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON\n"
        "                                  11,200,000\n"
        "  11   PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (9)   2.6%\n"
    )
    assert shares(cover) == 11_200_000  # Row-9 aggregate, NOT the 36,847,842 subtotal


def test_schedule13_shares_inline_table_real_layouts() -> None:
    """Row-9 aggregate from the inline cover-table layouts, against real filings.

    - Apple/Vanguard SC 13G/A 2024-02-13 (acc 0001104659-24-020009): Rows 5-8
      carry voting/dispositive subtotals; Row 9 = 1,317,966,471.
    - Warner Bros. Discovery SC 13G/A 2024-01-25 (acc 0000093751-24-000272):
      filer spells the label "AGGREGATED AMOUNT" (with a D) — must still match.
    """
    _, shares, _ = _sched13_helpers()
    aapl_vanguard = (
        "7. SOLE DISPOSITIVE POWER\n1,254,220,941\n"
        "8. SHARED DISPOSITIVE POWER\n63,745,530\n"
        "9. AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON\n1,317,966,471\n"
        "10. CHECK BOX IF THE AGGREGATE AMOUNT IN ROW (9) EXCLUDES CERTAIN SHARES\nN/A\n"
    )
    assert shares(aapl_vanguard) == 1_317_966_471
    wbd_aggregated = (
        "8. SOLE DISPOSITIVE POWER 135,675,989 "
        "9. AGGREGATED AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON 136,648,651 "
        "10. CHECK BOX"
    )
    assert shares(wbd_aggregated) == 136_648_651


def test_schedule13_shares_vertical_label_does_not_bind_cusip() -> None:
    """REGRESSION: a Row-9 label with no inline number must NOT bind the CUSIP.

    Apple SC 13G/A 2024-02-14 (acc 0001193125-24-036431) renders a vertical-label
    cover table: Row 9's label has no adjacent number (values sit in a stripped
    column), and the next ≥4-digit token after the label is the CUSIP 037833100.
    The parser must NOT mistake that CUSIP for a share count — with no Item 4(a)
    prose aggregate, it must return None rather than fabricate.
    """
    _, shares, _ = _sched13_helpers()
    vertical = (
        "AGGREGATE AMOUNT BENEFICIALLY OWNED BY 10 CHECK BOX IF THE AGGREGATE "
        "AMOUNT IN ROW 11 PERCENT OF CLASS REPRESENTED BY AMOUNT IN 12 TYPE OF "
        "CUSIP No. 037833100 13G Page 3 of 48 Pages"
    )
    assert shares(vertical) is None


def test_schedule13_pct_parses_percent_of_class() -> None:
    _, _, pct = _sched13_helpers()
    assert pct("(b) Percent of Class: 4.069%") == 4.069
    assert pct("Percent of Class 7.3 %") == 7.3
    assert pct("no percent here") is None
    # Out-of-range guard.
    assert pct("Percent of Class: 250%") is None


def test_issuer_token_strips_legal_suffixes() -> None:
    token, _, _ = _sched13_helpers()
    assert token("NVIDIA CORP") == "nvidia"
    assert token("FMR LLC") == "fmr"
    assert token("The Vanguard Group, Inc.") == "vanguard"


def test_ceo_cert_attachment_rank_matches_ceo_leg_variants() -> None:
    """The CEO Section-302 cert (Exhibit 31.1) leg — real naming variants probed
    2026-07-09: "EX-31.1" (most), "EX-31.01" (GOOGL, leading zero), "EX-31.A"
    (DIS, letter suffix + explicit officer description)."""
    from finrobot.engine.data.providers.edgar_provider import _ceo_cert_attachment_rank

    # Numeric ".1", zero-padded ".01", filename fallback, and letter ".A".
    assert _ceo_cert_attachment_rank("EX-31.1", "EX-31.1", "a-ex-311.htm") is not None
    assert _ceo_cert_attachment_rank("EX-31.01", "EX-31.01", "googexhibit3101.htm") is not None
    assert _ceo_cert_attachment_rank("", "", "wferb-ex311.htm") is not None
    # Description explicitly names the CEO → best rank (0), beats a bare ".1".
    ceo_desc = _ceo_cert_attachment_rank(
        "EX-31.A", "SECTION 302 CERTIFICATION OF CHIEF EXECUTIVE OFFICER", "ex31a.htm"
    )
    assert ceo_desc == 0
    assert _ceo_cert_attachment_rank("EX-31.1", "EX-31.1", "a-ex-311.htm") > ceo_desc


def test_ceo_cert_attachment_rank_rejects_cfo_and_906() -> None:
    """Must NEVER select the CFO leg (Ex-31.2/.02/.B) or a Section-906 cert
    (Ex-32.x, which may be a single COMBINED CEO+CFO document) — a wrong signer
    is worse than falling back."""
    from finrobot.engine.data.providers.edgar_provider import _ceo_cert_attachment_rank

    # CFO leg of the 302 cert.
    assert _ceo_cert_attachment_rank("EX-31.2", "EX-31.2", "a-ex-312.htm") is None
    assert _ceo_cert_attachment_rank("EX-31.02", "EX-31.02", "googexhibit3102.htm") is None
    assert (
        _ceo_cert_attachment_rank(
            "EX-31.B", "SECTION 302 CERTIFICATION OF CHIEF FINANCIAL OFFICER", "ex31b.htm"
        )
        is None
    )
    # A ".1" leg whose description says CFO is still rejected (description wins).
    assert (
        _ceo_cert_attachment_rank("EX-31.1", "CERTIFICATION OF CHIEF FINANCIAL OFFICER", "x.htm")
        is None
    )
    # Section-906 certs (Ex-32.x) — excluded even when the description says CEO.
    assert _ceo_cert_attachment_rank("EX-32.1", "EX-32.1", "a-ex-321.htm") is None
    assert (
        _ceo_cert_attachment_rank(
            "EX-32.A", "SECTION 906 CERTIFICATION OF CHIEF EXECUTIVE OFFICER", "ex32a.htm"
        )
        is None
    )
    # Unrelated exhibits.
    assert _ceo_cert_attachment_rank("EX-10.1", "EX-10.1", "ex-101.htm") is None
    assert _ceo_cert_attachment_rank("10-Q", "10-Q", "ko-20260403.htm") is None


def _mock_sched13_filing(form: str, fdate: date, acc: str, filer: str, cik: str | None, text: str):
    f = MagicMock()
    f.form = form
    f.filing_date = fdate
    f.accession_no = acc
    f.homepage_url = "https://sec.gov/..."
    f.text.return_value = text
    ci = MagicMock()
    ci.name = filer
    ci.cik = cik
    filer_obj = MagicMock()
    filer_obj.company_information = ci
    header = MagicMock()
    header.filers = [filer_obj]
    f.header = header
    return f


def test_fetch_schedule13_parses_dedups_and_skips_self_filing() -> None:
    from finrobot.engine.data.providers.edgar_provider import EdgarToolsProvider

    p = EdgarToolsProvider("Jane Doe jane@example.com")
    cover = "(a) Amount Beneficially Owned: 998,190,803\n(b) Percent of Class: 4.069%"
    older_cover = "(a) Amount Beneficially Owned: 900,000,000\n(b) Percent of Class: 3.9%"
    no_shares = "Item 1. cover with no ownership amount"
    filings = [
        # newest FMR amendment (kept)
        _mock_sched13_filing("SC 13G/A", date(2024, 11, 12), "a1", "FMR LLC", "315066", cover),
        # older FMR amendment (deduped away — same filer)
        _mock_sched13_filing("SC 13G/A", date(2024, 2, 13), "a2", "FMR LLC", "315066", older_cover),
        # self-filing: filer == subject (skipped)
        _mock_sched13_filing("SC 13G", date(2024, 7, 18), "a3", "NVIDIA CORP", "1045810", cover),
        # BlackRock (kept)
        _mock_sched13_filing("SC 13D", date(2024, 1, 26), "a4", "BlackRock Inc.", "1364742", cover),
        # filing with no parseable share count (skipped — no fabricated 0)
        _mock_sched13_filing(
            "SC 13G", date(2023, 6, 1), "a5", "State Street Corp", "93751", no_shares
        ),
    ]
    c = MagicMock()
    c.cik = "1045810"  # NVDA
    c.name = "NVIDIA CORP"
    c.get_filings.return_value = filings

    data, warnings = p._fetch_schedule13(c, limit=8)
    alerts = data["alerts"]
    names = [a["filer_name"] for a in alerts]
    assert names == ["FMR LLC", "BlackRock Inc."]  # deduped, self + no-shares skipped
    assert alerts[0]["shares"] == 998_190_803
    assert alerts[0]["pct_of_class"] == 4.069
    assert alerts[0]["accession_no"] == "a1"  # newest FMR kept
    assert alerts[1]["schedule_type"] == "13D"  # BlackRock SC 13D → activist


# ---------------------------------------------------------------------------
# build_rag_chunks — section-aware 10-K chunking.
#
# The old path merged every section then chunked the blob with a bare
# "10-K/<date>" source, so chunk citations were guesswork and risk chunks
# straddled section boundaries. build_rag_chunks chunks EACH section so every
# chunk's source carries its section title — which is what run_qa cites.
# ---------------------------------------------------------------------------


class TestBuildRagChunks:
    def _sections(self) -> list[dict[str, Any]]:
        return [
            {"title": "Item 1A — Risk Factors", "text": " ".join(f"risk{i}" for i in range(120))},
            {"title": "Item 7 — MD&A", "text": " ".join(f"mdna{i}" for i in range(120))},
            {"title": "Item 9 — Empty", "text": "   "},  # whitespace-only → skipped
        ]

    def test_source_carries_section_title(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import build_rag_chunks

        chunks = build_rag_chunks(self._sections(), "2025-10-31")
        assert chunks, "expected chunks from non-empty sections"
        for c in chunks:
            assert c["source"].startswith("10-K/2025-10-31")
        risk_sources = {c["source"] for c in chunks if "risk0" in c["text"]}
        assert any("Item 1A — Risk Factors" in s for s in risk_sources)
        mdna_sources = {c["source"] for c in chunks if "mdna0" in c["text"]}
        assert any("Item 7 — MD&A" in s for s in mdna_sources)

    def test_chunk_index_is_unique_and_sequential(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import build_rag_chunks

        chunks = build_rag_chunks(self._sections(), "2025-10-31")
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))  # globally re-numbered, no dupes

    def test_empty_sections_skipped_and_chunks_serializable(self) -> None:
        import json

        from finrobot.engine.data.providers.edgar_provider import build_rag_chunks

        chunks = build_rag_chunks(self._sections(), "2025-10-31")
        # the whitespace-only "Item 9" section contributes nothing
        assert not any("Item 9" in c["source"] for c in chunks)
        json.dumps(chunks)  # must be JSON-serializable (cache contract)


# ---------------------------------------------------------------------------
# 13F stale-quarter warning (_fetch_13f_sync)
# ---------------------------------------------------------------------------


class TestFetch13FStaleWarning:
    """The 13F cache serves the newest quarter it HAS, which silently lags
    once the next quarter's 13F-HR deadline (45 days after quarter end)
    passes. Consumers must get a stale warning, never a silent old quarter."""

    @staticmethod
    def _wire(monkeypatch: pytest.MonkeyPatch, holders: list[dict], status: dict) -> None:
        from contextlib import asynccontextmanager

        from finrobot.engine.data import sec_holdings_cache as cache_mod

        async def _holders(*_a: Any, **_k: Any) -> list[dict]:
            return holders

        async def _status(*_a: Any, **_k: Any) -> dict:
            return status

        # _fetch_13f_sync scopes its I/O to an ephemeral connection (BUG-082
        # sibling); stub it out so the test never opens the real home-dir DB.
        @asynccontextmanager
        async def _no_conn() -> Any:
            yield None

        monkeypatch.setattr(cache_mod, "lookup_holders_for_ticker", _holders)
        monkeypatch.setattr(cache_mod, "cache_status", _status)
        monkeypatch.setattr(cache_mod, "ephemeral_connection", _no_conn)

    def test_stale_cache_emits_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(
            monkeypatch,
            holders=[{"period_end": "2025-09-30", "holder_name": "X"}],
            status={
                "populated": True,
                "row_count": 10,
                "latest_period_end": "2025-09-30",
                "distinct_tickers": 1,
                "expected_period_end": "2026-03-31",
                "stale": True,
            },
        )
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        _payload, warnings = p._fetch_13f_sync("NVDA")
        joined = " ".join(warnings)
        assert "stale" in joined.lower()
        assert "2025-09-30" in joined and "2026-03-31" in joined

    def test_fresh_cache_no_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(
            monkeypatch,
            holders=[{"period_end": "2026-03-31", "holder_name": "X"}],
            status={
                "populated": True,
                "row_count": 10,
                "latest_period_end": "2026-03-31",
                "distinct_tickers": 1,
                "expected_period_end": "2026-03-31",
                "stale": False,
            },
        )
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        _payload, warnings = p._fetch_13f_sync("NVDA")
        assert warnings == []

    def test_ticker_older_than_cache_global_latest_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cache globally fresh, but THIS ticker's newest rows are an old
        quarter (issuer dropped by filers / CUSIP churn) → still stale."""
        self._wire(
            monkeypatch,
            holders=[{"period_end": "2025-12-31", "holder_name": "X"}],
            status={
                "populated": True,
                "row_count": 10,
                "latest_period_end": "2026-03-31",
                "distinct_tickers": 1,
                "expected_period_end": "2026-03-31",
                "stale": False,
            },
        )
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        _payload, warnings = p._fetch_13f_sync("NVDA")
        assert any("stale" in w.lower() for w in warnings)

    def test_unbuilt_cache_keeps_not_built_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(
            monkeypatch,
            holders=[],
            status={
                "populated": False,
                "row_count": 0,
                "latest_period_end": None,
                "distinct_tickers": 0,
                "expected_period_end": "2026-03-31",
                "stale": False,
            },
        )
        p = EdgarToolsProvider("Jane Doe jane@example.com")
        _payload, warnings = p._fetch_13f_sync("NVDA")
        assert len(warnings) == 1
        assert "not built" in warnings[0]


# ---------------------------------------------------------------------------
# SEC XBRL companyfacts deep annual history (no network — pure facts→dict)
# ---------------------------------------------------------------------------


def _fact(
    *, start: str, end: str, val: float, fy: int, fp: str = "FY", form: str = "10-K", filed: str
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "val": val,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
    }


def _facts_with(concept: str, items: list[dict[str, Any]], unit: str = "USD") -> dict[str, Any]:
    return {"facts": {"us-gaap": {concept: {"units": {unit: items}}}}}


class TestCompanyfactsAnnualSeries:
    """The deep-history extraction that feeds the through-cycle DCF window."""

    def test_keys_by_period_end_not_filing_fy(self) -> None:
        """fy-bug guard: a comparative tagged with a LATER filing's fy must land
        on its OWN period-end year, never the filing fy. MU's FY2018 peak appears
        in the FY2019 10-K tagged fy=2019; keying by fy would mislabel it.
        """
        from finrobot.engine.data.providers.edgar_provider import _companyfacts_annual_series

        items = [
            # The real FY2018 fact filed in the 2018 10-K (fy=2018).
            _fact(start="2017-09-01", end="2018-08-30", val=30_391, fy=2018, filed="2018-10-01"),
            # The SAME period restated as a comparative in the FY2019 10-K (fy=2019).
            _fact(start="2017-09-01", end="2018-08-30", val=30_391, fy=2019, filed="2019-10-01"),
            # FY2019 itself, filed 2019 (fy=2019).
            _fact(start="2018-08-31", end="2019-08-29", val=23_406, fy=2019, filed="2019-10-01"),
        ]
        series = _companyfacts_annual_series(
            _facts_with("RevenueFromContractWithCustomerExcludingAssessedTax", items),
            ("RevenueFromContractWithCustomerExcludingAssessedTax",),
        )
        # Keyed by period-END year: 2018 and 2019 — NOT 2019 twice.
        assert set(series.keys()) == {2018, 2019}
        assert series[2018] == 30_391
        assert series[2019] == 23_406

    def test_latest_filed_comparative_wins(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _companyfacts_annual_series

        items = [
            _fact(start="2022-01-01", end="2022-12-31", val=100, fy=2022, filed="2023-02-01"),
            # A later 10-K restates the same FY with a corrected value.
            _fact(start="2022-01-01", end="2022-12-31", val=110, fy=2023, filed="2024-02-01"),
        ]
        series = _companyfacts_annual_series(_facts_with("Revenues", items), ("Revenues",))
        assert series[2022] == 110  # latest filed wins

    def test_skips_non_usd_quarterly_and_non_10k(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _companyfacts_annual_series

        concept = "Revenues"
        node_items = [
            # quarterly (≈90 days) — too short for an annual flow
            _fact(start="2023-01-01", end="2023-03-31", val=25, fy=2023, filed="2023-05-01"),
            # 10-Q form — not an annual report
            _fact(
                start="2023-01-01",
                end="2023-12-31",
                val=999,
                fy=2023,
                form="10-Q",
                filed="2024-01-15",
            ),
            # the real annual 10-K fact
            _fact(start="2023-01-01", end="2023-12-31", val=100, fy=2023, filed="2024-02-01"),
        ]
        facts = _facts_with(concept, node_items)
        series = _companyfacts_annual_series(facts, (concept,))
        assert series == {2023: 100}

        # Non-USD unit is ignored entirely.
        eur = _facts_with(
            concept,
            [_fact(start="2023-01-01", end="2023-12-31", val=100, fy=2023, filed="2024-02-01")],
            unit="EUR",
        )
        assert _companyfacts_annual_series(eur, (concept,)) == {}

    def test_concept_fallback_first_nonempty_wins(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _companyfacts_annual_series

        # Primary concept absent; second candidate present.
        facts = _facts_with(
            "SalesRevenueNet",
            [_fact(start="2020-01-01", end="2020-12-31", val=50, fy=2020, filed="2021-02-01")],
        )
        series = _companyfacts_annual_series(
            facts,
            ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
        )
        assert series == {2020: 50}

    def test_revenue_prefers_total_over_asc606_subset_same_year(self) -> None:
        """Financial-issuer revenue-subset bug (2026-06-29): an insurer reports
        BOTH total ``Revenues`` and the ASC-606 contract-revenue subset for the
        SAME fiscal years. prefer_total_across_concepts surfaces the total (77B),
        never the fee-only subset (2.4B) the old first-concept-wins latched."""
        from finrobot.engine.data.providers.edgar_provider import (
            _HIST_REVENUE_CONCEPTS,
            _companyfacts_annual_series,
        )

        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                _fact(
                                    start="2024-01-01",
                                    end="2024-12-31",
                                    val=70_000,
                                    fy=2024,
                                    filed="2025-02-19",
                                ),  # noqa: E501
                                _fact(
                                    start="2025-01-01",
                                    end="2025-12-31",
                                    val=77_084,
                                    fy=2025,
                                    filed="2026-02-19",
                                ),  # noqa: E501
                            ]
                        }
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                _fact(
                                    start="2024-01-01",
                                    end="2024-12-31",
                                    val=2_300,
                                    fy=2024,
                                    filed="2025-02-19",
                                ),  # noqa: E501
                                _fact(
                                    start="2025-01-01",
                                    end="2025-12-31",
                                    val=2_436,
                                    fy=2025,
                                    filed="2026-02-19",
                                ),  # noqa: E501
                            ]
                        }
                    },
                }
            }
        }
        series = _companyfacts_annual_series(
            facts, _HIST_REVENUE_CONCEPTS, prefer_total_across_concepts=True
        )
        assert series == {2024: 70_000, 2025: 77_084}  # totals, NOT the 2.4B subset

    def test_revenue_mixes_total_early_years_and_asc606_recent_years(self) -> None:
        """AAPL counter-case: ``Revenues`` froze at FY2018 (265B); live revenue is
        the ASC-606 concept from FY2019 (416B by FY2025). The total concept owns
        the years it reports; the subset fills ONLY the later years totals are
        missing — one consistent total series, never a regression to stale 2018."""
        from finrobot.engine.data.providers.edgar_provider import (
            _HIST_REVENUE_CONCEPTS,
            _companyfacts_annual_series,
        )

        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                _fact(
                                    start="2017-10-01",
                                    end="2018-09-29",
                                    val=265_595,
                                    fy=2018,
                                    filed="2018-11-05",
                                ),  # noqa: E501
                            ]
                        }
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                _fact(
                                    start="2024-10-01",
                                    end="2025-09-27",
                                    val=416_161,
                                    fy=2025,
                                    filed="2025-11-01",
                                ),  # noqa: E501
                            ]
                        }
                    },
                }
            }
        }
        series = _companyfacts_annual_series(
            facts, _HIST_REVENUE_CONCEPTS, prefer_total_across_concepts=True
        )
        assert series == {2018: 265_595, 2025: 416_161}


class TestCompanyfactsPointSeries:
    """EPS instant/point series — keyed by period-end FY, 10-K FY facts only.
    Unlike the annual-flow series it accepts true instants (no start) yet still
    rejects sub-annual duration facts (a quarterly EPS frame)."""

    EPS = "EarningsPerShareBasic"

    def _series(self, items: list[dict[str, Any]], concepts: tuple[str, ...] = (EPS,)):
        from finrobot.engine.data.providers.edgar_provider import _companyfacts_point_series

        return _companyfacts_point_series(_facts_with(self.EPS, items), concepts)

    def test_full_year_duration_eps_kept_by_period_end(self) -> None:
        items = [_fact(start="2023-01-01", end="2023-12-31", val=5.25, fy=2023, filed="2024-02-01")]
        assert self._series(items) == {2023: 5.25}

    def test_instant_fact_without_start_accepted(self) -> None:
        """A point-in-time fact (no start key) has no duration to validate."""
        items = [
            {
                "end": "2022-12-31",
                "val": 3.10,
                "fy": 2022,
                "fp": "FY",
                "form": "10-K",
                "filed": "2023-02-01",
            }
        ]
        assert self._series(items) == {2022: 3.10}

    def test_sub_annual_duration_eps_skipped(self) -> None:
        """A ~90-day (quarterly) EPS frame must not pollute the annual point."""
        items = [
            _fact(
                start="2023-07-01", end="2023-09-30", val=1.1, fy=2023, fp="Q3", filed="2023-11-01"
            ),
            _fact(start="2023-01-01", end="2023-12-31", val=4.4, fy=2023, filed="2024-02-01"),
        ]
        assert self._series(items) == {2023: 4.4}

    def test_non_fy_period_skipped(self) -> None:
        items = [
            {
                "end": "2023-12-31",
                "val": 9.9,
                "fy": 2023,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-02-01",
            },
            _fact(start="2023-01-01", end="2023-12-31", val=4.4, fy=2023, filed="2024-02-01"),
        ]
        assert self._series(items) == {2023: 4.4}

    def test_non_10k_form_skipped_but_10ka_kept(self) -> None:
        items = [
            _fact(
                start="2023-01-01",
                end="2023-12-31",
                val=1.0,
                fy=2023,
                form="10-Q",
                filed="2024-01-15",
            ),
            _fact(
                start="2021-01-01",
                end="2021-12-31",
                val=2.0,
                fy=2021,
                form="10-K/A",
                filed="2022-03-01",
            ),
        ]
        assert self._series(items) == {2021: 2.0}

    def test_latest_filed_wins_for_same_year(self) -> None:
        items = [
            _fact(start="2022-01-01", end="2022-12-31", val=3.0, fy=2022, filed="2023-02-01"),
            _fact(start="2022-01-01", end="2022-12-31", val=3.3, fy=2023, filed="2024-02-01"),
        ]
        assert self._series(items) == {2022: 3.3}

    def test_missing_val_or_end_skipped(self) -> None:
        items = [
            {
                "end": "2023-12-31",
                "val": None,
                "fy": 2023,
                "fp": "FY",
                "form": "10-K",
                "filed": "2024-02-01",
            },
            {"val": 5.0, "fy": 2022, "fp": "FY", "form": "10-K", "filed": "2023-02-01"},
            _fact(start="2021-01-01", end="2021-12-31", val=2.0, fy=2021, filed="2022-02-01"),
        ]
        assert self._series(items) == {2021: 2.0}

    def test_unparseable_end_date_skipped(self) -> None:
        items = [
            {
                "end": "not-a-date",
                "val": 5.0,
                "fy": 2023,
                "fp": "FY",
                "form": "10-K",
                "filed": "2024-02-01",
            },
            _fact(start="2021-01-01", end="2021-12-31", val=2.0, fy=2021, filed="2022-02-01"),
        ]
        assert self._series(items) == {2021: 2.0}

    def test_concept_fallback_first_nonempty_wins(self) -> None:
        items = [_fact(start="2020-01-01", end="2020-12-31", val=1.5, fy=2020, filed="2021-02-01")]
        # Primary concept absent (facts only carry EarningsPerShareBasic); the
        # function tries each concept and stops at the first with data.
        assert self._series(items, ("EarningsPerShareDiluted", self.EPS)) == {2020: 1.5}

    def test_empty_when_no_concept_present(self) -> None:
        items = [_fact(start="2020-01-01", end="2020-12-31", val=1.5, fy=2020, filed="2021-02-01")]
        assert self._series(items, ("EarningsPerShareDiluted",)) == {}


class TestBuildSecYearlyFinancials:
    """The newest-first per-year dict the provider-agnostic extractor consumes."""

    def _multi_concept_facts(self) -> dict[str, Any]:
        usgaap: dict[str, Any] = {}

        def add(concept: str, by_year: dict[int, float], unit: str = "USD") -> None:
            items = [
                _fact(
                    start=f"{y - 1}-12-31",
                    end=f"{y}-12-31",
                    val=v,
                    fy=y,
                    filed=f"{y + 1}-02-01",
                )
                for y, v in by_year.items()
            ]
            usgaap[concept] = {"units": {unit: items}}

        add("Revenues", {2021: 1000, 2022: 1200, 2023: 800})
        add("OperatingIncomeLoss", {2021: 200, 2022: 300, 2023: -100})
        add("NetIncomeLoss", {2021: 150, 2022: 250, 2023: -120})
        # capex reported as positive outflow magnitude by SEC
        add("PaymentsToAcquirePropertyPlantAndEquipment", {2021: 90, 2022: 110, 2023: 70})
        add("DepreciationDepletionAndAmortization", {2021: 60, 2022: 70, 2023: 80})
        return {"facts": {"us-gaap": usgaap}}

    def test_shape_keys_match_extractor_contract(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _build_sec_yearly_financials

        rows = _build_sec_yearly_financials(self._multi_concept_facts(), 10)
        required = {
            "fiscal_year",
            "revenue",
            "operating_income",
            "operating_margin",
            "net_income",
            "depreciation_amortization",
            "capital_expenditure",
            "change_in_working_capital",
            "financial_currency",
            "quote_currency",
        }
        for row in rows:
            assert required <= set(row.keys())

    def test_newest_first_and_windowed(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _build_sec_yearly_financials

        rows = _build_sec_yearly_financials(self._multi_concept_facts(), 2)
        # newest-first, windowed to 2 most-recent fiscal years
        assert [r["fiscal_year"][:4] for r in rows] == ["2023", "2022"]

    def test_margins_and_capex_sign(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _build_sec_yearly_financials

        rows = {
            r["fiscal_year"][:4]: r
            for r in _build_sec_yearly_financials(self._multi_concept_facts(), 10)
        }
        fy2023 = rows["2023"]
        # trough year: operating margin is negative (−100 / 800)
        assert fy2023["operating_margin"] == pytest.approx(-100 / 800)
        # capex stays a positive magnitude (FCF convention)
        assert fy2023["capital_expenditure"] == 70
        # EBITDA reconstructed via the identity EBIT + D&A (−100 + 80 = −20), since
        # SEC has no standalone EBITDA concept — faithful, not fabricated.
        assert fy2023["ebitda"] == pytest.approx(-100 + 80)
        assert rows["2021"]["ebitda"] == pytest.approx(200 + 60)
        assert rows["2021"]["operating_margin"] == pytest.approx(200 / 1000)

    def test_ebitda_none_when_component_missing(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _build_sec_yearly_financials

        # Revenue + operating income present, but NO D&A concept at all → the EBITDA
        # identity can't be formed, so ebitda is None (never a fabricated value).
        usgaap = {
            "Revenues": {
                "units": {
                    "USD": [
                        _fact(
                            start="2022-01-01",
                            end="2022-12-31",
                            val=1000,
                            fy=2022,
                            filed="2023-02-01",
                        )
                    ]
                }
            },
            "OperatingIncomeLoss": {
                "units": {
                    "USD": [
                        _fact(
                            start="2022-01-01",
                            end="2022-12-31",
                            val=200,
                            fy=2022,
                            filed="2023-02-01",
                        )
                    ]
                }
            },
        }
        rows = _build_sec_yearly_financials({"facts": {"us-gaap": usgaap}}, 10)
        assert rows[0]["ebitda"] is None

    def test_empty_facts_yield_no_rows(self) -> None:
        from finrobot.engine.data.providers.edgar_provider import _build_sec_yearly_financials

        assert _build_sec_yearly_financials({"facts": {"us-gaap": {}}}, 10) == []
