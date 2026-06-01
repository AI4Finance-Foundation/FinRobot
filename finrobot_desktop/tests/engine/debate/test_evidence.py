"""TDD tests for build_evidence_set (Task 2, Plan 1)."""

import pytest

from finrobot.engine.debate.evidence import build_evidence_set


def _structured() -> dict:
    return {
        "valuation_synthesis": {
            "methods": [
                {
                    "name": "DCF",
                    "low": 150,
                    "mid": 176,
                    "high": 200,
                    "confidence": 0.6,
                    "source": "dcf@v2",
                },
                {
                    "name": "Comps",
                    "low": 180,
                    "mid": 244,
                    "high": 300,
                    "confidence": 0.4,
                    "source": "multiples@v1",
                },
            ],
            "weighted_price": 203.2,
            "current_price": 211.14,
            "upside_downside": -0.0376,
            "outlier_methods": [],
            "warnings": [],
            "reliable": True,
        }
    }


def test_extracts_synthesis_and_methods() -> None:
    es = build_evidence_set(_structured(), artifact_id="run-9")
    ids = es.by_id()
    assert "synthesis.upside_downside" in ids
    # ratio -0.0376 → percent magnitude -3.76 (unit is "%")
    assert ids["synthesis.upside_downside"].value == pytest.approx(-3.76)
    assert "method.DCF.mid" in ids and ids["method.DCF.mid"].value == 176
    assert "method.Comps.mid" in ids and ids["method.Comps.mid"].value == 244
    assert es.current_price == 211.14
    assert es.reliable is True


def test_missing_synthesis_yields_empty_but_valid_set() -> None:
    es = build_evidence_set({}, artifact_id="run-x")
    assert es.items == []
    assert es.reliable is False


def test_method_assumptions_flow_into_evidence_provenance() -> None:
    """A method's assumptions string must reach Evidence.provenance so the debate
    can cite the price with its conditions (the $73-needs-its-prefix fix)."""
    structured = _structured()
    structured["valuation_synthesis"]["methods"][0]["assumptions"] = (
        "WACC 16.6% · 5年增长 40%→2.5% · β2.24"
    )
    es = build_evidence_set(structured, artifact_id="run-9")
    dcf_ev = es.by_id()["method.DCF.mid"]
    assert dcf_ev.provenance == {"assumptions": "WACC 16.6% · 5年增长 40%→2.5% · β2.24"}
    # A method without assumptions leaves provenance None — no fabricated prefix.
    assert es.by_id()["method.Comps.mid"].provenance is None
