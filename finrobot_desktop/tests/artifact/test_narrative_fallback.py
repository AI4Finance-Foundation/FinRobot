"""``_fill_narrative_fallbacks`` fills NULL narrative fields with a DETERMINISTIC
summary from the frozen structured data — so a report never publishes empty sections
(TSM 2026-07-02: 5/9 sections NULL in one run), and never fabricates prose."""

from __future__ import annotations

from finrobot.artifact.builders import _fill_narrative_fallbacks


def _structured() -> dict:
    return {
        "thesis": {
            "recommendation": "HOLD",
            "price_target": None,
            "price_target_basis": "FAIRLY VALUED: price $334.60 within the RI band [$272, $369].",
            # Narrative fields the LLM omitted (NULL) — the bug:
            "tagline": None,
            "key_takeaways": None,
            "company_overview": None,
            "valuation_overview": None,
            "competitor_analysis": None,
            "news_summary": None,
            # One field the LLM DID write — must be preserved untouched.
            "narrative": "The bank is well capitalized.",
        },
        "valuation_synthesis": {
            "confidence": "medium",
            "methods": [{"name": "comps_pb"}, {"name": "residual_income"}],
        },
        "peer_analysis": {
            "peers": [{"ticker": "BAC"}, {"ticker": "WFC"}, {"ticker": "C"}],
            "median_pe": 15.06,
            "median_ev_ebitda": 13.53,
        },
        "catalyst_analysis": {"overall_sentiment": "bullish", "net_sentiment": 0.42},
    }


def _raw_data() -> dict:
    return {
        "company_name": "JPMorgan Chase & Co.",
        "market": {"industry": "Banks - Diversified", "sector": "Financial Services", "market_cap": 9.3e11},
        "income": {"revenue": 1.86e11},
    }


def test_null_fields_filled_deterministically_from_structured_data():
    structured = _structured()
    warnings = _fill_narrative_fallbacks(structured, _raw_data(), "JPM")
    thesis = structured["thesis"]

    # Every previously-NULL field is now non-empty.
    for k in ("tagline", "key_takeaways", "company_overview", "valuation_overview",
              "competitor_analysis", "news_summary"):
        assert thesis[k], f"{k} should be filled"

    # valuation_overview = the deterministic basis (traceable, lists the real reasoning).
    assert "FAIRLY VALUED" in thesis["valuation_overview"]
    # competitor_analysis cites the real peers + medians, labeled as peer-set medians.
    assert "BAC" in thesis["competitor_analysis"] and "WFC" in thesis["competitor_analysis"]
    assert "15.1x" in thesis["competitor_analysis"]  # median_pe
    assert "not JPM's own trading multiples" in thesis["competitor_analysis"]
    # company_overview from company facts (traceable), with the no-fabrication segment note.
    assert "JPMorgan Chase & Co." in thesis["company_overview"]
    assert "Banks - Diversified" in thesis["company_overview"]
    assert "Segment revenue breakdown was not available" in thesis["company_overview"]
    # news_summary from catalyst sentiment.
    assert "bullish" in thesis["news_summary"]
    # key_takeaways: verdict + withheld-point line (target is None here).
    assert any("HOLD" in t for t in thesis["key_takeaways"])
    assert any("withheld" in t for t in thesis["key_takeaways"])

    # The one LLM-authored field is untouched.
    assert thesis["narrative"] == "The bank is well capitalized."

    # Provenance flagged — reader-facing wording, no bracketed engineering tag
    # (external audit 2026-07-07), naming every deterministically-filled field.
    assert warnings and warnings[0].startswith("Narrative note:")
    assert "[" not in warnings[0]
    assert "tagline" in warnings[0] and "key_takeaways" in warnings[0]


def test_present_fields_not_overwritten_and_no_warning():
    structured = _structured()
    # LLM wrote everything this time.
    structured["thesis"].update(
        tagline="A real tagline.",
        key_takeaways=["A real takeaway."],
        company_overview="A real overview.",
        valuation_overview="A real valuation overview.",
        competitor_analysis="A real competitor analysis.",
        news_summary="A real news summary.",
    )
    warnings = _fill_narrative_fallbacks(structured, _raw_data(), "JPM")
    assert warnings == []
    assert structured["thesis"]["tagline"] == "A real tagline."
    assert structured["thesis"]["valuation_overview"] == "A real valuation overview."
