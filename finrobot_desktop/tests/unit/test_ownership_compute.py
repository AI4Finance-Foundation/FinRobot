from __future__ import annotations


from finrobot.engine.compute.ownership import (
    _canonical_transaction_type,
    build_proxy_compensation,
    compute_ownership_governance,
)


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
    from finrobot.engine.compute.ownership import build_insider_transactions

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
    from finrobot.engine.compute.ownership import build_insider_transactions

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
    from finrobot.engine.compute.ownership import _extract_ceo_name

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
    from finrobot.engine.compute.ownership import _extract_ceo_name

    text = (
        "Compensation Discussion and Analysis\n\n"
        "CEO compensation programs are reviewed annually by the Compensation Committee."
    )
    assert _extract_ceo_name(text) != "Analysis"


def test_extract_ceo_name_keeps_canonical_table_pattern() -> None:
    """The 'Name\\nCEO' table layout (Google/Alphabet proxy style) must
    still work — the regression test guards against tightening that
    breaks the high-confidence cases."""
    from finrobot.engine.compute.ownership import _extract_ceo_name

    text = "Sundar Pichai\nCEO Total Compensation $74M"
    assert _extract_ceo_name(text) == "Sundar Pichai"


def test_extract_ceo_name_keeps_honorific_pattern() -> None:
    """`Mr./Ms./Dr. Lastname` near a CEO anchor must still resolve."""
    from finrobot.engine.compute.ownership import _extract_ceo_name

    text = (
        "The Board reappointed Mr. Cook as Chief Executive Officer "
        "for another term."
    )
    assert _extract_ceo_name(text) == "Cook"


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
