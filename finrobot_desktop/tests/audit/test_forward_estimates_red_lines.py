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
from datetime import date
from pathlib import Path

from finrobot.engine.compute.operators.forward_estimates import (
    ForwardFinancials,
    get_forward_financials,
)

# Fixed as_of so forward-period selection is deterministic across calendar time.
AS_OF = date(2026, 6, 1)

ROOT = Path(__file__).resolve().parents[2]
LEAF_SRC = ROOT / "finrobot" / "engine" / "compute" / "operators" / "forward_estimates.py"
FINROBOT = ROOT / "finrobot"


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
        Path("finrobot/engine/compute/operators/forward_estimates.py"),
        Path("tests/audit/test_forward_estimates_red_lines.py"),
        Path("tests/unit/test_forward_estimates.py"),
        # Aggregator consumes the leaf's output by parameter, so a string
        # mention of `forward_eps=` etc. there is the contract surface — not
        # a violation. Listing it keeps the audit explicit instead of magic.
        Path("finrobot/engine/compute/operators/valuation_aggregator.py"),
        Path("tests/audit/test_valuation_aggregator.py"),
        Path("tests/routes/test_valuation_routes.py"),
        # routes/valuation.py wires the route handler to the aggregator —
        # passes forward_* by kwarg name, never invents the numbers.
        Path("finrobot/routes/valuation.py"),
        # _helpers.py is the pipeline-side mirror of routes/valuation.py: it
        # wires build_valuation_synthesis → aggregate_valuation, passing the
        # leaf's already-minted forward EBITDA straight through by kwarg name
        # (gated single-currency). Like the route, it never derives the number.
        Path("finrobot/engine/pipelines/_helpers.py"),
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
        for py in FINROBOT.rglob("*.py"):
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
        assert any("volatility" in w for w in out.warnings)

    def test_fmp_consensus_path_promotes_confidence(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 12.5},
            fmp_analyst_estimates={
                "rows": [
                    {
                        "date": "2026-12-31",
                        "epsAvg": 13.0,
                        "revenueAvg": 1.2e11,
                        "ebitdaAvg": 4.5e10,
                    }
                ]
            },
            as_of=AS_OF,
        )
        assert out.forward_eps == 13.0
        assert out.forward_ebitda == 4.5e10
        # FMP analyst-estimates carries no FCF figure in any API generation —
        # forward_fcf is always None on this path.
        assert out.forward_fcf is None
        assert out.confidence == "high"
        assert "FMP" in out.source
        assert out.fiscal_period == "2026-12-31"

    def test_fmp_surfaces_forward_net_income_for_market_cap_pe(self) -> None:
        # Peer comps compute forward P/E as market_cap / forward_net_income (the
        # CompanyFinancials peer model carries market_cap, not price/shares). The
        # leaf must surface FY1 consensus net income so no other module reparses
        # the FMP row. None on a row that omits it.
        with_ni = get_forward_financials(
            ticker="AMD",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-12-31", "epsAvg": 7.5, "netIncomeAvg": 1.22e10}]
            },
            as_of=AS_OF,
        )
        assert with_ni.forward_net_income == 1.22e10
        without_ni = get_forward_financials(
            ticker="AMD",
            yf_info=None,
            fmp_analyst_estimates={"rows": [{"date": "2026-12-31", "epsAvg": 7.5}]},
            as_of=AS_OF,
        )
        assert without_ni.forward_net_income is None

    def test_fmp_real_shape_no_fcf_is_high_when_ebitda_present(self) -> None:
        # Real FMP /analyst-estimates shape: it never returns FCF, but DOES
        # return EBITDA. confidence must not be gated on the (永远缺席的) FCF,
        # else 'high' is unreachable in production. (Live AAPL FY2026 row.)
        out = get_forward_financials(
            ticker="AAPL",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [
                    {
                        "date": "2026-09-27",
                        "epsAvg": 8.74725,
                        "revenueAvg": 477166486632,
                        "ebitdaAvg": 172226064656,
                        # no FCF figure — FMP omits it in every API generation
                    }
                ]
            },
            as_of=AS_OF,
        )
        assert out.forward_ebitda == 172226064656
        assert out.forward_fcf is None
        assert out.confidence == "high"

    def test_fmp_with_only_eps_revenue_is_medium_confidence(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [
                    {
                        "epsAvg": 13.0,
                        "revenueAvg": 1.2e11,
                    }
                ]
            },
            as_of=AS_OF,
        )
        assert out.confidence == "medium"

    def test_fmp_empty_rows_falls_back_to_unavailable(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info=None,
            fmp_analyst_estimates={"rows": []},
            as_of=AS_OF,
        )
        assert out.confidence == "unavailable"

    def test_fmp_empty_rows_falls_back_to_yfinance_forward_eps(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forwardEps": 12.5},
            fmp_analyst_estimates={"rows": []},
            as_of=AS_OF,
        )
        assert out.forward_eps == 12.5
        assert out.forward_revenue is None
        assert out.forward_ebitda is None
        assert out.forward_fcf is None
        assert out.confidence == "low"
        assert "yfinance" in out.source
        assert any("FMP analyst-estimates unavailable" in w for w in out.warnings)

    def test_fmp_malformed_rows_falls_back_to_yfinance_forward_eps(self) -> None:
        out = get_forward_financials(
            ticker="NVDA",
            yf_info={"forward_eps": 11.0},
            fmp_analyst_estimates={"rows": ["bad-row"]},
            as_of=AS_OF,
        )
        assert out.forward_eps == 11.0
        assert out.confidence == "low"


class TestForwardPeriodSelection:
    """FMP returns many fiscal years; the leaf must pick FY1 (nearest upcoming
    fiscal-year-end), not whatever happens to sit at rows[0]. Using a 4-years-out
    estimate as the 'forward' P/E numerator would be a wrong number."""

    _MULTI_YEAR = {
        "rows": [
            # FMP returns newest/farthest-future first — rows[0] is FY+3.
            {"date": "2029-09-30", "epsAvg": 12.0, "revenueAvg": 5.5e11},
            {"date": "2028-09-30", "epsAvg": 11.0, "revenueAvg": 5.2e11},
            {"date": "2027-09-30", "epsAvg": 10.0, "revenueAvg": 4.9e11},
            {"date": "2026-09-30", "epsAvg": 8.6, "revenueAvg": 4.65e11},
            {"date": "2025-09-30", "epsAvg": 7.4, "revenueAvg": 4.0e11},
        ]
    }

    def test_picks_nearest_upcoming_fiscal_year_not_first_row(self) -> None:
        out = get_forward_financials(
            ticker="AAPL", yf_info=None, fmp_analyst_estimates=self._MULTI_YEAR, as_of=AS_OF
        )
        # FY1 relative to 2026-06-01 is the 2026-09-30 row, EPS 8.6 — matches the
        # external AAPL FY2026 consensus (~$8.5–8.8), NOT the 2029 row's 12.0.
        assert out.forward_eps == 8.6
        assert out.forward_revenue == 4.65e11
        assert out.fiscal_period == "2026-09-30"

    def test_rolls_to_next_fy_after_current_fy_end_passes(self) -> None:
        # Once we're past 2026-09-30, FY1 becomes 2027-09-30.
        out = get_forward_financials(
            ticker="AAPL",
            yf_info=None,
            fmp_analyst_estimates=self._MULTI_YEAR,
            as_of=date(2026, 10, 1),
        )
        assert out.forward_eps == 10.0
        assert out.fiscal_period == "2027-09-30"

    def test_all_estimates_in_past_flags_stale(self) -> None:
        out = get_forward_financials(
            ticker="AAPL",
            yf_info=None,
            fmp_analyst_estimates=self._MULTI_YEAR,
            as_of=date(2030, 1, 1),
        )
        # No future FY left — fall back to the most recent and warn rather than
        # silently serve a stale "forward" number.
        assert out.fiscal_period == "2029-09-30"
        assert any("stale" in w for w in out.warnings)

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


class TestForwardFxMismatchGuard:
    """FMP /analyst-estimates ships netIncomeAvg/epsAvg in the issuer's NATIVE
    reporting currency with NO currency field (live-verified UMC/TSM/AAPL/SONY,
    2026-06-14). For an ADR whose canonical FINANCIALS got FX-normalized to USD,
    the comps gate (reporting==quote, USD==USD) can't see the row is native, so a
    magnitude guard against currency-clean USD trailing anchors is the only catch.

    Fixtures use the REAL probed payloads (rows from the live /analyst-estimates
    response), not values reverse-engineered from the implementation."""

    # Live UMC /analyst-estimates FY2026 row (probe 2026-06-14): native TWD.
    # Trailing anchors are the USD-canonical figures (FMP financials FX-normalized).
    _UMC_ROW = {"date": "2026-12-31", "epsAvg": 23.1096, "netIncomeAvg": 57704671223.0}
    _UMC_TRAIL_NI_USD = 1_585_291_390.0  # canonical net income (USD)
    _UMC_TRAIL_REV_USD = 7_615_689_016.0  # canonical revenue (USD)

    # Live SONY FY row: native JPY netIncomeAvg ~1.25e12, and trailing NI is
    # NEGATIVE (one-off loss) so the NI-ratio leg can't form — the revenue leg
    # must catch it (net income can't exceed revenue).
    _SONY_ROW = {"date": "2026-03-31", "epsAvg": 209.06, "netIncomeAvg": 1_249_350_000_000.0}
    _SONY_TRAIL_NI_USD = -2_144_712_202.0
    _SONY_TRAIL_REV_USD = 78_670_000_000.0

    def test_native_currency_forward_ni_abstained_by_ni_ratio(self) -> None:
        # UMC: forward NI 57.7B (TWD) vs trailing 1.59B (USD) = 36x => abstain.
        out = get_forward_financials(
            ticker="UMC",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._UMC_ROW]},
            as_of=AS_OF,
            trailing_net_income_usd=self._UMC_TRAIL_NI_USD,
            trailing_revenue_usd=self._UMC_TRAIL_REV_USD,
        )
        assert out.forward_net_income is None
        assert out.forward_eps is None
        assert out.forward_ebitda is None
        assert out.confidence == "unavailable"
        assert any("abstained" in w for w in out.warnings)

    def test_native_currency_forward_ni_abstained_by_revenue_leg_when_loss_maker(self) -> None:
        # SONY: negative trailing NI (no NI ratio) but native-JPY forward NI 1.25e12
        # dwarfs USD revenue 78.7B => the revenue leg abstains it. This is the hole
        # the NI-ratio-only guard left (it shipped forward_pe=0.10x before).
        out = get_forward_financials(
            ticker="SONY",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._SONY_ROW]},
            as_of=AS_OF,
            trailing_net_income_usd=self._SONY_TRAIL_NI_USD,
            trailing_revenue_usd=self._SONY_TRAIL_REV_USD,
        )
        assert out.forward_net_income is None
        assert out.forward_eps is None
        assert out.confidence == "unavailable"
        assert any("revenue" in w for w in out.warnings)

    def test_clean_usd_issuer_not_abstained(self) -> None:
        # AAPL FY2026 (probe): forward NI 131.6B vs trailing 122.6B = 1.07x => kept.
        out = get_forward_financials(
            ticker="AAPL",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-09-27", "epsAvg": 8.75, "netIncomeAvg": 131_623_452_796.0}]
            },
            as_of=AS_OF,
            trailing_net_income_usd=122_575_000_000.0,
            trailing_revenue_usd=451_442_000_000.0,
        )
        assert out.forward_net_income == 131_623_452_796.0
        assert out.forward_eps == 8.75

    def test_cyclical_recovery_not_abstained(self) -> None:
        # MU (probe): forward NI 67.1B vs trailing 24.1B = 2.78x (NI leg), and
        # 1.15x of trailing revenue 58.1B (revenue leg). A real cyclical upcycle —
        # both legs must stay UNDER threshold so MU is kept. This is the false-
        # positive boundary: a too-tight guard would clip MU.
        out = get_forward_financials(
            ticker="MU",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-08-31", "epsAvg": 59.43, "netIncomeAvg": 67_100_000_000.0}]
            },
            as_of=AS_OF,
            trailing_net_income_usd=24_110_000_000.0,
            trailing_revenue_usd=58_120_000_000.0,
        )
        assert out.forward_net_income == 67_100_000_000.0

    def test_guard_inert_without_anchors(self) -> None:
        # No anchors supplied (legacy callers) => guard is inert, value passes
        # through. The native-TWD UMC row is NOT abstained without an anchor — the
        # guard never fabricates a verdict from nothing.
        out = get_forward_financials(
            ticker="UMC",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._UMC_ROW]},
            as_of=AS_OF,
        )
        assert out.forward_net_income == 57704671223.0

    def test_tsm_usd_forward_with_anchors_not_abstained(self) -> None:
        # TSM's /analyst-estimates already returns USD (probe: NI ratio 1.33x) even
        # though it's a TWD ADR — proving the per-ticker inconsistency that defeats
        # a currency-tag gate. With anchors the guard must KEEP it (ratio in band).
        out = get_forward_financials(
            ticker="TSM",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-12-31", "epsAvg": 15.71, "netIncomeAvg": 81_460_000_000.0}]
            },
            as_of=AS_OF,
            trailing_net_income_usd=61_169_840_617.0,
            trailing_revenue_usd=130_140_000_000.0,
        )
        assert out.forward_net_income == 81_460_000_000.0
        assert out.forward_eps == 15.71

    # Live KOF /analyst-estimates FY2026 row (probe 2026-07-06): native MXN. FMP
    # UNDER-reports netIncomeAvg here — 2.54B MXN vs revenueAvg 308B = 0.8% implied
    # net margin vs KOF's real ~8% (≈10× low) — so ni_ratio 2.78 and rev_ratio 0.20
    # both stay IN-BAND while the native-MXN epsAvg 120.98 leaks a fwd P/E 8.7 (= USD
    # market cap / MXN net income). Anchors are the canonical USD trailing figures.
    _KOF_ROW = {"date": "2026-12-31", "epsAvg": 120.98476, "netIncomeAvg": 2_541_684_254.0}
    _KOF_TRAIL_NI_USD = 913_425_199.02  # canonical net income (USD)
    _KOF_TRAIL_REV_USD = 12_588_199_212.26  # canonical revenue (USD)
    _KOF_TRAIL_EPS_USD = 4.34792  # 913_425_199.02 / 210_083_226 canonical ADR shares

    def test_underreported_native_ni_abstained_by_eps_leg(self) -> None:
        # KOF: ni_ratio 2.78 (< 6) and rev_ratio 0.20 (< 3) both pass — the two
        # existing legs are blind to an UNDER-reported netIncomeAvg. The eps leg
        # (native epsAvg 120.98 vs USD trailing EPS 4.35 = 27.8×) is the only catch.
        out = get_forward_financials(
            ticker="KOF",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._KOF_ROW]},
            as_of=AS_OF,
            trailing_net_income_usd=self._KOF_TRAIL_NI_USD,
            trailing_revenue_usd=self._KOF_TRAIL_REV_USD,
            trailing_eps_usd=self._KOF_TRAIL_EPS_USD,
        )
        assert out.forward_net_income is None
        assert out.forward_eps is None
        assert out.forward_ebitda is None
        assert out.confidence == "unavailable"
        assert any("EPS" in w for w in out.warnings)

    def test_kof_ni_rev_legs_alone_leak_without_eps_anchor(self) -> None:
        # The SAME KOF row WITHOUT the eps anchor: the ni/rev legs alone let the
        # native-MXN consensus through (the bug this leg fixes). Pins that the eps
        # leg is load-bearing, not redundant with legs 1–2.
        out = get_forward_financials(
            ticker="KOF",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._KOF_ROW]},
            as_of=AS_OF,
            trailing_net_income_usd=self._KOF_TRAIL_NI_USD,
            trailing_revenue_usd=self._KOF_TRAIL_REV_USD,
        )
        assert out.forward_net_income == 2_541_684_254.0
        assert out.forward_eps == 120.98476

    def test_clean_us_issuer_eps_leg_in_band(self) -> None:
        # AAPL FY2026 (probe 2026-07-06): epsAvg 8.755 vs USD trailing EPS 8.346
        # (122.575B NI / 14.687B shares) = 1.05× — the eps leg must KEEP it. This is
        # the false-positive boundary: eps growth ≈ NI growth for a clean issuer, so
        # 6.0 (which clears MU's 2.78 cyclical NI jump) clears this comfortably too.
        out = get_forward_financials(
            ticker="AAPL",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-09-27", "epsAvg": 8.755, "netIncomeAvg": 131_817_013_388.5}]
            },
            as_of=AS_OF,
            trailing_net_income_usd=122_575_000_000.0,
            trailing_revenue_usd=451_442_000_000.0,
            trailing_eps_usd=8.345613737421493,
        )
        assert out.forward_net_income == 131_817_013_388.5
        assert out.forward_eps == 8.755

    def test_legit_usd_adr_eps_leg_in_band(self) -> None:
        # TSM USD vintage + eps anchor: epsAvg 15.71 vs USD trailing EPS 11.80
        # (61.17B NI / 5.186B ADR shares) = 1.33× — the eps leg keeps a legitimately
        # USD-denominated ADR forward, so it does not false-trip when FMP ships USD.
        out = get_forward_financials(
            ticker="TSM",
            yf_info=None,
            fmp_analyst_estimates={
                "rows": [{"date": "2026-12-31", "epsAvg": 15.71, "netIncomeAvg": 81_460_000_000.0}]
            },
            as_of=AS_OF,
            trailing_net_income_usd=61_169_840_617.0,
            trailing_revenue_usd=130_140_000_000.0,
            trailing_eps_usd=11.7952,
        )
        assert out.forward_net_income == 81_460_000_000.0
        assert out.forward_eps == 15.71

    def test_eps_leg_inert_on_nonpositive_trailing_eps(self) -> None:
        # A loss-maker (or a share-less snapshot) forms no clean trailing EPS, so a
        # non-positive anchor leaves the eps leg inert — the revenue leg still covers
        # the loss-maker case (SONY). Guards against dividing by a ≤0 denominator.
        out = get_forward_financials(
            ticker="SONY",
            yf_info=None,
            fmp_analyst_estimates={"rows": [self._SONY_ROW]},
            as_of=AS_OF,
            trailing_net_income_usd=self._SONY_TRAIL_NI_USD,
            trailing_revenue_usd=self._SONY_TRAIL_REV_USD,
            trailing_eps_usd=-0.36,  # negative trailing EPS → eps leg must not fire
        )
        # Still abstained, but via the REVENUE leg (not the eps leg on a ≤0 anchor).
        assert out.forward_net_income is None
        assert any("revenue" in w for w in out.warnings)
