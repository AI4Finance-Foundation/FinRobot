"""Audit invariants for v5 §6.4.1 forward_estimates leaf (PR4c).

Spec §6.4.1 promotes ``forward_estimates.py`` to a red-line module: no other
code may produce a forward EPS / EBITDA / FCF number. The aggregator,
routes, pipelines, and any future caller must accept whatever this leaf
returns — including unavailable — and degrade UI accordingly.

Three contracts pinned:

1. Leaf isolation — no providers, no LLM, no upper-layer imports.
2. Single entry point — only ``get_forward_financials`` ships data; no
   other module is allowed to compute forward EPS / EBITDA / FCF directly.
3. Graceful degradation — missing FMP wiring returns ``ConfidenceLevel
   == "low"`` with Chinese warnings, never raises.
"""

from __future__ import annotations

import re
from pathlib import Path

from finrobot.engine.compute.forward_estimates import (
    ForwardFinancials,
    get_forward_financials,
)

ROOT = Path(__file__).resolve().parents[2]
LEAF_SRC = ROOT / "finrobot" / "engine" / "compute" / "forward_estimates.py"
FINAGENT = ROOT / "finrobot"


# ---------------------------------------------------------------------------
# Source-level invariants
# ---------------------------------------------------------------------------


class TestLeafIsolation:
    def test_no_forbidden_imports(self) -> None:
        src = LEAF_SRC.read_text()
        forbidden = (
            "from finrobot.engine.pipelines",
            "from finrobot.engine.agents",
            "from finrobot.engine.orchestrator",
            "from finrobot.engine.data",
            "from finrobot.artifact",
            "import pydantic_ai",
            "from pydantic_ai",
            "import openai",
            "import yfinance",
            "import fmpsdk",
            "import finnhub",
            "import requests",
            "import httpx",
        )
        violations = [
            pat for pat in forbidden if re.search(rf"^\s*{re.escape(pat)}", src, re.MULTILINE)
        ]
        assert not violations, f"forward_estimates leaks: {violations}"


# ---------------------------------------------------------------------------
# Single entry point — no other file may invent forward EPS / EBITDA / FCF
# ---------------------------------------------------------------------------


class TestSingleEntryPoint:
    """Only forward_estimates.py is allowed to mint forward.* numbers.

    Catches drift like a route reaching into yfinance.info["forwardEps"] on
    its own, or a pipeline guessing forward EBITDA = revenue * 0.3.
    """

    _ALLOWED_FILES = {
        # The leaf itself + its tests
        Path("finrobot/engine/compute/forward_estimates.py"),
        Path("tests/audit/test_forward_estimates_red_lines.py"),
        Path("tests/unit/test_forward_estimates.py"),
        # Aggregator consumes the leaf's output by parameter, so a string
        # mention of `forward_eps=` etc. there is the contract surface — not
        # a violation. Listing it keeps the audit explicit instead of magic.
        Path("finrobot/engine/compute/valuation_aggregator.py"),
        Path("tests/audit/test_valuation_aggregator.py"),
        Path("tests/routes/test_valuation_routes.py"),
        # routes/valuation.py wires the route handler to the aggregator —
        # passes forward_* by kwarg name, never invents the numbers.
        Path("finrobot/routes/valuation.py"),
        # yfinance provider is allowed to surface "forward_eps" through its
        # raw dict (the leaf reads from there) — but it must not derive
        # forward EBITDA / FCF.
        Path("finrobot/engine/data/providers/yfinance_provider.py"),
    }

    def test_no_other_file_writes_forward_revenue_or_forward_ebitda(self) -> None:
        # Patterns that would indicate someone is computing forward EBITDA /
        # FCF / revenue outside the leaf. We allow `forward_eps` reads (just
        # passing through from yfinance) but not derived consensus numbers.
        forbidden_patterns = (
            re.compile(r"\bforward_ebitda\s*="),
            re.compile(r"\bforward_fcf\s*="),
            re.compile(r"\bforward_revenue\s*="),
        )
        violations: list[str] = []
        for py in FINAGENT.rglob("*.py"):
            rel = py.relative_to(ROOT)
            if rel in self._ALLOWED_FILES:
                continue
            text = py.read_text()
            for pat in forbidden_patterns:
                for match in pat.finditer(text):
                    lineno = text[: match.start()].count("\n") + 1
                    violations.append(f"  {rel}:{lineno} writes {match.group(0)!r}")
        assert not violations, (
            "Only forward_estimates.py may produce forward EBITDA / FCF / revenue.\n"
            "Violations:\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Graceful-degradation contract
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_missing_yf_info_returns_unavailable(self) -> None:
        out = get_forward_financials(ticker="NVDA", yf_info=None)
        assert out.confidence == "unavailable"
        assert out.forward_eps is None
        assert out.forward_revenue is None
        assert out.warnings  # explains why
        assert isinstance(out, ForwardFinancials)

    def test_yf_info_with_forward_eps_only_returns_low_confidence(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 12.5, "forward_pe": 50},
        )
        assert out.forward_eps == 12.5
        # Without FMP we can't fill the rest.
        assert out.forward_revenue is None
        assert out.forward_ebitda is None
        assert out.forward_fcf is None
        assert out.confidence == "low"
        assert any("FMP" in w for w in out.warnings)

    def test_high_margin_volatility_downgrades_confidence(self) -> None:
        # 3-year EBITDA margins varying from 10% to 40% → stdev/mean > 20%
        volatile = [0.10, 0.35, 0.40]
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 12.5},
            historical_ebitda_margins=volatile,
        )
        assert out.confidence == "low"
        assert any("波动" in w for w in out.warnings)

    def test_fmp_consensus_path_promotes_confidence(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 12.5},
            fmp_analyst_estimates={
                "rows": [
                    {
                        "date": "2026-12-31",
                        "estimatedEpsAvg": 13.0,
                        "estimatedRevenueAvg": 1.2e11,
                        "estimatedEbitdaAvg": 4.5e10,
                        "estimatedFreeCashFlowAvg": 3.0e10,
                    }
                ]
            },
        )
        assert out.forward_eps == 13.0
        assert out.forward_ebitda == 4.5e10
        assert out.forward_fcf == 3.0e10
        assert out.confidence == "high"
        assert "FMP" in out.source

    def test_fmp_with_only_eps_revenue_is_medium_confidence(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [
                    {
                        "estimatedEpsAvg": 13.0,
                        "estimatedRevenueAvg": 1.2e11,
                    }
                ]
            },
        )
        assert out.confidence == "medium"

    def test_fmp_empty_rows_falls_back_to_unavailable(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info=None,
            fmp_analyst_estimates={"rows": []},
        )
        assert out.confidence == "unavailable"

    def test_non_numeric_eps_treated_as_missing(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": "n/a"},
        )
        assert out.forward_eps is None
        assert out.confidence == "unavailable"

    def test_zero_or_negative_eps_treated_as_missing(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 0},
        )
        assert out.forward_eps is None
        out2 = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": -2.0},
        )
        assert out2.forward_eps is None
