"""Audit tests for proxy compensation plausibility gates.

These tests guard the four bugs in build_proxy_compensation that caused
AAPL to display "Chief Executive Officer" as CEO name and $416B as CEO comp.

Red-line contract (must all hold):
1. ceo_name must not be a title/role word from the blacklist.
2. ceo_total_compensation must be in [1M, 500M] or None.
3. comp extraction must be anchored near "CEO total compensation/pay" keyword.
4. Garbage text (no CEO keyword near a dollar amount) returns None for comp.
5. Valid "CEO Total Compensation $74,250,000" is accepted correctly.
"""

from __future__ import annotations

from finrobot.engine.compute.operators.ownership import (
    _CEO_COMP_MAX,
    _CEO_COMP_MIN,
    _CEO_NAME_BLACKLIST,
    build_proxy_compensation,
    compute_ownership_governance,
)


# ---------------------------------------------------------------------------
# Fixtures — raw proxy dicts with filing metadata required by the function
# ---------------------------------------------------------------------------

_BASE_META: dict[str, str] = {
    "filing_date": "2026-01-15",
    "accession_no": "0001193125-26-000001",
    "source_url": "https://www.sec.gov/test",
}


def _proxy(text: str) -> dict[str, object]:
    return {**_BASE_META, "text": text}


# ---------------------------------------------------------------------------
# Case 1: Tim Cook + $63M → accepted ✓
# ---------------------------------------------------------------------------


def test_valid_ceo_name_and_comp_accepted() -> None:
    """Tim Cook is a real name; $63M is inside [1M, 500M]."""
    text = (
        "Tim Cook, our Chief Executive Officer, received CEO total compensation "
        "of $63,000,000 in fiscal 2025. The CEO pay ratio was 1,447 to 1."
    )
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None
    assert proxy.ceo_name == "Tim Cook"
    assert proxy.ceo_total_compensation == 63_000_000.0
    assert proxy.ceo_pay_ratio == 1447


# ---------------------------------------------------------------------------
# Case 2: Literal "Chief Executive Officer" as name → rejected ✗
# ---------------------------------------------------------------------------


def test_literal_title_rejected_as_ceo_name() -> None:
    """When regex captures only role words, ceo_name must be None."""
    text = (
        "Chief Executive Officer received total compensation of $63,000,000. "
        "The CEO pay ratio was 500 to 1."
    )
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None, "Proxy with pay ratio should still build"
    # Name was all title words — must be None.
    assert proxy.ceo_name is None, f"Expected None, got: {proxy.ceo_name!r}"


# ---------------------------------------------------------------------------
# Case 3: $416B → rejected (above _CEO_COMP_MAX) ✗
# ---------------------------------------------------------------------------


def test_implausible_comp_above_max_rejected() -> None:
    """$416B is AAPL's revenue/market-cap range, not a CEO salary."""
    # Use an anchored keyword so the extractor even tries.
    text = (
        "CEO total compensation for fiscal year 2025 was $416,000,000,000. "
        "The CEO pay ratio is 900 to 1."
    )
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None, "Filing metadata is valid; proxy object should exist"
    assert proxy.ceo_total_compensation is None, (
        f"Expected None for $416B comp, got: {proxy.ceo_total_compensation}"
    )


# ---------------------------------------------------------------------------
# Case 4: No CEO keyword near a dollar amount → ceo_total_compensation None ✗
# ---------------------------------------------------------------------------


def test_no_ceo_keyword_near_dollar_returns_none_for_comp() -> None:
    """A document that discusses revenue/market cap with no CEO pay anchor."""
    text = (
        "Apple Inc. reported annual revenue of $391 billion. "
        "The company repurchased $87 billion in shares during fiscal 2025. "
        "Employees received various benefits totaling $2.1 billion."
    )
    proxy = build_proxy_compensation(_proxy(text))
    # No CEO comp anchor, so comp must be None.
    assert proxy is None or proxy.ceo_total_compensation is None, (
        f"Expected None for comp with no CEO anchor, got: "
        f"{proxy.ceo_total_compensation if proxy else 'proxy=None'}"
    )


# ---------------------------------------------------------------------------
# Case 5: "CEO Total Compensation $74,250,000" → accepted ✓
# ---------------------------------------------------------------------------


def test_explicit_ceo_total_comp_line_accepted() -> None:
    """Standard NEO table line format is accepted."""
    text = "Sundar Pichai\nCEO Total Compensation $74,250,000\nThe CEO pay ratio was 833 to 1.\n"
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None
    assert proxy.ceo_total_compensation == 74_250_000.0
    assert proxy.ceo_name == "Sundar Pichai"
    assert proxy.ceo_pay_ratio == 833


def test_aapl_summary_compensation_table_beats_business_highlights() -> None:
    """Apple 2026 DEF 14A: revenue is $416.2B, Tim Cook SCT total is $74.294811M."""
    text = (
        "2025 Business Highlights Net sales $416.2 billion. "
        "Summary Compensation Table Name and Principal Position Year Salary Stock Awards "
        "Non-Equity Incentive Plan Compensation All Other Compensation Total "
        "Tim Cook Chief Executive Officer 2025 3,000,000 58,093,236 12,000,000 "
        "1,201,575 (2) 74,294,811 "
        "Summary of CEO Total Target Compensation 2025 Total Target CEO Compensation: "
        "$59 million. The 2025 annual total compensation of our CEO was $74,294,811, "
        "the 2025 annual total compensation of our median compensated employee was "
        "$139,483, and the ratio of these amounts is 533 to 1."
    )
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None
    assert proxy.ceo_name == "Tim Cook"
    assert proxy.ceo_total_compensation == 74_294_811.0
    assert proxy.ceo_pay_ratio == 533


def test_target_ceo_compensation_is_not_actual_total_compensation() -> None:
    text = (
        "Summary of CEO Total Target Compensation 2025 Total Target CEO Compensation: "
        "$59 million. Actual Summary Compensation Table data appears elsewhere."
    )
    proxy = build_proxy_compensation(_proxy(text))
    assert proxy is not None
    assert proxy.ceo_total_compensation is None


# ---------------------------------------------------------------------------
# Blacklist coverage
# ---------------------------------------------------------------------------


def test_all_blacklist_words_are_rejected() -> None:
    """Every word in the blacklist must not survive as a ceo_name by itself."""
    for word in _CEO_NAME_BLACKLIST:
        text = (
            f"{word} received CEO total compensation of $50,000,000. The CEO pay ratio is 400 to 1."
        )
        proxy = build_proxy_compensation(_proxy(text))
        if proxy is not None:
            assert proxy.ceo_name is None or word.lower() not in proxy.ceo_name.lower(), (
                f"Blacklisted word {word!r} leaked into ceo_name: {proxy.ceo_name!r}"
            )


# ---------------------------------------------------------------------------
# Plausibility bounds constants are correct
# ---------------------------------------------------------------------------


def test_ceo_comp_bounds_are_reasonable() -> None:
    assert _CEO_COMP_MIN == 1_000_000.0, "Min CEO comp should be $1M"
    assert _CEO_COMP_MAX == 500_000_000.0, "Max CEO comp should be $500M"


# ---------------------------------------------------------------------------
# Silent garbage gate: all-None NEO fields → degraded_sections includes proxy
# ---------------------------------------------------------------------------


def test_garbage_proxy_triggers_degraded_section() -> None:
    """When ceo_name/comp/ratio all parse to None, proxy section must be degraded."""
    # Text has the filing metadata but the actual text is a boilerplate
    # "incorporated by reference" string like AAPL's 10-K item_10_directors.
    text = (
        "Incorporated by reference to the definitive proxy statement. "
        "See Part III. $391,000,000,000 revenue reported."
    )
    analysis = compute_ownership_governance(
        insider_data={"transactions": []},
        institutional_data={"holders": []},
        proxy_data={**_BASE_META, "text": text},
    )
    assert "proxy_compensation" in analysis.degraded_sections, (
        "All-None NEO proxy should appear in degraded_sections"
    )
    assert analysis.proxy_compensation is None, (
        "proxy_compensation field must be None when all NEO fields are garbage"
    )
