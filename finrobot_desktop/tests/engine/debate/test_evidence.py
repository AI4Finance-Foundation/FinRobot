"""TDD tests for build_evidence_set (Task 2, Plan 1)."""

from finrobot.engine.debate.evidence import build_evidence_set


def _structured() -> dict:
    return {
        "valuation_synthesis": {
            "methods": [
                {"name": "DCF", "low": 150, "mid": 176, "high": 200, "confidence": 0.6, "source": "dcf@v2"},
                {"name": "Comps", "low": 180, "mid": 244, "high": 300, "confidence": 0.4, "source": "multiples@v1"},
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
    assert ids["synthesis.upside_downside"].value == -0.0376
    assert "method.DCF.mid" in ids and ids["method.DCF.mid"].value == 176
    assert "method.Comps.mid" in ids and ids["method.Comps.mid"].value == 244
    assert es.current_price == 211.14
    assert es.reliable is True


def test_missing_synthesis_yields_empty_but_valid_set() -> None:
    es = build_evidence_set({}, artifact_id="run-x")
    assert es.items == []
    assert es.reliable is False
