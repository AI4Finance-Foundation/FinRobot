from __future__ import annotations


from finrobot.engine.compute.operators.ownership import (
    _canonical_transaction_type,
    _money_from_text,
    build_institutional_holdings,
    build_proxy_compensation,
    build_schedule13_alerts,
    compute_ownership_governance,
)


_SCHED13_OK = {
    "alerts": [
        {
            "filer_name": "FMR LLC",
            "filer_cik": "315066",
            "schedule_type": "13G",
            "filing_date": "2024-11-12",
            "accession_no": "0000315066-24-002826",
            "shares": 998_190_803,
            "pct_of_class": 4.069,
        },
        {
            "filer_name": "BlackRock Inc.",
            "filer_cik": "1364742",
            "schedule_type": "13G",
            "filing_date": "2024-01-26",
            "accession_no": "0001086364-24-000123",
            "shares": 180_593_555,
            "pct_of_class": 7.3,
        },
    ],
    "warnings": [],
    "provider": "edgar_tools",
}


def test_build_schedule13_alerts_typed() -> None:
    alerts = build_schedule13_alerts(_SCHED13_OK)
    assert [a.filer_name for a in alerts] == ["FMR LLC", "BlackRock Inc."]
    assert alerts[0].shares == 998_190_803
    assert alerts[0].pct_of_class == 4.069
    assert alerts[0].schedule_type == "13G"
    assert alerts[0].filing_date.isoformat() == "2024-11-12"


def test_13f_holding_missing_shares_or_value_is_dropped_not_zeroed() -> None:
    """A 13F holder row with a missing/unparseable share count or value is a
    parse gap, NOT a real 0-share / $0 position — it must be dropped, never
    coerced to a fabricated 0 (None ≠ 0). A complete row survives unchanged."""
    holdings = build_institutional_holdings(
        {
            "holders": [
                {
                    "holder_name": "BERKSHIRE HATHAWAY INC",
                    "holder_cik": "1067983",
                    "cusip": "037833100",
                    "name_of_issuer": "APPLE INC",
                    "shares": 300_000_000,
                    "value_usd": 57_843_260_493.0,
                    "period_end": "2026-03-31",
                    "filing_date": "2026-05-15",
                    "accession_no": "0000950123-26-000001",
                },
                {
                    # value omitted entirely (parse gap) — must be dropped, not $0
                    "holder_name": "GHOST CAPITAL LLC",
                    "cusip": "037833100",
                    "name_of_issuer": "APPLE INC",
                    "shares": 1000,
                    "period_end": "2026-03-31",
                    "filing_date": "2026-05-15",
                    "accession_no": "0000950123-26-000002",
                },
                {
                    # shares unparseable (footnote-only) — must be dropped, not 0
                    "holder_name": "PHANTOM PARTNERS",
                    "cusip": "037833100",
                    "name_of_issuer": "APPLE INC",
                    "shares": "[F1]",
                    "value_usd": 5_000_000.0,
                    "period_end": "2026-03-31",
                    "filing_date": "2026-05-15",
                    "accession_no": "0000950123-26-000003",
                },
            ]
        }
    )
    # Only the complete Berkshire row survives; the two degenerate rows dropped.
    assert len(holdings) == 1
    assert holdings[0].holder_name == "BERKSHIRE HATHAWAY INC"
    assert holdings[0].shares == 300_000_000
    assert holdings[0].value_usd == 57_843_260_493.0


def test_schedule13_pct_optional_when_unparseable() -> None:
    """Vanguard-style cover pages can defeat the % regex; shares is still real,
    pct stays None rather than a fabricated number."""
    alerts = build_schedule13_alerts(
        {
            "alerts": [
                {
                    "filer_name": "VANGUARD GROUP INC",
                    "schedule_type": "13G",
                    "filing_date": "2024-02-13",
                    "accession_no": "x",
                    "shares": 204_504_938,
                    "pct_of_class": None,
                }
            ]
        }
    )
    assert alerts[0].pct_of_class is None
    assert alerts[0].shares == 204_504_938


def test_compute_ownership_populates_schedule13_and_degrades_only_on_failure() -> None:
    base = {
        "insider_data": {"transactions": []},
        "institutional_data": {"holders": []},
        "proxy_data": {"proxy": None},
    }

    # Successful fetch with alerts → populated, NOT degraded.
    a = compute_ownership_governance(**base, schedule13_data=_SCHED13_OK)
    assert len(a.schedule13_alerts) == 2
    assert "schedule13_alerts" not in a.degraded_sections

    # Successful fetch, zero filings → empty + NOT degraded (genuinely none).
    b = compute_ownership_governance(**base, schedule13_data={"alerts": [], "provider": "x"})
    assert b.schedule13_alerts == []
    assert "schedule13_alerts" not in b.degraded_sections

    # Fetch failed → degraded so the UI shows "data unavailable", not "none".
    c = compute_ownership_governance(**base, schedule13_data={"available": False, "error": "boom"})
    assert c.schedule13_alerts == []
    assert "schedule13_alerts" in c.degraded_sections

    # Legacy callers (no schedule13_data) → empty, not degraded.
    d = compute_ownership_governance(**base)
    assert d.schedule13_alerts == []
    assert "schedule13_alerts" not in d.degraded_sections


# Representative slice of NVIDIA's FY2026 DEF 14A (filed 2026-05-12), flattened
# the way edgartools' .text() emits it. External benchmark (proxy original):
#   CEO Jen-Hsun Huang · FY2026 SCT total = $36,343,830 · pay ratio = 129:1
# The table puts name+year+figures on one line and the TITLE on the next — the
# layout that previously made the parser read the wrong year (FY2025).
_NVDA_PROXY_SCT = """
Summary Compensation Table for Fiscal 2026, 2025, and 2024

The following table summarizes information regarding the compensation earned by
our NEOs during Fiscal 2026, 2025, and 2024.

Name and Principal Position   Fiscal Year   Salary   Stock Awards   Option Awards   Non-Equity Incentive   Total
Jen-Hsun Huang   2026   1,497,627   24,800,511   6,000,000   4,045,691   (4)   36,343,830
President and CEO   2025   1,486,199   38,811,306   6,000,000   3,568,746   49,866,251
                    2024   996,514   26,676,415   4,000,000   2,494,973   34,167,902
Colette M. Kress   2026   898,577   12,825,872   2,000,000   1,500,000   17,224,449
EVP and CFO   2025   850,000   11,000,000   2,000,000   1,400,000   15,250,000

Pay Ratio

Our median employee's total compensation for Fiscal 2026 was $282,050. Our CEO's
Fiscal 2026 total compensation was $36,343,830. Therefore, our Fiscal 2026 CEO to
median employee pay ratio was 129:1.
"""


def test_proxy_compensation_nvda_fy2026_reads_correct_year_and_ratio() -> None:
    """Regression for BUG: parser read the FY2025 total ($49.9M) instead of the
    most-recent FY2026 total ($36,343,830) because the role group spanned the
    first data row. Also locks pay-ratio extraction from the Item 402(u)
    disclosure prose ("...pay ratio was 129:1")."""
    comp = build_proxy_compensation(
        {
            "filing_date": "2026-05-12",
            "accession_no": "0001045810-26-000036",
            "text": _NVDA_PROXY_SCT,
        }
    )
    assert comp is not None
    assert comp.ceo_name == "Jen-Hsun Huang"
    assert comp.ceo_total_compensation == 36_343_830.0
    assert comp.ceo_pay_ratio == 129


def test_proxy_pay_ratio_accepts_ratio_of_n_to_1_phrasing() -> None:
    """JPM-style disclosure says "...resulting in a ratio of 363 to 1" with no
    literal "pay ratio". The extractor must still capture it."""
    text = (
        "The annual total compensation of our estimated median employee was "
        "$111,905, resulting in a ratio of 363 to 1."
    )
    comp = build_proxy_compensation(
        {"filing_date": "2026-04-06", "accession_no": "x", "text": text}
    )
    assert comp is not None
    assert comp.ceo_pay_ratio == 363


def test_proxy_comp_from_ceo_total_prose_msft_phrasing() -> None:
    """MSFT states CEO comp in prose ("...total compensation of our CEO was
    $96,496,790") with the figures table in a vertical layout the grid parser
    can't read. The prose disclosure must carry it."""
    text = "for fiscal year 2025, the total compensation of our CEO was $96,496,790."
    comp = build_proxy_compensation(
        {"filing_date": "2025-10-21", "accession_no": "x", "text": text}
    )
    assert comp is not None
    assert comp.ceo_total_compensation == 96_496_790.0


def test_proxy_comp_ignores_roleless_peer_table_rows() -> None:
    """Safety: TSLA's proxy embeds a PEER company's comp table (Apple/Tim Cook)
    for comparison. Rows with no adjacent CEO title must NOT be read as the
    issuer's CEO comp — a wrong figure is worse than a blank."""
    text = (
        "Comparison of peer CEO pay. Name and Principal Position Year Total "
        "Tim Cook 2019 3,000,000 7,671,000 884,466 11,555,466 "
        "2018 3,000,000 12,000,000 682,219 15,682,219"
    )
    comp = build_proxy_compensation(
        {"filing_date": "2025-09-17", "accession_no": "x", "text": text}
    )
    # No CEO-comp prose and no role-anchored row → comp stays None (blank), and
    # critically NOT the peer's 11.5M / 15.7M figure.
    assert comp is None or comp.ceo_total_compensation is None


def test_proxy_compensation_pay_ratio_disclosure_is_comp_fallback() -> None:
    """When the SCT grid is unparseable, the pay-ratio disclosure sentence
    ("Our CEO's ... total compensation was $X") still yields CEO total comp."""
    text = (
        "Our CEO's Fiscal 2026 total compensation was $36,343,830. Therefore, "
        "our CEO to median employee pay ratio was 129:1."
    )
    comp = build_proxy_compensation(
        {"filing_date": "2026-05-12", "accession_no": "x", "text": text}
    )
    assert comp is not None
    assert comp.ceo_total_compensation == 36_343_830.0
    assert comp.ceo_pay_ratio == 129


def test_money_from_text_bare_m_is_not_a_million_multiplier() -> None:
    """BUG-011: the scale regex matched a bare 'm' with no word boundary, so
    "$96 measured over the period" parsed as 96 x 1e6 = $96,000,000 and the
    garbage cleared the [1M, 500M] CEO-comp gate. A raw $96 must stay $96 so
    the gate drops it. The real million/billion/bn suffixes still scale."""
    assert _money_from_text("$96 measured over the period") == 96.0
    assert _money_from_text("$96 million") == 96_000_000.0
    assert _money_from_text("$1.5 billion") == 1_500_000_000.0
    assert _money_from_text("$96bn") == 96_000_000_000.0


def test_proxy_pay_ratio_ignores_prior_year_ratio_for_current_year_pair() -> None:
    """BUG-012: the disclosure parser must return the (comp, ratio) pair from
    the SAME current-year 402(u) sentence. A prior-year ratio quoted earlier
    ("Last year, our CEO pay ratio was 250 to 1") must NOT override the
    current-year ratio (312) paired with the current-year CEO total comp."""
    text = (
        "Our median employee total compensation for fiscal 2025 was $96,000. "
        "Last year, our CEO pay ratio was 250 to 1. For fiscal 2025, our CEO "
        "total compensation was $30,000,000 and our CEO pay ratio was 312 to 1."
    )
    comp = build_proxy_compensation(
        {"filing_date": "2025-03-01", "accession_no": "x", "text": text}
    )
    assert comp is not None
    assert comp.ceo_total_compensation == 30_000_000.0
    assert comp.ceo_pay_ratio == 312


def test_form4_code_M_derivative_side_is_exercise_not_sale() -> None:
    """SEC Form 4 General Instructions § 8: code M = exercise/conversion of a
    derivative security under Rule 16b-3 — NEVER a sale. edgar-python emits
    ``derivative_sale`` for the option-leg of the same exercise event the
    issuer also reports on the stock leg as ``exercise``; canonical mapping
    collapses both sides onto ``exercise`` so the UI carries one truthful
    label. (TSLA 2026-05-15 Vaibhav Taneja Form 4 was the 2026-05-28 audit
    case in point.)"""
    assert _canonical_transaction_type("M", "derivative_sale") == "exercise"
    assert _canonical_transaction_type("M", "exercise") == "exercise"
    assert _canonical_transaction_type("M", "") == "exercise"


def test_form4_canonical_codes_cover_full_sec_table() -> None:
    """Every SEC Form 4 Section 8 transaction code maps to a stable, non-
    empty canonical type. Regression guard against silent gaps when the
    SEC publishes new codes or edgar-python ships a fresh label."""
    cases = {
        "P": "purchase",
        "S": "sale",
        "A": "grant",
        "D": "disposition_to_issuer",
        "F": "tax_withholding",
        "M": "exercise",
        "G": "gift",
        "J": "other",
        "C": "conversion",
        "X": "exercise_itm_atm",
        "O": "exercise_otm",
    }
    for code, expected in cases.items():
        assert _canonical_transaction_type(code, "irrelevant") == expected


def test_form4_unknown_code_falls_through_to_upstream_label() -> None:
    """Future-proof: if the SEC adds a code we don't know yet, surface
    whatever the provider gave us rather than dropping the type entirely.
    Empty fallback collapses to empty string, never raises."""
    assert _canonical_transaction_type("?", "tender_offer") == "tender_offer"
    assert _canonical_transaction_type(None, "purchase") == "purchase"
    assert _canonical_transaction_type("", None) == ""


def test_form4_build_insider_transactions_normalises_M_derivative_label() -> None:
    """End-to-end regression on the 2026-05-28 TSLA artifact bug: the
    derivative-leg row for a code-M exercise must read ``exercise``, not
    ``derivative_sale``. Mirrors the actual payload the artifact stored."""
    from finrobot.engine.compute.operators.ownership import build_insider_transactions

    rows = build_insider_transactions(
        {
            "transactions": [
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-062860",
                    "insider_name": "Vaibhav Taneja",
                    "insider_position": "Chief Financial Officer",
                    # edgar-python's wrong label arriving from the provider:
                    "transaction_type": "derivative_sale",
                    "code": "M",
                    "shares": 2000,
                    "value": 36440,
                    "price_per_share": 18.22,
                    "security_type": "derivative",
                    "security_title": "Stock Option",
                    "underlying_security": "Common Stock",
                },
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-062860",
                    "insider_name": "Vaibhav Taneja",
                    "insider_position": "Chief Financial Officer",
                    "transaction_type": "exercise",
                    "code": "M",
                    "shares": 2000,
                    "value": 36440,
                    "price_per_share": 18.22,
                    "security_type": "non-derivative",
                    "security_title": "Common Stock",
                    "underlying_security": "",
                },
            ]
        }
    )

    # Both rows of the same exercise event now carry the same canonical type.
    assert len(rows) == 2
    assert rows[0].transaction_type == "exercise"
    assert rows[1].transaction_type == "exercise"
    # security_type still distinguishes the two legs of the exercise.
    assert rows[0].security_type == "derivative"
    assert rows[1].security_type == "non-derivative"


def test_form4_missing_shares_value_become_none_not_zero() -> None:
    """A Form 4 leg whose provider omitted shares/value must carry None — a
    fabricated 0 makes a parse failure look like a real 0-share/$0 transaction,
    wasting analyst time. An *explicit* value=0 (forfeit/gift) stays 0 (None≠0)."""
    from finrobot.engine.compute.operators.ownership import build_insider_transactions

    rows = build_insider_transactions(
        {
            "transactions": [
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-000001",
                    "insider_name": "Jane Doe",
                    "transaction_type": "sale",
                    "code": "S",
                    # shares + value absent (provider parse gap)
                },
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-000002",
                    "insider_name": "Elon Musk",
                    "transaction_type": "other_disposition",
                    "code": "D",
                    "shares": 96_000_000,
                    "value": 0,  # Tornetta forfeit — a genuine $0 leg
                },
            ]
        }
    )

    assert rows[0].shares is None
    assert rows[0].value is None
    # Genuine forfeit: shares present, value an explicit 0 (not None).
    assert rows[1].shares == 96_000_000
    assert rows[1].value == 0.0


def test_compute_ownership_governance_builds_typed_models_with_provenance() -> None:
    analysis = compute_ownership_governance(
        insider_data={
            "transactions": [
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-062860",
                    "insider_name": "Vaibhav Taneja",
                    "insider_position": "CFO",
                    "transaction_type": "sale",
                    "code": "S",
                    "shares": 3000,
                    "value": 1_350_000,
                    "price_per_share": 450,
                    "security_type": "non-derivative",
                    "security_title": "Common Stock",
                }
            ]
        },
        institutional_data={
            "holders": [
                {
                    "holder_name": "Bridgewater",
                    "holder_cik": "1350694",
                    "cusip": "67066G104",
                    "name_of_issuer": "NVIDIA CORP",
                    "title_of_class": "COM",
                    "shares": 30_000_000,
                    "value_usd": 5.5e9,
                    "period_end": "2026-03-31",
                    "filing_date": "2026-05-15",
                    "accession_no": "0001350694-26-000001",
                }
            ]
        },
        proxy_data={
            "filing_date": "2026-01-08",
            "accession_no": "0001308179-26-000008",
            "text": "CEO pay ratio was 1,447 to 1. Total CEO compensation was $51.8 million.",
            "source_url": "https://www.sec.gov/Archives/example",
        },
    )

    assert analysis.degraded_sections == []
    assert analysis.insider_transactions[0].provenance.form == "4"
    assert analysis.institutional_holdings[0].provenance.form == "13F-HR"
    assert analysis.proxy_compensation is not None
    assert analysis.proxy_compensation.provenance.form == "DEF 14A"
    assert analysis.proxy_compensation.ceo_pay_ratio == 1447
    assert analysis.proxy_compensation.ceo_total_compensation == 51_800_000


def test_ceo_name_uses_form4_officer_title_over_prose_scrape() -> None:
    """CEO identity is a structured fact — the Form-4 officer title wins over the
    DEF 14A prose scraper.

    Regression for MU (2026-06): the scraper grabbed director "T. Mark Liu" off
    another firm's "Former Chief Executive Officer of Intel" bio while the Form-4s
    carried the real CEO "Sanjay Mehrotra". The comp figure is correct from the
    proxy; only the name must come from the authoritative Form-4 title.
    """
    analysis = compute_ownership_governance(
        insider_data={
            "transactions": [
                {
                    "filing_date": "2026-06-02",
                    "accession_no": "0001242654-26-000010",
                    "insider_name": "Sanjay Mehrotra",
                    "insider_position": "President and CEO",
                    "transaction_type": "sale",
                    "code": "S",
                    "shares": 560,
                    "value": 545_300,
                    "price_per_share": 973.75,
                    "security_type": "non-derivative",
                    "security_title": "Common Stock",
                }
            ]
        },
        institutional_data=None,
        proxy_data={
            "filing_date": "2025-11-25",
            "accession_no": "0000723125-25-000038",
            "text": (
                "Former Chief Executive Officer and Chief Financial Officer of "
                "Intel Corporation\n  T. Mark Liu was appointed to the Board, "
                "except for Mr. Liu and Ms. Simons, who joined in March 2025. "
                "Total CEO compensation was $30,940,146."
            ),
            "source_url": "https://www.sec.gov/Archives/example",
        },
    )
    assert analysis.proxy_compensation is not None
    assert analysis.proxy_compensation.ceo_name == "Sanjay Mehrotra"
    assert analysis.proxy_compensation.ceo_total_compensation == 30_940_146


def test_ceo_name_from_insiders_skips_former_and_nonceo_titles() -> None:
    """The Form-4 CEO resolver picks the current-CEO title, skipping a departed
    CEO's residual filings and non-CEO officers."""
    from finrobot.engine.compute.operators.ownership import (
        _ceo_name_from_insiders,
        build_insider_transactions,
    )

    insiders = build_insider_transactions(
        {
            "transactions": [
                {
                    "filing_date": "2026-01-01",
                    "accession_no": "a",
                    "insider_name": "Old Boss",
                    "insider_position": "Former Chief Executive Officer",
                    "code": "S",
                },
                {
                    "filing_date": "2026-02-01",
                    "accession_no": "b",
                    "insider_name": "Money Person",
                    "insider_position": "Chief Financial Officer",
                    "code": "S",
                },
                {
                    "filing_date": "2026-03-01",
                    "accession_no": "c",
                    "insider_name": "Real Boss",
                    "insider_position": "President and Chief Executive Officer",
                    "code": "S",
                },
            ]
        }
    )
    assert _ceo_name_from_insiders(insiders) == "Real Boss"
    assert _ceo_name_from_insiders([]) is None


def test_extract_ceo_name_rejects_paragraph_spanning_phrase() -> None:
    """TSLA DEF 14A 2025 contained a section heading "A More Profitable
    Future for Tesla and a Better Future for Us All" followed by a paragraph
    starting "Tesla does not currently have a long-term CEO performance
    award". The old regex stitched "Us All\\n\\nTesla" into a 3-token
    candidate name because (a) `\\s+` between name tokens allowed crossing
    the blank line, and (b) the title-only blacklist only rejected
    candidates *entirely* composed of title words, so "Tesla" let the
    candidate through.

    Both inputs the bug exploited must now be closed: name tokens must
    stay on one line, and any function-word token (Us, All, …) rejects
    the candidate.
    """
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = (
        "A More Profitable Future for Tesla and a Better Future for Us All\n\n"
        "Tesla does not currently have a long-term CEO performance award in place "
        "to retain Mr. Musk as Chief Executive Officer over the coming decade."
    )
    name = _extract_ceo_name(text)
    # Either Musk (correct) or None is acceptable. "Us All Tesla" is not.
    assert name != "Us All Tesla"
    assert name != "Us All"
    # Strategy 1 (honorific) should pick up "Musk" near the CEO anchor.
    assert name == "Musk"


def test_extract_ceo_name_rejects_section_heading_above_ceo_paragraph() -> None:
    """NVDA DEF 14A had a section heading "Compensation Discussion and
    Analysis" followed by a blank-line gap and a paragraph mentioning CEO.
    The old Strategy 0 regex captured the trailing single word "Analysis"
    as a candidate name because the `{0,3}` quantifier allowed zero
    additional tokens — i.e. a one-word "name". Real SCT table entries
    always carry at least "Firstname Lastname".
    """
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = (
        "Compensation Discussion and Analysis\n\n"
        "CEO compensation programs are reviewed annually by the Compensation Committee."
    )
    assert _extract_ceo_name(text) != "Analysis"


def test_extract_ceo_name_keeps_canonical_table_pattern() -> None:
    """The 'Name\\nCEO' table layout (Google/Alphabet proxy style) must
    still work — the regression test guards against tightening that
    breaks the high-confidence cases."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = "Sundar Pichai\nCEO Total Compensation $74M"
    assert _extract_ceo_name(text) == "Sundar Pichai"


def test_extract_ceo_name_keeps_honorific_pattern() -> None:
    """`Mr./Ms./Dr. Lastname` near a CEO anchor must still resolve."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = "The Board reappointed Mr. Cook as Chief Executive Officer for another term."
    assert _extract_ceo_name(text) == "Cook"


# --- T7#8 (4th recurrence, MSFT 2026-07-07): a CD&A prose sentence ending
#     "… for Mr. Smith." right above the "CEO Pay Ratio" heading was emitted as
#     CEO name "Mr. Smith." — a sentence fragment, not a name cell — and the
#     $96.5M SCT total got hung on the Vice Chair's honorific. Subsystem-wide
#     invariant: no extractor may emit a name containing a sentence-boundary
#     full-stop token (_is_blacklisted_name path c).


def test_extract_ceo_name_msft_prose_fragment_does_not_bind_honorific_fragment() -> None:
    """The false strategy-0 hit ("Mr. Smith.\\n\\nCEO Pay Ratio") must lose to
    the real signature layout ("Satya Nadella\\n\\nChairman and Chief Executive
    Officer") that the bare-CEO branch used to miss entirely."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = (
        "Satya Nadella\n\nChairman and Chief Executive Officer\n\n"
        "Letter from our Chairman\n\n"
        "…total value associated with retirement-based stock vesting of SAs: "
        "$6,254,433 for Mr. Smith.\n\nCEO Pay Ratio\n\n"
        "For fiscal year 2025, the annual total compensation of our CEO was $96,496,790."
    )
    assert _extract_ceo_name(text) == "Satya Nadella"


def test_extract_ceo_name_prose_fragment_alone_abstains() -> None:
    """With no trustworthy layout elsewhere, the fragment must yield None —
    never "Mr. Smith."."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = "stock vesting of SAs: $6,254,433 for Mr. Smith.\n\nCEO Pay Ratio\n\n"
    assert _extract_ceo_name(text) is None


def test_extract_ceo_name_does_not_bind_directors_outside_ceo_role() -> None:
    """A director's OUTSIDE 'Chief Executive Officer, Acme Corp' line is not
    this issuer's CEO — the full-title branch must reject ', <Company>'."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = "Jane Roe\nChief Executive Officer, Acme Corp\n"
    assert _extract_ceo_name(text) is None


def test_is_blacklisted_name_rejects_sentence_boundary_tokens() -> None:
    """Initials ("B.") and suffixes ("Jr.") are legitimate; a full-stop token
    like "Smith." / "Mr." marks a prose boundary and poisons the whole run."""
    from finrobot.engine.compute.operators.ownership import _is_blacklisted_name

    assert _is_blacklisted_name("Mr. Smith.")
    assert _is_blacklisted_name("Smith. Satya")
    assert not _is_blacklisted_name("Jane B. Doe")
    assert not _is_blacklisted_name("Sammy Davis Jr.")


# --- T7#8 (3rd recurrence): the no-Form-4 DEF 14A prose fallback must never
#     emit a wrong PERSON. A director/successor surname sitting near a CEO
#     anchor that belongs to someone else must NOT win; None beats a wrong CEO.


def test_extract_ceo_name_ko_succession_proxy_binds_named_ceo_not_successor() -> None:
    """KO 2026 DEF 14A (no in-window Form-4 CEO leg → prose fallback). The
    proxy announces a CEO succession: incoming COO "Henrique Braun" appears via
    "Mr. Braun ... Chief Executive Officer" near a CEO anchor that actually
    belongs to the *named* CEO "James Quincey, our Chairman and Chief Executive
    Officer". The old honorific-proximity strategy grabbed "Braun" (a wrong
    person). The appositive comma-bind must win and the proximity heuristic must
    never override it.
    """
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = (
        "As I prepare to pass the baton to Henrique Braun, I'm proud of our team. "
        "As CEO, I delivered another year of strong performance.\n\n"
        "All nominees are independent under the NYSE corporate governance rules, "
        "except for James Quincey, our Chairman and Chief Executive Officer, and "
        "Henrique Braun, our Executive Vice President and Chief Operating Officer. "
        "In connection with the announcement that Mr. Braun will serve as Chief "
        "Executive Officer of the Company effective March 31, 2026, Mr. Braun was "
        "nominated to the Board. Effective March 31, 2026, Henrique Braun will "
        "succeed James Quincey as CEO of the Company."
    )
    name = _extract_ceo_name(text)
    assert name == "James Quincey"
    # The load-bearing assertion: never the successor/COO surname.
    assert name != "Braun"
    assert "Braun" not in (name or "")


def test_extract_ceo_name_abstains_when_two_honorifics_flank_ceo_anchor() -> None:
    """When NO appositive title bind exists and TWO distinct honorific names sit
    near CEO anchors (a succession/co-leadership proxy), the extractor cannot
    confidently pick one and must abstain (None) rather than coin-flip a wrong
    person. A single unambiguous honorific still resolves (locked above)."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    text = (
        "Mr. Smith stepped down. The Board announced that Mr. Jones will serve "
        "as Chief Executive Officer, with Mr. Smith remaining as a senior advisor "
        "to the Chief Executive Officer during the transition."
    )
    # Two honorific candidates (Smith, Jones) both near CEO anchors, no comma
    # appositive bind → abstain. Never silently return one of them.
    assert _extract_ceo_name(text) is None


def test_extract_ceo_name_appositive_handles_chairman_and_ceo() -> None:
    """The appositive bind must accept the canonical "<Name>, our Chairman and
    Chief Executive Officer" / "<Name>, President and Chief Executive Officer"
    forms, not only the bare "Chief Executive Officer"."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name

    assert (
        _extract_ceo_name("Reelect James Quincey, our Chairman and Chief Executive Officer.")
        == "James Quincey"
    )
    assert (
        _extract_ceo_name("We nominate Mary Barra, President and Chief Executive Officer.")
        == "Mary Barra"
    )


# --- SOX-302 CEO certification (Exhibit 31.1) — the authoritative current-CEO
#     source that outranks the (annual, succession-stale) DEF 14A prose. Signer
#     texts below are the real formats probed 2026-07-09 across the mega-cap
#     basket (KO/AAPL/MSFT/JPM/NVDA/GOOGL/XOM/AMZN/META/DIS).

# The two live cert opening formats: a title clause between the name and
# "certify" (KO/DIS) vs. the bare "I, <Name>, certify" (everyone else).
_CERT_KO = (
    "EXHIBIT 31.1 CERTIFICATION\n"
    "I, Henrique Braun, Chief Executive Officer of The Coca-Cola Company, "
    "certify that:\n"
    "1. I have reviewed this Quarterly Report on Form 10-Q ...\n"
    "Date: April 30, 2026\n/s/ Henrique Braun\nHenrique Braun\n"
    "Chief Executive Officer of The Coca-Cola Company\n"
)
_CERT_AAPL = (
    "Exhibit 31.1\nI, Timothy D. Cook, certify that:\n"
    "1. I have reviewed this Quarterly Report on Form 10-Q of Apple Inc. ...\n"
    "Date: May 1, 2026\nBy: /s/ Timothy D. Cook\nTimothy D. Cook\n"
    "Chief Executive Officer\n"
)


def test_extract_ceo_name_from_cert_bare_i_certify() -> None:
    """Bare "I, <Name>, certify" opening (AAPL/MSFT/JPM/NVDA/XOM/AMZN/META)."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name_from_cert

    assert _extract_ceo_name_from_cert(_CERT_AAPL) == "Timothy D. Cook"
    assert _extract_ceo_name_from_cert("I, Satya Nadella, certify that:") == "Satya Nadella"
    # Hyphenated + middle-initial legal names survive intact.
    assert _extract_ceo_name_from_cert("I, Jen-Hsun Huang, certify that:") == "Jen-Hsun Huang"
    assert _extract_ceo_name_from_cert("I, Darren W. Woods, certify that:") == "Darren W. Woods"


def test_extract_ceo_name_from_cert_title_clause_between_name_and_certify() -> None:
    """KO/DIS format: a title clause sits between the name and "certify". The
    comma right after the name bounds the capture so the title never leaks in."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name_from_cert

    assert _extract_ceo_name_from_cert(_CERT_KO) == "Henrique Braun"
    # DIS: apostrophe surname + parenthetical issuer clause before "certify".
    dis = (
        "I, Josh D'Amaro, Chief Executive Officer of The Walt Disney Company "
        '(the "Company"), certify that:\n'
    )
    assert _extract_ceo_name_from_cert(dis) == "Josh D'Amaro"


def test_extract_ceo_name_from_cert_signature_block_fallback() -> None:
    """When the opening sentence can't yield a name, the closing signature block
    (typed name directly above the CEO title line) is the fallback."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name_from_cert

    cert = (
        "Exhibit 31.1\nI, the undersigned officer, certify that:\n"
        "1. I have reviewed this report ...\n"
        "Date: May 1, 2026\n/s/ Sundar Pichai\nSundar Pichai\n"
        "Chief Executive Officer (Principal Executive Officer)\n"
    )
    assert _extract_ceo_name_from_cert(cert) == "Sundar Pichai"


def test_extract_ceo_name_from_cert_rejects_garbage_via_choke() -> None:
    """Every cert candidate funnels through _is_blacklisted_name — a title-only,
    corporate-vocabulary, or sentence-fragment run can never surface as a CEO."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name_from_cert

    assert _extract_ceo_name_from_cert("I, Chief Executive Officer, certify that:") is None
    assert _extract_ceo_name_from_cert("I, Median Employee, certify that:") is None
    assert _extract_ceo_name_from_cert("I, Acme Corporation, certify that:") is None
    # Sentence-boundary honorific fragment (MSFT 2026-07 family) → reject.
    assert _extract_ceo_name_from_cert("I, Mr. Smith., certify that:") is None


def test_extract_ceo_name_from_cert_missing_returns_none() -> None:
    """No cert text / no matchable name → None (caller falls back to proxy)."""
    from finrobot.engine.compute.operators.ownership import _extract_ceo_name_from_cert

    assert _extract_ceo_name_from_cert("") is None
    assert _extract_ceo_name_from_cert("This exhibit contains no certification opening.") is None


def _ko_proxy_payload() -> dict[str, object]:
    """KO 2026 DEF 14A prose: scrapes the OUTGOING named CEO 'James Quincey'."""
    return {
        "filing_date": "2026-03-16",
        "accession_no": "0000021344-26-000012",
        "text": (
            "except for James Quincey, our Chairman and Chief Executive Officer, and "
            "Henrique Braun, our Executive Vice President and Chief Operating Officer. "
            "Our CEO's total compensation was $27,000,000. The CEO pay ratio was 1,624 to 1."
        ),
        "source_url": "https://www.sec.gov/Archives/ko-proxy",
    }


def test_ceo_name_cert_overrides_proxy_ko_succession() -> None:
    """KO 2026 end-to-end: the DEF 14A (filed before the 2026-03-31 succession)
    still scrapes outgoing CEO 'James Quincey', but the latest 10-Q's Ex-31.1 is
    signed by 'Henrique Braun'. The cert is the current principal executive
    officer by law → it wins, with source + provenance recorded."""
    analysis = compute_ownership_governance(
        insider_data=None,
        institutional_data=None,
        proxy_data=_ko_proxy_payload(),
        cert_data={
            "cert_available": True,
            "cert_text": _CERT_KO,
            "form": "10-Q",
            "filing_date": "2026-04-30",
            "accession_no": "0001628280-26-028802",
            "source_url": "https://www.sec.gov/Archives/ko-10q",
        },
    )
    comp = analysis.proxy_compensation
    assert comp is not None
    assert comp.ceo_name == "Henrique Braun"
    assert comp.ceo_name_source == "sox302_cert"
    assert comp.ceo_name_provenance is not None
    assert comp.ceo_name_provenance.form == "10-Q"
    assert comp.ceo_name_provenance.filing_date.isoformat() == "2026-04-30"
    # The comp figures still come from the proxy — only the NAME is overridden.
    assert comp.ceo_total_compensation == 27_000_000
    assert comp.filing_date.isoformat() == "2026-03-16"


def test_ceo_name_falls_back_to_proxy_when_cert_absent() -> None:
    """No cert (foreign filer / no Ex-31.1 / fetch miss) → keep the proxy name,
    source stays 'def14a'. A miss must never blank or corrupt the name."""
    analysis = compute_ownership_governance(
        insider_data=None,
        institutional_data=None,
        proxy_data=_ko_proxy_payload(),
        cert_data={"cert_available": False},
    )
    comp = analysis.proxy_compensation
    assert comp is not None
    assert comp.ceo_name == "James Quincey"
    assert comp.ceo_name_source == "def14a"
    assert comp.ceo_name_provenance is None


def test_ceo_name_cert_garbage_falls_back_to_proxy() -> None:
    """A cert whose signer can't be cleanly parsed (choke reject) must NOT
    override — fall back to the proxy name rather than emit a wrong CEO."""
    analysis = compute_ownership_governance(
        insider_data=None,
        institutional_data=None,
        proxy_data=_ko_proxy_payload(),
        cert_data={
            "cert_available": True,
            "cert_text": "I, Chief Executive Officer, certify that:\n",
            "form": "10-Q",
            "filing_date": "2026-04-30",
            "accession_no": "0001628280-26-028802",
        },
    )
    comp = analysis.proxy_compensation
    assert comp is not None
    assert comp.ceo_name == "James Quincey"
    assert comp.ceo_name_source == "def14a"


def test_ceo_name_cert_wins_over_form4_officer_title() -> None:
    """Priority: SOX-302 cert > Form-4 officer title > proxy prose. When both a
    Form-4 CEO title and a cert resolve to different names, the cert (current
    PEO, quarterly) wins."""
    analysis = compute_ownership_governance(
        insider_data={
            "transactions": [
                {
                    "filing_date": "2026-02-10",
                    "accession_no": "0000000000-26-000001",
                    "insider_name": "James Quincey",
                    "insider_position": "Chairman and CEO",
                    "transaction_type": "sale",
                    "code": "S",
                    "shares": 100,
                    "value": 6000,
                    "price_per_share": 60.0,
                    "security_type": "non-derivative",
                    "security_title": "Common Stock",
                }
            ]
        },
        institutional_data=None,
        proxy_data=_ko_proxy_payload(),
        cert_data={
            "cert_available": True,
            "cert_text": _CERT_KO,
            "form": "10-Q",
            "filing_date": "2026-04-30",
            "accession_no": "0001628280-26-028802",
        },
    )
    comp = analysis.proxy_compensation
    assert comp is not None
    assert comp.ceo_name == "Henrique Braun"
    assert comp.ceo_name_source == "sox302_cert"


# --- T7#8 (same recurrence, Form-4 leg): a divisional/regional CEO title must
#     not outrank the parent-company CEO on the filing-count tie-break.


def test_ceo_from_insiders_rejects_divisional_regional_ceo_title() -> None:
    """Ford 2026 Form-4s carry both "President and CEO" (Jim Farley, the
    issuer's CEO) and "President & CEO Ford China&IMG" (Shengpo Wu, a regional
    unit CEO). The regional CEO filed enough Form-4s to win the (count, recency)
    tie-break and was wrongly resolved as the parent CEO. A business-unit CEO
    title must be skipped so only the parent CEO can resolve."""
    from finrobot.engine.compute.operators.ownership import (
        _ceo_name_from_insiders,
        build_insider_transactions,
    )

    insiders = build_insider_transactions(
        {
            "transactions": [
                # Regional CEO files MORE and MORE RECENTLY — would win the
                # (count, latest) tie-break if not rejected.
                *[
                    {
                        "filing_date": f"2026-06-{day:02d}",
                        "accession_no": f"div-{day}",
                        "insider_name": "Shengpo Wu",
                        "insider_position": "President & CEO Ford China&IMG",
                        "code": "S",
                    }
                    for day in (1, 2, 3, 4, 5)
                ],
                # Parent CEO files fewer / earlier.
                *[
                    {
                        "filing_date": f"2026-01-{day:02d}",
                        "accession_no": f"parent-{day}",
                        "insider_name": "Jr James D Farley",
                        "insider_position": "President and CEO",
                        "code": "S",
                    }
                    for day in (1, 2)
                ],
            ]
        }
    )
    assert _ceo_name_from_insiders(insiders) == "Jr James D Farley"


def test_is_divisional_ceo_title_distinguishes_parent_from_unit() -> None:
    """Anchor the divisional check: parent-company CEO titles (unqualified, or
    continued only by a connector / "of the Company") are NOT divisional;
    a named region/brand/segment after the CEO token IS divisional."""
    from finrobot.engine.compute.operators.ownership import _is_divisional_ceo_title

    # Parent-company CEO titles — must NOT be flagged divisional.
    for title in (
        "President and CEO",
        "Chief Executive Officer",
        "Chairman and Chief Executive Officer",
        "President & CEO",
        "President and Chief Executive Officer",
        "CEO of the Company",
        "Chief Executive Officer and Chairman",
    ):
        assert _is_divisional_ceo_title(title) is False, title

    # Divisional / regional / subsidiary CEO titles — MUST be flagged.
    for title in (
        "President & CEO Ford China&IMG",
        "CEO Ford China&IMG",
        "CEO, EMEA",
        "President & CEO of EMEA",
        "CEO of Ford Credit",
    ):
        assert _is_divisional_ceo_title(title) is True, title


def test_compute_ownership_governance_survives_legacy_cached_footnote_dates() -> None:
    """Defence-in-depth: cached insider payloads written by older code versions
    may carry edgartools footnote stand-ins like "[F4]" in exercise_date /
    expiration_date. The compute layer must collapse those to None instead of
    crashing the entire pipeline with ``Invalid isoformat string: '[F4]'``.
    """
    analysis = compute_ownership_governance(
        insider_data={
            "transactions": [
                {
                    "filing_date": "2026-05-15",
                    "accession_no": "0001104659-26-062860",
                    "insider_name": "Sample Insider",
                    "insider_position": "Director",
                    "transaction_type": "grant",
                    "code": "A",
                    "shares": 10_000,
                    "value": 0,
                    "price_per_share": 0,
                    "security_type": "derivative",
                    "security_title": "Non-Qualified Stock Option",
                    "underlying_security": "Common Stock",
                    "exercise_date": "[F4]",
                    "expiration_date": "[F1,F2]",
                    "footnote_ids": "F1,F2,F4",
                    "footnotes_text": "Vesting per F4 schedule.",
                }
            ]
        },
        institutional_data={"holders": []},
        proxy_data={"proxy": None},
    )

    assert len(analysis.insider_transactions) == 1
    tx = analysis.insider_transactions[0]
    assert tx.exercise_date is None
    assert tx.expiration_date is None
    assert tx.footnote_ids == "F1,F2,F4"


def test_compute_ownership_governance_marks_empty_sections_degraded() -> None:
    analysis = compute_ownership_governance(
        insider_data={"transactions": []},
        institutional_data={"holders": []},
        proxy_data={"proxy": None},
    )

    assert analysis.insider_transactions == []
    assert analysis.institutional_holdings == []
    assert analysis.proxy_compensation is None
    assert analysis.degraded_sections == [
        "insider_transactions",
        "institutional_holdings",
        "proxy_compensation",
    ]


def test_compute_ownership_governance_lifts_payload_warnings() -> None:
    """Fetch warnings (e.g. 13F stale-quarter) must reach the analysis object —
    _collect_warnings only sees structured models, so dropping them here means
    they never reach artifact.outputs.warnings (same contract as
    FinancialData.warnings)."""
    analysis = compute_ownership_governance(
        insider_data={"transactions": [], "warnings": ["insider fetch degraded"]},
        institutional_data={
            "holders": [],
            "warnings": ["13F holdings are stale: serving 2025-09-30, expected 2026-03-31"],
        },
        proxy_data={"proxy": None},
        schedule13_data={"alerts": [], "warnings": ["insider fetch degraded"]},
    )
    # Deduped, order-preserving union of all four payloads' warnings.
    assert analysis.warnings == [
        "insider fetch degraded",
        "13F holdings are stale: serving 2025-09-30, expected 2026-03-31",
    ]


def test_compute_ownership_governance_no_warnings_field_defaults_empty() -> None:
    analysis = compute_ownership_governance(
        insider_data={"transactions": []},
        institutional_data={"holders": []},
        proxy_data={"proxy": None},
    )
    assert analysis.warnings == []
