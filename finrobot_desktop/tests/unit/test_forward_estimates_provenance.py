"""Forward-estimate provenance persisted into the equity_research artifact.

The forward comps row's NUMBERS already ride inside valuation_synthesis; the
report additionally needs the *provenance* (which fiscal year, what source, how
confident) to frozenly label the row "FY2026E" and footnote its source without a
live /api/valuation/aggregate refetch. ``_forward_estimates_provenance`` is the
pure slice that turns the pipeline's ForwardFinancials into that slim block.
"""

from __future__ import annotations

from finrobot.artifact.builders import _forward_estimates_provenance
from finrobot.engine.compute.operators.forward_estimates import ForwardFinancials


def _forward(**overrides: object) -> ForwardFinancials:
    base: dict[str, object] = {
        "ticker": "AAPL",
        "forward_eps": 7.5,
        "forward_revenue": 4.5e11,
        "forward_ebitda": 1.2e11,
        "forward_fcf": 9.0e10,
        "confidence": "high",
        "source": "FMP /v3/analyst-estimates (FY1 consensus)",
        "warnings": [],
        "fiscal_period": "2026-09-30",
    }
    base.update(overrides)
    return ForwardFinancials(**base)  # type: ignore[arg-type]


def test_persists_slim_provenance_when_a_forward_estimate_landed() -> None:
    prov = _forward_estimates_provenance(_forward())
    assert prov is not None
    assert prov == {
        "fiscal_period": "2026-09-30",
        "source": "FMP /v3/analyst-estimates (FY1 consensus)",
        "confidence": "high",
    }
    # Only provenance — never the numbers (those live in valuation_synthesis).
    assert "forward_eps" not in prov
    assert "forward_ebitda" not in prov


def test_none_when_no_forward_estimate_landed() -> None:
    # The yfinance/unavailable degrade carries no fiscal_period — persist nothing
    # rather than an empty provenance block that would render a bare footnote.
    assert _forward_estimates_provenance(_forward(fiscal_period=None)) is None
    assert _forward_estimates_provenance(None) is None


def test_blank_source_or_confidence_coerces_to_none() -> None:
    prov = _forward_estimates_provenance(_forward(source="", confidence="unavailable"))
    assert prov is not None
    assert prov["source"] is None
    assert prov["confidence"] == "unavailable"
    assert prov["fiscal_period"] == "2026-09-30"
