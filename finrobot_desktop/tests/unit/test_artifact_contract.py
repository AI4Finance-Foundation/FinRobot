"""Output-contract total gate (ArtifactContract) — persist-boundary invariants.

The contract runs at the single auto-persist boundary (runner.py, between the
builder output and the store.save). It asserts whole-artifact invariants the
upstream point gates structurally cannot — they each see one object (a
ValuationSynthesis, a FinancialData snapshot, one prose field), never the
assembled artifact's headline/basis/narrative together. MVP clauses:

  C1  headline upside band  — target/entry must sit in the calibrated band
      (single-method [0.5x, 2x], multi-method [0.25x, 4x]). Catches the MU
      $2172 = 2.5x-$864 accident (lone comps_pe on a memory cyclical's peak EPS)
      regardless of how the upstream gate mis-calibrated.
  C2  double-decimal malformation — a $-anchored amount with two decimal points
      ($2172.062.06) is a concatenation artifact; withhold (can't auto-repair).

The tests assert the GATE CAUGHT IT (withhold + REVIEW + evidence), not that the
number is "right" — the contract definition is itself the oracle. Accident
specimens ($2172/$864, $2172.062.06) are the documented bug numbers from
valuation_synthesis.py:77-79 and the narrative-reconcile regression, not live
quotes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from finrobot.artifact.contract import CONTRACT_CLAUSES, enforce_artifact_contract
from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.summary_extractor import extract_target_price

UTC = timezone.utc
CREATED = datetime(2026, 6, 8, tzinfo=UTC)


def _artifact(
    *,
    raw_data: dict | None = None,
    structured: dict | None = None,
    llm_narrative: dict | None = None,
    summary_text: str = "head",
    warnings: list[str] | None = None,
    type_: str = "equity_research",
) -> Artifact:
    return Artifact(
        id="art_2026-06-08T00:00:00_MU_equity_research",
        ticker="MU",
        cross_tickers=[],
        type=type_,  # type: ignore[arg-type]
        inputs=ArtifactInputs(
            data_source="yfinance",
            data_fetched_at=CREATED,
            raw_data=raw_data or {},
        ),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="x"),
        outputs=ArtifactOutputs(
            structured=structured or {},
            llm_narrative=llm_narrative or {},
            summary_text=summary_text,
            warnings=list(warnings or []),
        ),
        meta=ArtifactMeta(created_at=CREATED, source="pipeline:equity_research"),
    )


def _warnings(art: Artifact) -> list[str]:
    return art.outputs.warnings


# ── Step 0: skeleton no-op ───────────────────────────────────────────────────


def test_clean_artifact_passes_through_unchanged() -> None:
    """A compliant artifact (in-band target, no malformed amounts) must come out
    byte-for-byte identical — the contract only ever degrades on a real
    violation, never touches a healthy artifact."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
        },
        llm_narrative={"recommendation": "BUY", "tagline": "fairly valued"},
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_registry_is_a_list_of_clauses() -> None:
    assert isinstance(CONTRACT_CLAUSES, list)
    assert CONTRACT_CLAUSES, "MVP ships C1 + C2"
    assert {c.id for c in CONTRACT_CLAUSES} >= {"C1", "C2"}


# ── C1: headline upside band ─────────────────────────────────────────────────


def _mu_2172_artifact() -> Artifact:
    """The MU accident: lone comps_pe → $2172 target = 2.5x the $864 market,
    shipped as a confident +151% BUY. Single method (weighted_price None)."""
    return _artifact(
        raw_data={"market": {"current_price": 864.0}},
        structured={
            "thesis": {
                "price_target": 2172.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe 36.9x → $2172",
            },
            "valuation_synthesis": {"weighted_price": None, "methods": ["comps_pe"]},
        },
        llm_narrative={
            "recommendation": "BUY",
            "tagline": "memory super-cycle, +151% upside",
            "company_overview": "Micron is a memory maker.",
        },
    )


def test_c1_withholds_single_method_target_out_of_band() -> None:
    art = enforce_artifact_contract(_mu_2172_artifact())
    structured = art.outputs.structured
    assert structured["thesis"]["price_target"] is None
    # Value-withhold, NOT a refuse-to-rate: the directional verdict is preserved.
    assert structured["thesis"]["recommendation"] == "BUY"
    assert structured["valuation_withheld"] is True
    assert structured["withheld_reason"] == "contract_C1"
    assert extract_target_price(art) is None  # C7 invariant: truly gone
    assert any(w.startswith("[CONTRACT/C1]") for w in _warnings(art))


def test_c1_neutralises_narrative_conclusion_keeps_body() -> None:
    """Withhold neutralises the point-target conclusion (tagline) but PRESERVES
    the directional verdict + the analysis body verbatim + stamps provenance."""
    art = enforce_artifact_contract(_mu_2172_artifact())
    narrative = art.outputs.llm_narrative
    assert narrative["recommendation"] == "BUY"  # verdict preserved, never REVIEW
    assert narrative["tagline"] is None
    assert narrative["company_overview"] == "Micron is a memory maker."  # body untouched
    assert any(w.startswith("[CONTRACT/withheld]") for w in _warnings(art))


def test_c1_passes_target_inside_single_method_band() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            # 1.8x < 2x; single-method basis discloses no cross-check so C6 is
            # silent and this stays a clean C1-only pass-through.
            "thesis": {
                "price_target": 180.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe — single-method, no cross-check available",
            },
            "valuation_synthesis": {"weighted_price": None},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c1_multi_method_band_is_wider_than_single() -> None:
    """A 3x target survives the multi-method [0.25x, 4x] band (weighted_price
    present = corroborated) but would trip the single-method [0.5x, 2x] band."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 300.0, "recommendation": "BUY"},  # 3x
            "valuation_synthesis": {"weighted_price": 295.0},  # corroborated
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] == 300.0  # survives
    assert "valuation_withheld" not in out.outputs.structured


def test_c1_noop_when_type_has_no_per_share_headline() -> None:
    """comps / lbo carry no per-share target (extract_target_price -> None), so
    C1 is structurally a no-op — never a spurious withhold."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={"median_pe": 18.5},  # PeerComps shape, no headline
        type_="comps",
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c1_withholds_plain_dcf_flat_headline() -> None:
    """A plain DCF dumps implied_price FLAT (no thesis). An out-of-band flat
    headline must still be withheld so it can't resurrect via extract_target_price."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={"implied_price": 350.0},  # 3.5x, single method, no synthesis block
        type_="dcf",
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["implied_price"] is None
    assert out.outputs.structured["valuation_withheld"] is True
    assert extract_target_price(out) is None


# ── C2: double-decimal malformation ──────────────────────────────────────────


def test_c2_catches_double_decimal_in_thesis_prose() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": "DCF implies $2172.062.06 per share",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["valuation_withheld"] is True
    assert out.outputs.structured["withheld_reason"] == "contract_C2"
    assert any(w.startswith("[CONTRACT/C2]") for w in _warnings(out))
    assert "$2172.062.06" in " ".join(_warnings(out))


def test_c2_catches_double_decimal_inside_llm_narrative_dict() -> None:
    """⟦复核⟧ llm_narrative is a dict, not a str — C2 must traverse its values."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
        },
        llm_narrative={"valuation_overview": "Fair value $1,234.562.06 on our DCF."},
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["valuation_withheld"] is True
    assert any(w.startswith("[CONTRACT/C2]") for w in _warnings(out))


def test_c2_ignores_legal_three_decimal_numbers() -> None:
    """The corrected $-anchored double-point regex must NOT fire on the most
    common legal financial decimals: beta 1.085, R² 0.987, FX 7.234, a fractional
    strike $1.875, a percentage 0.025. (The naive \\d\\.\\d{2}\\d regex mauled
    all of these — see spec C2 ⟦复核⟧.)"""
    prose = (
        "beta 1.085, R² 0.987, USDTWD 7.234, strike $1.875, 0.025 of revenue, "
        "fair value $1,234.56 today"
    )
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": prose,
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
        llm_narrative={"valuation_overview": prose},
        summary_text=prose,
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before  # nothing tripped


def test_enforce_is_idempotent_on_a_withheld_artifact() -> None:
    """Running the contract twice must not double-stamp or change the verdict —
    a withheld artifact re-enforced stays withheld with no extra mutation beyond
    the already-appended warnings. The withheld-target signal (verdict directional,
    price_target None) is stable, so the second run re-detects it (via C7) without
    mutating anything further."""
    once = enforce_artifact_contract(_mu_2172_artifact())
    snapshot = copy.deepcopy(once.model_dump())
    twice = enforce_artifact_contract(once)
    # target stays None, verdict stays directional (BUY); warnings carry the evidence.
    assert twice.outputs.structured["thesis"]["price_target"] is None
    assert twice.outputs.structured["thesis"]["recommendation"] == "BUY"
    assert twice.model_dump()["outputs"]["structured"] == snapshot["outputs"]["structured"]


# ── Step 2 oracle: C1 band 3-point boundary tests ────────────────────────────


def _single_method_target_artifact(target: float, *, entry: float = 100.0) -> Artifact:
    return _artifact(
        raw_data={"market": {"current_price": entry}},
        structured={
            "thesis": {"price_target": target, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": None},  # single method
        },
    )


def _multi_method_target_artifact(target: float, *, entry: float = 100.0) -> Artifact:
    return _artifact(
        raw_data={"market": {"current_price": entry}},
        structured={
            "thesis": {"price_target": target, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": target - 1.0},  # corroborated
        },
    )


def test_c1_single_method_just_under_2x_passes() -> None:
    """1.99x sits inside the single-method [0.5x, 2x] band → survives."""
    out = enforce_artifact_contract(_single_method_target_artifact(199.0))
    assert out.outputs.structured["thesis"]["price_target"] == 199.0
    assert "valuation_withheld" not in out.outputs.structured


def test_c1_single_method_exactly_2x_passes() -> None:
    """The 2.0x boundary is INCLUSIVE (lo <= ratio <= hi) → survives."""
    out = enforce_artifact_contract(_single_method_target_artifact(200.0))
    assert out.outputs.structured["thesis"]["price_target"] == 200.0
    assert "valuation_withheld" not in out.outputs.structured


def test_c1_single_method_just_over_2x_trips() -> None:
    """2.01x is outside the single-method band → withheld."""
    out = enforce_artifact_contract(_single_method_target_artifact(201.0))
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert out.outputs.structured["valuation_withheld"] is True
    assert any(w.startswith("[CONTRACT/C1]") for w in _warnings(out))


def test_c1_multi_method_exactly_4x_passes_just_over_trips() -> None:
    """Multi-method band boundary: 4.0x inclusive passes, 4.01x trips."""
    on_edge = enforce_artifact_contract(_multi_method_target_artifact(400.0))
    assert on_edge.outputs.structured["thesis"]["price_target"] == 400.0
    over = enforce_artifact_contract(_multi_method_target_artifact(401.0))
    assert over.outputs.structured["thesis"]["price_target"] is None
    assert over.outputs.structured["valuation_withheld"] is True


# ── Step 2 oracle: C2 regex fuzz table ───────────────────────────────────────

_C2_LEGAL = ["1.085", "0.987", "$1.875", "7.234", "$1,234.56"]
_C2_MALFORMED = ["$2172.062.06", "$1,234.562.06", "$50.001.2"]


@pytest.mark.parametrize("amount", _C2_LEGAL)
def test_c2_fuzz_legal_amounts_never_caught(amount: str) -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": f"value is {amount} here",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before  # legal amount, nothing tripped


@pytest.mark.parametrize("amount", _C2_MALFORMED)
def test_c2_fuzz_malformed_amounts_all_caught(amount: str) -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": f"DCF implies {amount} per share",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["valuation_withheld"] is True
    assert any(w.startswith("[CONTRACT/C2]") for w in _warnings(out))


# ── C7: withheld must not resurrect ──────────────────────────────────────────


def test_c7_nulls_resurrected_financial_modeling_implied_price_on_withheld_target() -> None:
    """The real bug, verdict now preserved: a SELL thesis whose own price_target is
    withheld (None) yet financial_modeling.implied_price=20.35 rides naked in
    structured. C7 scans the RAW slot, nulls it, fires [CONTRACT/C7]. The withheld
    signal is (directional verdict + price_target None), not the deleted REVIEW."""
    art = _artifact(
        raw_data={"market": {"current_price": 18.0}},
        structured={
            "thesis": {"price_target": None, "recommendation": "SELL"},
            "financial_modeling": {"implied_price": 20.35},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["financial_modeling"]["implied_price"] is None
    assert out.outputs.structured["valuation_withheld"] is True
    assert out.outputs.structured["withheld_reason"] == "contract_C7"
    # The directional verdict is preserved un-scrubbed.
    assert out.outputs.structured["thesis"]["recommendation"] == "SELL"
    assert any(w.startswith("[CONTRACT/C7/internal]") for w in _warnings(out))


def test_c7_evidence_is_internal_tag_not_surfaced_to_analyst() -> None:
    """C7 is an INTERNAL scrub invariant — its evidence is engineering plumbing
    ("nulling so it cannot resurrect downstream" + a raw float), not a withhold
    REASON. It must NOT surface to the analyst UI: the report parser renders only
    `[CONTRACT/Cn] …` (tag immediately closed), so C7 emits the non-surfacing
    `[CONTRACT/C7/internal] …`. Regression lock for the MU leak where C7's plumbing
    showed as the cover withhold reason + the top audit banner."""
    art = _artifact(
        raw_data={"market": {"current_price": 18.0}},
        structured={
            "thesis": {"price_target": None, "recommendation": "HOLD"},
            "financial_modeling": {"implied_price": 188.12},
        },
    )
    warnings = _warnings(enforce_artifact_contract(art))
    # Recorded for the audit trail under the non-surfacing /internal sub-tag …
    assert any(w.startswith("[CONTRACT/C7/internal] ") for w in warnings)
    # … and NEVER under the analyst-facing surfaced format the report UI parses
    # (`[CONTRACT/C7] …` with the tag closed immediately after the clause id).
    assert not any(w.startswith("[CONTRACT/C7] ") for w in warnings)


def test_c7_judges_withheld_via_directional_verdict_with_null_target() -> None:
    """The withheld signal is a directional verdict (BUY/HOLD/SELL) with
    price_target None — NOT a pre-set valuation_withheld. C7 must still fire and
    must NOT touch the verdict."""
    art = _artifact(
        raw_data={"market": {"current_price": 18.0}},
        structured={
            "thesis": {"price_target": None, "recommendation": "HOLD"},
            "dcf_result": {"implied_price": 99.0},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["dcf_result"]["implied_price"] is None
    assert out.outputs.structured["thesis"]["recommendation"] == "HOLD"
    assert any(w.startswith("[CONTRACT/C7/internal]") for w in _warnings(out))


def test_c7_still_judges_legacy_review_recommendation() -> None:
    """Back-compat: an OLD stored artifact may carry recommendation=='REVIEW' (the
    deleted verdict). C7 must still treat it as withheld so legacy fallback slots
    are scrubbed. The contract never WRITES 'REVIEW' — it only reads it here."""
    art = _artifact(
        raw_data={"market": {"current_price": 18.0}},
        structured={
            "thesis": {"price_target": None, "recommendation": "REVIEW"},
            "financial_modeling": {"implied_price": 20.35},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["financial_modeling"]["implied_price"] is None
    assert any(w.startswith("[CONTRACT/C7/internal]") for w in _warnings(out))


def test_c7_noop_when_withheld_and_all_slots_already_null() -> None:
    """A clean withheld artifact (directional verdict, no target, no resurrected
    slots) must pass through unchanged — C7 only fires on a SURVIVING headline."""
    art = _artifact(
        raw_data={"market": {"current_price": 18.0}},
        structured={
            "thesis": {"price_target": None, "recommendation": "SELL"},
            "financial_modeling": {"implied_price": None},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c7_noop_on_a_buy_with_live_fallback_slots() -> None:
    """A compliant BUY (not REVIEW) keeps its financial_modeling.implied_price —
    C7 only governs WITHHELD artifacts; it must not null a healthy fallback."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
            "financial_modeling": {"implied_price": 129.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c7_scrub_runs_on_every_hard_withhold() -> None:
    """The _withhold refactor: ANY hard withhold (here C2) must scrub the nested
    financial_modeling.implied_price too, so the C7 invariant holds for every hard
    clause — not just C7's own path."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": "DCF implies $2172.062.06 per share",  # trips C2
            },
            "valuation_synthesis": {"weighted_price": 128.0},
            "financial_modeling": {"implied_price": 129.0},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["financial_modeling"]["implied_price"] is None
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert extract_target_price(out) is None


def test_withheld_sell_thesis_passes_contract_verdict_unscrubbed() -> None:
    """Item-7 invariant: a thesis that honestly withholds its POINT target
    (price_target None) while still shipping a directional SELL verdict — with NO
    resurrected fallback slots — passes the contract un-scrubbed of its verdict
    (no C7 mutation, recommendation stays SELL). The value-integrity guardrails
    only withhold the VALUE; they never refuse the judgment."""
    art = _artifact(
        raw_data={"market": {"current_price": 50.0}},
        structured={
            "thesis": {
                "price_target": None,
                "recommendation": "SELL",
                "price_target_basis": "single-method DCF, no cross-check available",
            },
            "valuation_withheld": True,
            "valuation_synthesis": {"weighted_price": None, "methods": []},
        },
        llm_narrative={"recommendation": "SELL", "company_overview": "body"},
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["recommendation"] == "SELL"  # verdict ships
    assert out.outputs.structured["thesis"]["price_target"] is None  # value honestly absent
    assert out.outputs.llm_narrative["recommendation"] == "SELL"  # mirror preserved
    # No fallback slot to resurrect, nothing tripped → no new [CONTRACT/*] warnings.
    assert not any(w.startswith("[CONTRACT/") for w in _warnings(out))


# ── C1b: method-vs-method corroboration span ─────────────────────────────────


def _method(name: str, mid: float) -> dict:
    return {"name": name, "low": mid * 0.9, "mid": mid, "high": mid * 1.1, "source": "x"}


def test_c1b_withholds_when_methods_span_above_corroboration_limit() -> None:
    """The MU 0.69x-of-market case C1 is blind to: the headline (130 vs 188 market =
    in-band) survives C1, but the surviving method mids are 7x apart ($30 vs $210)
    — no honest blended point exists, so C1b withholds the TARGET (verdict kept)."""
    art = _artifact(
        raw_data={"market": {"current_price": 188.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "SELL"},
            "valuation_synthesis": {
                "weighted_price": 120.0,  # corroborated band → C1 passes
                "methods": [_method("dcf", 30.0), _method("comps_pe", 210.0)],  # 7x apart
            },
        },
        llm_narrative={"recommendation": "SELL"},
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert out.outputs.structured["thesis"]["recommendation"] == "SELL"  # verdict kept
    assert out.outputs.structured["valuation_withheld"] is True
    assert "C1b" in out.outputs.structured["withheld_reason"]
    assert any(w.startswith("[CONTRACT/C1b]") for w in _warnings(out))


def test_c1b_passes_when_methods_corroborate_within_2x() -> None:
    """Methods within the 2x corroboration span (max/min = 1.5x) → C1b silent."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {
                "weighted_price": 128.0,
                "methods": [_method("dcf", 120.0), _method("comps_pe", 180.0)],  # 1.5x
            },
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c1b_noop_on_single_method_or_bare_names() -> None:
    """C1b needs ≥2 numeric mids to measure a span: a single method, or method
    entries that are bare names (no mid), are a no-op (never a spurious withhold)."""
    single = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 150.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe — single-method, no cross-check available",
            },
            "valuation_synthesis": {"weighted_price": None, "methods": [_method("dcf", 150.0)]},
        },
    )
    before_single = single.model_dump()
    assert enforce_artifact_contract(single).model_dump() == before_single

    bare = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 150.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe — single-method, no cross-check available",
            },
            "valuation_synthesis": {"weighted_price": None, "methods": ["dcf", "comps_pe"]},
        },
    )
    before_bare = bare.model_dump()
    assert enforce_artifact_contract(bare).model_dump() == before_bare


def test_c1b_noop_when_no_per_share_headline() -> None:
    """No target (lbo / comps / withheld) → C1b is structurally a no-op."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "valuation_synthesis": {
                "weighted_price": None,
                "methods": [_method("dcf", 30.0), _method("comps_pe", 210.0)],  # 7x but no target
            },
        },
        type_="comps",
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


# ── C4: currency caliber ─────────────────────────────────────────────────────


def test_c4_withholds_on_currency_family_blocked_finding_with_surviving_target() -> None:
    """A cross_currency_ratio blocked_field finding survived in numeric_audit yet a
    headline target still rides — withhold (the type-agnostic missed-withhold
    backstop for mixed-currency P/E like SAP / TSM / TM)."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
            "currency": {"quote_currency": "USD", "reporting_currency": "EUR"},
            "numeric_audit": {
                "findings": [
                    {
                        "field_key": "pe_ratio",
                        "check": "cross_currency_ratio",
                        "severity": "blocked_field",
                        "evidence": "pe_ratio formed across USD/EUR",
                    }
                ]
            },
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert out.outputs.structured["valuation_withheld"] is True
    assert any(w.startswith("[CONTRACT/C4]") for w in _warnings(out))


def test_c4_noop_when_currency_finding_is_only_review_severity() -> None:
    """A review-severity currency finding does NOT block — C4 only withholds on a
    blocked_field; a review caliber note is left to flow as-is."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
            "currency": {"quote_currency": "USD", "reporting_currency": "EUR"},
            "numeric_audit": {
                "findings": [
                    {
                        "field_key": "pe_ratio",
                        "check": "cross_currency_ratio",
                        "severity": "review",
                        "evidence": "advisory only",
                    }
                ]
            },
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c4_fires_on_currency_block_missing_caliber_keys() -> None:
    """A per-share headline exists and a currency dict is present but missing
    quote/reporting → a caliber gap (the tags weren't resolved) → withhold."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
            "currency": {"quote_currency": "USD"},  # reporting_currency missing
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert any(w.startswith("[CONTRACT/C4]") for w in _warnings(out))


def test_c4_noop_when_no_numeric_audit_and_currency_complete() -> None:
    """dcf / ddm carry no numeric_audit currency findings and a complete currency
    block (or none) → C4 is a no-op, never a spurious withhold."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 130.0, "recommendation": "BUY"},
            "valuation_synthesis": {"weighted_price": 128.0},
            "currency": {"quote_currency": "USD", "reporting_currency": "USD"},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


# ── C6: single-method no-cross-check disclosure (SOFT) ───────────────────────


def test_c6_notes_single_method_basis_without_disclosure() -> None:
    """Single method survived (weighted_price None) + live target, but the basis
    fails to disclose it lacks a cross-check → SOFT [CONTRACT/C6/note]. Target is
    NOT withheld — the analyst still gets the number, just told it has no second
    opinion."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 150.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe 18x on FY1 EPS",  # no disclosure
            },
            "valuation_synthesis": {"weighted_price": None},  # single method
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] == 150.0  # NOT withheld
    assert "valuation_withheld" not in out.outputs.structured
    assert any(w.startswith("[CONTRACT/C6/note]") for w in _warnings(out))


def test_c6_silent_when_disclosure_present() -> None:
    """When the basis already discloses 'no cross-check available' (upstream
    resolve_canonical_thesis writes it), C6 is silent."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 150.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe 18x — single-method, no cross-check available",
            },
            "valuation_synthesis": {"weighted_price": None},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c6_silent_when_multi_method() -> None:
    """A corroborated multi-method target (weighted_price present) doesn't need the
    single-method disclosure → C6 silent."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 150.0,
                "recommendation": "BUY",
                "price_target_basis": "DCF + comps weighted",
            },
            "valuation_synthesis": {"weighted_price": 148.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


# ── C3: basis conclusion amount == headline ──────────────────────────────────


def test_c3_withholds_when_basis_conclusion_contradicts_headline() -> None:
    """basis 'comps_pe 36.9x → $999' but headline price_target=130 — the cue-
    anchored conclusion amount ($999, after '→') contradicts the headline → withhold."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe 36.9x → $999",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    out = enforce_artifact_contract(art)
    assert out.outputs.structured["thesis"]["price_target"] is None
    assert out.outputs.structured["valuation_withheld"] is True
    assert any(w.startswith("[CONTRACT/C3]") for w in _warnings(out))


def test_c3_noop_when_conclusion_equals_headline() -> None:
    """basis conclusion amount == headline (within tolerance) → no contradiction."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": "comps_pe 18x → target $130.00",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c3_noop_within_rounding_tolerance() -> None:
    """A rounded restatement ('$276' against headline 276.43) is inside the shared
    NARRATIVE_DRIFT_TOLERANCE → not a contradiction."""
    art = _artifact(
        raw_data={"market": {"current_price": 200.0}},
        structured={
            "thesis": {
                "price_target": 276.43,
                "recommendation": "BUY",
                "price_target_basis": "DCF → target $276",
            },
            "valuation_synthesis": {"weighted_price": 270.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before


def test_c3_noop_when_dollar_amounts_have_no_conclusion_cue() -> None:
    """THE FALSE-POSITIVE GUARD: the basis cites per-method mids ($5.88, $19.54)
    with NO conclusion cue (no →, no 'target'/'目标') — C3 must NOT guess one of
    them is the conclusion. Headline 130 differs from both, yet C3 is a NO-OP."""
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {
                "price_target": 130.0,
                "recommendation": "BUY",
                "price_target_basis": "DCF says $5.88, comps say $19.54, they disagree",
            },
            "valuation_synthesis": {"weighted_price": 128.0},
        },
    )
    before = art.model_dump()
    out = enforce_artifact_contract(art)
    assert out.model_dump() == before
