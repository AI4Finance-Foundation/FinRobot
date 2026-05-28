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

import pytest

from finrobot.engine.data.interface import ProviderError
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
    for attr in ("business", "risk_factors", "management_discussion",
                 "directors_officers_and_governance", "subsidiaries", "notes"):
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
        tenq.management_discussion = f"Q{4-i} MD&A " * 50
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

    form4 = MagicMock()
    form4.insider_name = "Elon Musk"
    form4.position = "CEO"
    form4.get_transaction_activities.return_value = [act1, act2]

    f = MagicMock()
    f.filing_date = date.today() - timedelta(days=10)
    f.accession_no = "0001104659-26-062860"
    f.obj.return_value = form4
    filings = MagicMock()
    filings.latest.return_value = [f]
    c = MagicMock()
    c.get_filings.return_value = filings

    data, _ = p._fetch_insider(c, days=90)
    assert len(data["transactions"]) == 2
    # Forfeit row preserves price=None when price_per_share=0
    forfeit = next(t for t in data["transactions"] if t["code"] == "D")
    assert forfeit["shares"] == 96_000_000
    assert forfeit["price_per_share"] is None  # 0 coerced to None
    assert "Tornetta" in forfeit["footnotes_text"]


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
    for attr in ("transaction_type", "code", "security_type", "security_title",
                 "underlying_security", "footnote_ids", "footnotes_text"):
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
    """TSLA-class proxies are 500k+ chars; the Summary Compensation Table
    sits 100k+ chars deep, well past the 50k governance-intro head cap.
    The slicer must keep the intro AND splice in a 40k window anchored
    on the first SCT heading found past the intro cut so the SCT row
    extractor has something to parse.
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
    # SCT body must exceed the 40k window so the tail beyond it is
    # actually excluded from the sliced window.
    sct = (
        "Summary Compensation Table\n"
        "Name and Principal Position    Year   Salary    Total\n"
        "Elon Musk Chief Executive Officer 2024 0 100,000,000\n"
    ) + ("w" * 50_000)
    tail = "TAIL_BEYOND_SCT_WINDOW" * 5_000

    full = intro + body_gap + sct + tail
    sliced = _slice_proxy_text(full)

    # Intro is preserved verbatim
    assert sliced.startswith("INTRO ")
    # The SCT window is present
    assert "Elon Musk Chief Executive Officer" in sliced
    # Bounded: intro + gap marker + SCT window — well under full text size
    assert len(sliced) < 100_000
    # Tail beyond the SCT window is dropped
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


@pytest.mark.asyncio
async def test_fetch_xbrl_uses_typed_getters() -> None:
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    facts = MagicMock()
    ttm = MagicMock()
    ttm.concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ttm.value = 451_442_000_000
    # Plain strings → fallback {"raw": ...} typed dict shape
    ttm.periods = ["Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"]
    facts.get_ttm_revenue.return_value = ttm
    facts.get_ttm_net_income.return_value = None  # nullable
    facts.get_revenue.return_value = 416_161_000_000
    facts.get_net_income.return_value = 96_995_000_000
    facts.get_gross_profit.return_value = 184_103_000_000
    facts.get_operating_income.return_value = 123_216_000_000
    facts.get_total_assets.return_value = 364_980_000_000
    facts.get_total_liabilities.return_value = 308_030_000_000
    facts.get_shareholders_equity.return_value = 56_950_000_000

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)
    assert data["facts_available"] is True
    assert data["latest_revenue"] == 416_161_000_000
    assert data["ttm_revenue"]["concept"].startswith("us-gaap:Revenue")
    assert data["ttm_revenue"]["value"] == 451_442_000_000
    # Plain strings fall through to {"raw": ...} fallback shape
    assert all("raw" in p for p in data["ttm_revenue"]["periods"])
    assert data["ttm_net_income"] is None


@pytest.mark.asyncio
async def test_fetch_xbrl_balance_sheet_prefers_latest_period_over_latest_annual() -> None:
    """Reproduces the 2026-05-28 TSLA balance-sheet staleness bug: when the
    issuer has both a FY 10-K and a more recent 10-Q on file, the artifact
    must surface the 10-Q values. ``edgar-python``'s standardized getters
    default to ``annual=True`` (FY only). The provider passes ``annual=False``
    for assets/liabilities/equity so the most recent point wins regardless
    of form type — verified by mocking distinct annual vs non-annual
    return values."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    facts = MagicMock()
    facts.get_ttm_revenue.return_value = None
    facts.get_ttm_net_income.return_value = None
    facts.get_revenue.return_value = None
    facts.get_net_income.return_value = None
    facts.get_gross_profit.return_value = None
    facts.get_operating_income.return_value = None

    # FY 10-K value vs. Q1 10-Q value — must pick the Q1 (annual=False) one.
    # Numbers anchor to TSLA on 2026-05-28: 10-K $137.806B vs 10-Q $143.724B.
    def _assets(annual: bool = True) -> float:
        return 137_806_000_000 if annual else 143_724_000_000

    def _liab(annual: bool = True) -> float:
        return 54_941_000_000 if annual else 58_922_000_000

    def _equity(annual: bool = True) -> float:
        return 82_137_000_000 if annual else 84_116_000_000

    facts.get_total_assets.side_effect = _assets
    facts.get_total_liabilities.side_effect = _liab
    facts.get_shareholders_equity.side_effect = _equity

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)

    # Must surface the Q1 10-Q values, not the FY 10-K.
    assert data["latest_total_assets"] == 143_724_000_000
    assert data["latest_total_liabilities"] == 58_922_000_000
    assert data["latest_shareholders_equity"] == 84_116_000_000


@pytest.mark.asyncio
async def test_fetch_xbrl_periods_tuple_produces_typed_dict() -> None:
    """Tuple periods → {"year": int, "quarter": str} typed dict — not repr string."""
    p = EdgarToolsProvider("Jane Doe jane@example.com")
    facts = MagicMock()
    ttm = MagicMock()
    ttm.concept = "us-gaap:NetIncomeLoss"
    ttm.value = 96_995_000_000
    ttm.periods = [(2025, "Q3"), (2025, "Q4")]
    facts.get_ttm_revenue.return_value = None
    facts.get_ttm_net_income.return_value = ttm
    facts.get_revenue.return_value = None
    facts.get_net_income.return_value = 96_995_000_000
    facts.get_gross_profit.return_value = None
    facts.get_operating_income.return_value = None
    facts.get_total_assets.return_value = None
    facts.get_total_liabilities.return_value = None
    facts.get_shareholders_equity.return_value = None

    c = MagicMock()
    c.get_facts.return_value = facts
    data, _ = p._fetch_xbrl(c)

    ni_ttm = data["ttm_net_income"]
    assert ni_ttm is not None
    assert ni_ttm["periods"] == [{"year": 2025, "quarter": "Q3"}, {"year": 2025, "quarter": "Q4"}]
    # Must NOT be Python repr string
    for period_entry in ni_ttm["periods"]:
        assert "(" not in str(period_entry), "period must not be a Python repr tuple string"


@pytest.mark.asyncio
async def test_xbrl_concept_snapshot_net_income_dual_key() -> None:
    """xbrl_concept_snapshot splits NetIncomeLoss into :annual and :ttm keys."""
    from finrobot.engine.compute.xbrl_aligned_comps import xbrl_concept_snapshot

    raw_xbrl = {
        "ttm_net_income": {
            "concept": "us-gaap:NetIncomeLoss",
            "value": 100_000_000,
            "periods": [{"year": 2025, "quarter": "Q3"}, {"year": 2025, "quarter": "Q4"}],
        },
        "latest_net_income": 90_000_000,
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
        p, "_fetch_sync",
        lambda ticker, data_type, kwargs: ({"foo": "bar"}, ["one warning"]),
    )
    result = await p.fetch("aapl", DataType.FILINGS_10K)
    assert result.ticker == "AAPL"
    assert result.provider == "edgar_tools"
    assert result.data == {"foo": "bar"}
    assert result.warnings == ["one warning"]
    assert result.timestamp.tzinfo is not None  # UTC tz-aware
