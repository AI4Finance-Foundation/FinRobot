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
    assert structured["thesis"]["recommendation"] == "REVIEW"
    assert structured["valuation_withheld"] is True
    assert structured["withheld_reason"] == "contract_C1"
    assert extract_target_price(art) is None  # C7 invariant: truly gone
    assert any(w.startswith("[CONTRACT/C1]") for w in _warnings(art))


def test_c1_neutralises_narrative_conclusion_keeps_body() -> None:
    """Q2 (locked): withhold neutralises the conclusion mirror fields but
    preserves the analysis body verbatim + stamps provenance."""
    art = enforce_artifact_contract(_mu_2172_artifact())
    narrative = art.outputs.llm_narrative
    assert narrative["recommendation"] == "REVIEW"
    assert narrative["tagline"] is None
    assert narrative["company_overview"] == "Micron is a memory maker."  # body untouched
    assert any(w.startswith("[CONTRACT/withheld]") for w in _warnings(art))


def test_c1_passes_target_inside_single_method_band() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 100.0}},
        structured={
            "thesis": {"price_target": 180.0, "recommendation": "BUY"},  # 1.8x < 2x
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
    the already-appended warnings."""
    once = enforce_artifact_contract(_mu_2172_artifact())
    snapshot = copy.deepcopy(once.model_dump())
    twice = enforce_artifact_contract(once)
    # target stays None, still REVIEW; warnings already carry the evidence.
    assert twice.outputs.structured["thesis"]["price_target"] is None
    assert twice.outputs.structured["thesis"]["recommendation"] == "REVIEW"
    assert twice.model_dump()["outputs"]["structured"] == snapshot["outputs"]["structured"]
