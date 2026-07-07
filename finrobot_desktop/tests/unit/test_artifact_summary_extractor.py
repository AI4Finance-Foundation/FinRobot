"""Extractor pulls entry/target/target_date out of full Artifacts (v5 ADR-0001)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.store import _summary_from_artifact
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_fairly_valued,
    extract_tagline,
    extract_target_date,
    extract_target_price,
    extract_verdict,
)

UTC = timezone.utc
CREATED = datetime(2026, 5, 1, tzinfo=UTC)


def _artifact(
    *,
    raw_data: dict | None = None,
    structured: dict | None = None,
    type_: str = "equity_research",
) -> Artifact:
    return Artifact(
        id="art_2026-05-01T00:00:00_NVDA_equity_research",
        ticker="NVDA",
        cross_tickers=[],
        type=type_,  # type: ignore[arg-type]
        inputs=ArtifactInputs(
            data_source="yfinance",
            data_fetched_at=CREATED,
            raw_data=raw_data or {},
        ),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="x"),
        outputs=ArtifactOutputs(structured=structured or {}, summary_text="head"),
        meta=ArtifactMeta(created_at=CREATED, source="pipeline:equity_research"),
    )


def test_entry_price_extracted_from_financialdata_raw_dump() -> None:
    art = _artifact(raw_data={"market": {"current_price": 876.42}})
    assert extract_entry_price(art) == 876.42


def test_entry_price_none_when_market_missing() -> None:
    assert extract_entry_price(_artifact(raw_data={})) is None


def test_entry_price_none_when_value_non_positive() -> None:
    art = _artifact(raw_data={"market": {"current_price": 0}})
    assert extract_entry_price(art) is None


def test_target_price_from_equity_research_thesis_block() -> None:
    art = _artifact(structured={"thesis": {"price_target": 920.0}})
    assert extract_target_price(art) == 920.0


def test_target_price_from_dcf_top_level_implied_price() -> None:
    # build_dcf_artifact dumps DCFResult FLAT (`_safe_dump(dcf)`); implied_price
    # sits at the top of structured, never under a `dcf_calc` nest.
    art = _artifact(structured={"implied_price": 185.4}, type_="dcf")
    assert extract_target_price(art) == 185.4


def test_target_price_from_ddm_equity_value_per_share() -> None:
    # Regression (Q5): DDMResult has no `implied_price` — its per-share headline
    # is `equity_value_per_share`, dumped FLAT by build_ddm_artifact. The old
    # `ddm_calc.implied_price` read matched no real artifact, so every DDM target
    # extracted as None and never reached the coverage list / signal lamp.
    art = _artifact(structured={"equity_value_per_share": 142.5}, type_="ddm")
    assert extract_target_price(art) == 142.5


def test_target_price_withheld_when_data_health_gate_nulls_thesis() -> None:
    """The data-health gate withholds the headline target (thesis.price_target
    -> None) precisely because the raw DCF implied_price is untrustworthy (e.g.
    TSLA $20.38 on a $418 market). The summary extractor must honour that
    withhold and NOT resurrect ``financial_modeling.implied_price`` for the
    coverage-list column / signal lamp — the gate's whole purpose is to keep
    that number off the screen. Regression for the 2026-06-05 TSLA/AMD artifacts
    whose REVIEW verdict still carried a $20 / $22 target in the artifacts.db
    column."""
    art = _artifact(
        structured={
            "thesis": {
                "price_target": None,
                "recommendation": "REVIEW",
                "price_target_basis": "DATA-HEALTH GATE: target withheld.",
            },
            "financial_modeling": {"implied_price": 20.38},
        },
    )
    assert extract_target_price(art) is None


def test_target_price_from_top_level_implied_price() -> None:
    art = _artifact(structured={"implied_price": 42.0}, type_="lbo")
    assert extract_target_price(art) == 42.0


def test_target_price_none_when_structured_empty() -> None:
    assert extract_target_price(_artifact(structured={})) is None


def test_target_date_defaults_to_created_at_plus_365_when_present() -> None:
    art = _artifact(structured={"thesis": {"price_target": 920.0}})
    expected = CREATED + timedelta(days=365)
    assert extract_target_date(art, 920.0) == expected


def test_target_date_honours_explicit_thesis_date_iso_string() -> None:
    art = _artifact(
        structured={"thesis": {"price_target": 920.0, "target_date": "2027-01-15T00:00:00+00:00"}}
    )
    out = extract_target_date(art, 920.0)
    assert out == datetime(2027, 1, 15, tzinfo=UTC)


def test_target_date_none_when_no_target_price() -> None:
    assert extract_target_date(_artifact(), None) is None


def test_summary_from_artifact_carries_new_v5_fields() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 876.42}},
        structured={"thesis": {"price_target": 920.0}},
    )
    s = _summary_from_artifact(art)
    assert s.entry_price == 876.42
    assert s.target_price == 920.0
    assert s.target_date == CREATED + timedelta(days=365)
    assert s.signal is None  # always lazy — routes attach it


def test_summary_from_legacy_artifact_keeps_v5_fields_none() -> None:
    s = _summary_from_artifact(_artifact())
    assert s.entry_price is None
    assert s.target_price is None
    assert s.target_date is None
    assert s.signal is None


def test_summary_from_artifact_headline_skips_markdown_facade() -> None:
    """summary_from_artifact projects a PROSE headline preview, not the leaked
    "# FinRobot Analysis Report / --- / ## Data Collection" markdown scaffolding
    that format_summary() opens a multi-method report with — the raw string the
    exported-HTML timeline JSON embeds for external readers."""
    art = _artifact()
    art.outputs.summary_text = (
        "# FinRobot Analysis Report\n\n---\n\n## Data Collection\n\n"
        "NVIDIA reported data-center revenue of $47.5B, up 154% YoY."
    )
    s = _summary_from_artifact(art)
    assert s.headline.startswith("NVIDIA reported data-center revenue of $47.5B")
    assert "#" not in s.headline
    assert "FinRobot Analysis Report" not in s.headline


# ── verdict ──────────────────────────────────────────────────────────────────


def test_verdict_pulls_recommendation_field() -> None:
    art = _artifact(structured={"thesis": {"recommendation": "Buy", "price_target": 100.0}})
    assert extract_verdict(art) == "BUY"


def test_verdict_normalises_case_and_whitespace() -> None:
    for raw in ("  hold ", "Hold", "HOLD"):
        art = _artifact(structured={"thesis": {"recommendation": raw, "price_target": 100.0}})
        assert extract_verdict(art) == "HOLD"


def test_verdict_falls_back_to_verdict_alias_when_recommendation_missing() -> None:
    art = _artifact(structured={"thesis": {"verdict": "SELL", "price_target": 100.0}})
    assert extract_verdict(art) == "SELL"


def test_verdict_returns_none_for_malformed_input() -> None:
    assert extract_verdict(_artifact(structured={"thesis": {"recommendation": "Maybe"}})) is None
    assert extract_verdict(_artifact(structured={"thesis": {}})) is None
    assert extract_verdict(_artifact(structured={"thesis": "not a dict"})) is None
    assert extract_verdict(_artifact()) is None


def test_verdict_maps_legacy_review_to_neutral_withheld_display() -> None:
    """Legacy artifacts (pre-Phase-2) stored recommendation=='REVIEW' (the deleted
    refuse-to-judge verdict). extract_verdict must still surface them — mapped to a
    neutral WITHHELD display, never dropped to None, and never re-emitting the
    forbidden 'REVIEW' string. New artifacts only ever write BUY/HOLD/SELL."""
    art = _artifact(structured={"thesis": {"recommendation": "REVIEW", "price_target": None}})
    out = extract_verdict(art)
    assert out == "WITHHELD"
    assert out != "REVIEW"


# ── tagline ──────────────────────────────────────────────────────────────────


def test_tagline_pulls_synthesis_agent_field() -> None:
    art = _artifact(
        structured={
            "thesis": {
                "tagline": "Services 高毛利 + 印度产能分散 · 估值仍有 14% 空间",
                "price_target": 295.0,
            }
        }
    )
    assert extract_tagline(art) == "Services 高毛利 + 印度产能分散 · 估值仍有 14% 空间"


def test_tagline_strips_whitespace_and_treats_empty_as_none() -> None:
    assert extract_tagline(_artifact(structured={"thesis": {"tagline": "  hello  "}})) == "hello"
    assert extract_tagline(_artifact(structured={"thesis": {"tagline": "   "}})) is None
    assert extract_tagline(_artifact(structured={"thesis": {"tagline": ""}})) is None


def test_tagline_none_for_legacy_artifact_without_field() -> None:
    # Legacy artifacts (pre narrative bump) have no tagline slot.
    art = _artifact(structured={"thesis": {"recommendation": "BUY", "price_target": 100.0}})
    assert extract_tagline(art) is None


def test_tagline_none_when_no_thesis() -> None:
    assert extract_tagline(_artifact()) is None
    assert extract_tagline(_artifact(structured={"thesis": "not a dict"})) is None


def test_summary_from_artifact_carries_verdict_and_tagline() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 876.42}},
        structured={
            "thesis": {
                "recommendation": "BUY",
                "price_target": 920.0,
                "tagline": "AI 算力超级周期受益者 · 估值仍有 30% 空间",
            }
        },
    )
    s = _summary_from_artifact(art)
    assert s.verdict == "BUY"
    assert s.tagline == "AI 算力超级周期受益者 · 估值仍有 30% 空间"


# ── fairly_valued (in-band point-target withhold) ────────────────────────────


def test_fairly_valued_true_for_in_band_withhold() -> None:
    """valuation_withheld AND a basis led by "FAIRLY VALUED" (the in-band framing
    synthesize_valuations writes when the live price sits inside the band) → True.
    Mirrors the frontend `fairlyValued` derivation in reportData.ts."""
    art = _artifact(
        structured={
            "valuation_withheld": True,
            "thesis": {
                "recommendation": "HOLD",
                "price_target": None,
                "price_target_basis": (
                    "FAIRLY VALUED — price sits inside the fair-value band; HOLD on direction."
                ),
            },
        }
    )
    assert extract_fairly_valued(art) is True


def test_fairly_valued_prefix_is_case_and_leading_whitespace_insensitive() -> None:
    art = _artifact(
        structured={
            "valuation_withheld": True,
            "thesis": {"price_target_basis": "   fairly valued (within range)"},
        }
    )
    assert extract_fairly_valued(art) is True


def test_fairly_valued_false_for_genuine_withhold() -> None:
    """A real withhold (M&A data poisoning / single divergent method) leads the
    basis with "WITHHELD", not "FAIRLY VALUED" → not fairly valued (honest
    uncertainty, not a confident HOLD)."""
    art = _artifact(
        structured={
            "valuation_withheld": True,
            "thesis": {
                "recommendation": "HOLD",
                "price_target": None,
                "price_target_basis": "WITHHELD — M&A transition poisons the trailing inputs.",
            },
        }
    )
    assert extract_fairly_valued(art) is False


def test_fairly_valued_false_when_point_not_withheld() -> None:
    """A published point target is never 'fairly valued' — the flag requires the
    point to have been withheld (valuation_withheld is True) in the first place,
    even if some stray basis text starts with the phrase."""
    art = _artifact(
        structured={
            "thesis": {
                "recommendation": "BUY",
                "price_target": 250.0,
                "price_target_basis": "FAIRLY VALUED",  # ignored: valuation_withheld absent
            }
        }
    )
    assert extract_fairly_valued(art) is False


def test_fairly_valued_false_without_thesis_or_basis() -> None:
    assert extract_fairly_valued(_artifact()) is False
    assert extract_fairly_valued(_artifact(structured={"valuation_withheld": True})) is False
    assert (
        extract_fairly_valued(
            _artifact(structured={"valuation_withheld": True, "thesis": "not a dict"})
        )
        is False
    )


def test_summary_from_artifact_carries_fairly_valued() -> None:
    in_band = _artifact(
        structured={
            "valuation_withheld": True,
            "thesis": {
                "recommendation": "HOLD",
                "price_target": None,
                "price_target_basis": "FAIRLY VALUED — within band.",
            },
        }
    )
    assert _summary_from_artifact(in_band).fairly_valued is True
    # Legacy / plain artifact (no withhold) projects False, not None.
    assert _summary_from_artifact(_artifact()).fairly_valued is False
