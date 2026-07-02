import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines import _helpers
from finrobot.engine.pipelines._helpers import _peer_override, execute_peer_analysis
from finrobot.engine.pipelines.comps import create_comps_pipeline


def _make_test_agents(output: str = "analysis output") -> dict[str, Agent]:
    agents = {}
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        agents[role] = Agent(
            TestModel(custom_output_text=output), deps_type=FinRobotDeps, defer_model_check=True
        )
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestCompsPipelineStructure:
    def test_has_exactly_3_steps(self):
        # Collapsed from 6: the old LLM peer_selection / peer_data /
        # multiples_calc / statistical_bench steps are replaced by ONE
        # deterministic statistical_bench (shared execute_peer_analysis).
        pipeline = create_comps_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 3

    def test_step_names_correct(self):
        pipeline = create_comps_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == ["target_data", "statistical_bench", "output_gen"]

    def test_target_data_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_output_gen_uses_report_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[2].agent is agents["report"]

    def test_peer_step_is_deterministic_not_llm(self):
        """Regression (determinism HIGH-3): peer multiples must come from the
        shared deterministic execute_peer_analysis (code fetches + computes),
        NOT LLM free text. The old LLM peer_data / multiples_calc steps are gone
        and statistical_bench carries the deterministic executor + structured
        validator so build_comps_artifact gets a real PeerComps."""
        from finrobot.engine.pipelines._helpers import execute_peer_analysis
        from finrobot.engine.pipelines.base import StructuredValidator

        pipeline = create_comps_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert "peer_data" not in names and "multiples_calc" not in names
        step = next(s for s in pipeline.steps if s.name == "statistical_bench")
        assert step.executor is execute_peer_analysis
        assert isinstance(step.validator, StructuredValidator)


# ---------------------------------------------------------------------------
# P1.5: execute_fn / validate_structured hook tests
# ---------------------------------------------------------------------------


def test_comps_pipeline_has_structured_validator_on_target_data():
    from finrobot.engine.pipelines.comps import create_comps_pipeline
    from finrobot.engine.pipelines.base import DefaultAgentExecutor, StructuredValidator
    from unittest.mock import MagicMock

    agents = {k: MagicMock() for k in ["data", "analysis", "modeling", "report"]}
    pipeline = create_comps_pipeline(agents)
    step = next(s for s in pipeline.steps if s.name == "target_data")
    assert not isinstance(step.executor, DefaultAgentExecutor)
    assert isinstance(step.validator, StructuredValidator)


# ---------------------------------------------------------------------------
# Custom peer override (--peers) — _peer_override parsing + execute_peer_analysis
# ---------------------------------------------------------------------------


class TestPeerOverrideParsing:
    def test_none_falls_back_to_auto_selection(self):
        # The default path passes no `peers` kwarg → None → deterministic selection.
        assert _peer_override(None) is None

    def test_empty_and_blank_yield_none(self):
        assert _peer_override("") is None
        assert _peer_override("  , ,") is None
        assert _peer_override([]) is None

    def test_comma_string_is_parsed_upper_stripped(self):
        assert _peer_override(" aapl, msft , googl ") == ["AAPL", "MSFT", "GOOGL"]

    def test_list_is_normalized(self):
        assert _peer_override(["aapl", "MSFT"]) == ["AAPL", "MSFT"]

    def test_dedupe_preserves_order(self):
        assert _peer_override("AAPL,MSFT,aapl,MSFT,GOOGL") == ["AAPL", "MSFT", "GOOGL"]

    def test_unrecognized_type_is_none(self):
        assert _peer_override(123) is None


def _deps_with_failing_layer() -> SimpleNamespace:
    async def _raise(*_a, **_k):
        raise ProviderError("forced drop")

    return SimpleNamespace(data_layer=SimpleNamespace(fetch_canonical=_raise, fetch=_raise))


class TestExecutePeerAnalysisOverride:
    def test_override_below_min_raises_clear_error(self):
        with pytest.raises(ValueError, match="needs 3-10 tickers"):
            asyncio.run(
                execute_peer_analysis(
                    None, _deps_with_failing_layer(), "", {}, "AAPL", peers=["AAPL", "MSFT"]
                )
            )

    def test_override_skips_llm_and_uses_given_tickers(self, monkeypatch):
        # If the override path leaked into automatic selection this would raise a
        # different error; instead the candidates in the failure are exactly the
        # supplied set, proving the LLM was bypassed. With every peer dropping
        # (failing layer → 0 survivors) the step raises ProviderError — typed
        # recoverable, NOT a raw ValueError that would crash the run — and its
        # message lists the supplied candidates verbatim.
        async def _boom(*_a, **_k):
            raise AssertionError("automatic peer selection must not run when --peers is given")

        monkeypatch.setattr(_helpers, "_deterministic_select_peers", _boom)
        with pytest.raises(ProviderError, match="QCOM"):
            asyncio.run(
                execute_peer_analysis(
                    None,
                    _deps_with_failing_layer(),
                    "",
                    {},
                    "AAPL",
                    peers=["NVDA", "AMD", "QCOM"],
                )
            )

    def test_peer_typeerror_drops_peer_not_crashes_step(self, monkeypatch):
        """2026-06-12 TSLA hardening: a storm-time TypeError raised by a third-party
        lib (yfinance/pandas/edgartools) on the peer-fetch path must be caught at
        the per-peer 'drop one, keep the set' boundary — not escape `asyncio.gather`
        and vaporize the whole comps step into a single-method valuation. With every
        peer raising TypeError → 0 survivors → the HANDLED ProviderError (recoverable
        by type → retries then degrades), never a raw TypeError that crashes the run.
        """

        async def _typeerror(*_a, **_k):
            raise TypeError("'NoneType' object is not subscriptable")

        async def _boom(*_a, **_k):
            raise AssertionError("automatic peer selection must not run when --peers is given")

        monkeypatch.setattr(_helpers, "_deterministic_select_peers", _boom)
        deps = SimpleNamespace(
            data_layer=SimpleNamespace(fetch_canonical=_typeerror, fetch=_typeerror)
        )
        with pytest.raises(ProviderError, match="QCOM"):
            asyncio.run(
                execute_peer_analysis(None, deps, "", {}, "AAPL", peers=["NVDA", "AMD", "QCOM"])
            )


class TestStickyPeerSelection:
    @staticmethod
    def _artifact(created_at: datetime):
        return SimpleNamespace(
            ticker="NVDA",
            meta=SimpleNamespace(created_at=created_at),
            outputs=SimpleNamespace(
                structured={
                    "peer_analysis": {
                        "peers": [
                            {"ticker": "AMD"},
                            {"ticker": "INTC"},
                            {"ticker": "QCOM"},
                            {"ticker": "AVGO"},
                            {"ticker": "TXN"},
                            {"ticker": "MRVL"},
                        ]
                    }
                }
            ),
        )

    def test_reuses_parent_artifact_peer_set(self):
        art = self._artifact(datetime.now(tz=timezone.utc))

        class Store:
            async def get(self, artifact_id):
                assert artifact_id == "art_prev"
                return art

        deps = SimpleNamespace(
            artifact_store=Store(), settings=SimpleNamespace(peer_sticky_max_age_days=7)
        )

        selection = asyncio.run(_helpers._sticky_peer_selection(deps, "art_prev", "NVDA"))

        assert selection is not None
        assert selection.tickers == ["AMD", "INTC", "QCOM", "AVGO", "TXN", "MRVL"]
        assert "Reused prior-version peer set" in selection.rationale

    def test_parent_artifact_peer_set_expires(self):
        art = self._artifact(datetime.now(tz=timezone.utc) - timedelta(days=8))

        class Store:
            async def get(self, artifact_id):
                assert artifact_id == "art_prev"
                return art

        deps = SimpleNamespace(
            artifact_store=Store(), settings=SimpleNamespace(peer_sticky_max_age_days=7)
        )

        selection = asyncio.run(_helpers._sticky_peer_selection(deps, "art_prev", "NVDA"))

        assert selection is None

    def test_zero_sticky_age_disables_reuse(self):
        art = self._artifact(datetime.now(tz=timezone.utc))

        class Store:
            async def get(self, artifact_id):
                assert artifact_id == "art_prev"
                return art

        deps = SimpleNamespace(
            artifact_store=Store(), settings=SimpleNamespace(peer_sticky_max_age_days=0)
        )

        selection = asyncio.run(_helpers._sticky_peer_selection(deps, "art_prev", "NVDA"))

        assert selection is None


def _canned_company(ticker: str):
    from finrobot.engine.models.financial import CompanyFinancials

    return CompanyFinancials(
        ticker=ticker,
        revenue=100.0,
        ebitda=20.0,
        net_income=10.0,
        market_cap=200.0,
        total_debt=30.0,
        total_cash=5.0,
        gross_margin=0.6,
        operating_margin=0.3,
        ev_ebitda=11.0,
        pe_ratio=18.0,
        ev_revenue=2.0,
    )


def _target_financial_data():
    from datetime import datetime, timezone

    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="AAPL",
        income=IncomeStatement(
            revenue=100.0, ebitda=20.0, net_income=10.0, gross_margin=0.6, operating_margin=0.3
        ),
        balance=BalanceSheet(total_debt=30.0, total_cash=5.0),
        market=MarketData(current_price=10.0, shares_outstanding=10.0, market_cap=100.0),
        valuation=ValuationMetrics(enterprise_value=125.0),
        data_source="test",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestPeerAnalysisDegradesInsteadOfCrashing:
    """Fix: a thin comp set (1..MIN-1 survivors) must NOT raise — it builds the
    thin PeerComps + a warning and lets the step validator gate it (non-critical
    → degrade). The old code raised ValueError whose graceful handling depended
    on the literal substring "429" living in its own message — brittle logic
    that crashed the run when the wording drifted."""

    def test_two_survivors_returns_thin_comps_with_warning(self, monkeypatch):
        from datetime import datetime, timezone

        from finrobot.engine.data.normalize.contracts import NormalizedFinancials, Provenance
        from finrobot.engine.models.financial import PeerComps, StepOutput

        now = datetime.now(tz=timezone.utc)
        good = NormalizedFinancials(
            ticker="X",
            revenue=100.0,
            market_cap=200.0,
            as_of=now,
            provenance=Provenance(provider="test", as_of=now, fetched_at=now),
        )

        # Survivors: A, B fetch fine; C, D drop (rate-limited). 2 < MIN(3).
        async def _fetch_canonical(_dt, ticker):
            if ticker in ("A", "B"):
                return good
            raise ProviderError(
                f"forced drop {ticker} for url "
                f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey=secret"
            )

        async def _fetch(_dt, _ticker):
            return SimpleNamespace(data={})

        deps = SimpleNamespace(
            data_layer=SimpleNamespace(fetch_canonical=_fetch_canonical, fetch=_fetch),
            settings=SimpleNamespace(fmp_api_key=""),
        )

        # Short-circuit the deterministic compute chain — we are testing the
        # thin-set control flow, not multiples math (covered by test_multiples).
        async def _id_normalize(company, **_k):
            return company

        monkeypatch.setattr(
            _helpers, "extract_company_financials", lambda _fin: _canned_company("peer")
        )
        monkeypatch.setattr(_helpers, "normalize_peer_to_usd", _id_normalize)
        monkeypatch.setattr(_helpers, "calculate_multiples", lambda c: c)
        monkeypatch.setattr(_helpers, "override_company_with_xbrl", lambda c, _x: c)

        async def _canned_target(**_k):
            return _canned_company("AAPL")

        monkeypatch.setattr(_helpers, "build_xbrl_aligned_company", _canned_target)

        ctx = {"target_data": _target_financial_data()}
        out = asyncio.run(
            execute_peer_analysis(None, deps, "", ctx, "AAPL", peers=["A", "B", "C", "D"])
        )

        # No raise — degraded StepOutput with a 2-peer PeerComps + thin warning.
        assert isinstance(out, StepOutput)
        assert isinstance(out.structured, PeerComps)
        assert len(out.structured.peers) == 2
        assert any("Thin comp set" in w for w in out.structured.warnings)
        warning_blob = " ".join(out.structured.warnings)
        assert "Peers excluded" in warning_blob
        assert "apikey" not in warning_blob
        assert "for url" not in warning_blob
        assert "financialmodelingprep.com" not in warning_blob

    def test_cap_trimmed_peer_is_named_not_silently_dropped(self, monkeypatch):
        """The screen over-selects (TOP_N=7) but the comp set caps at MAX=6. When
        all 7 fetch cleanly the 7th is trimmed — previously SILENTLY, leaving the
        'picking 7 firms' rationale contradicting a 6-row table with no drop
        record (KO 2026-07-02: PRMB in trace, absent from table). The trimmed peer
        must now be named so the 7→6 audit trail reconstructs."""
        from finrobot.engine.models.financial import PeerComps, StepOutput

        # Every candidate fetches cleanly; extract keys the company off the ticker
        # so survivors carry distinct identities and the trimmed one is nameable.
        # payload() is the FORWARD_ESTIMATES shape (empty → no forward, no crash).
        async def _fetch_canonical(_dt, ticker):
            return SimpleNamespace(ticker=ticker, payload=lambda: {})

        async def _fetch(_dt, _ticker):
            return SimpleNamespace(data={})

        deps = SimpleNamespace(
            data_layer=SimpleNamespace(fetch_canonical=_fetch_canonical, fetch=_fetch),
            settings=SimpleNamespace(fmp_api_key=""),
        )

        async def _id_normalize(company, **_k):
            return company

        monkeypatch.setattr(
            _helpers, "extract_company_financials", lambda fin: _canned_company(fin.ticker)
        )
        monkeypatch.setattr(_helpers, "normalize_peer_to_usd", _id_normalize)
        monkeypatch.setattr(_helpers, "calculate_multiples", lambda c: c)
        monkeypatch.setattr(_helpers, "override_company_with_xbrl", lambda c, _x: c)

        async def _canned_target(**_k):
            return _canned_company("AAPL")

        monkeypatch.setattr(_helpers, "build_xbrl_aligned_company", _canned_target)

        ctx = {"target_data": _target_financial_data()}
        candidates = ["P1", "P2", "P3", "P4", "P5", "P6", "P7"]
        out = asyncio.run(execute_peer_analysis(None, deps, "", ctx, "AAPL", peers=candidates))

        assert isinstance(out, StepOutput)
        assert isinstance(out.structured, PeerComps)
        # Capped at MAX=6, and the 7th (lowest-ranked survivor) is trimmed…
        assert len(out.structured.peers) == 6
        assert "P7" not in {p.ticker for p in out.structured.peers}
        # …but named in the warnings so the trace reconstructs 7 → 6.
        warning_blob = " ".join(out.structured.warnings)
        assert "P7" in warning_blob
        assert "comp-set cap" in warning_blob


def _financial_sector_target_data():
    """A bank target FinancialData (industry triggers is_balance_sheet_financial)."""
    from datetime import datetime, timezone

    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="JPM",
        income=IncomeStatement(revenue=150.0, ebitda=80.0, net_income=50.0),
        balance=BalanceSheet(total_debt=400.0, total_cash=500.0),
        market=MarketData(
            current_price=200.0,
            shares_outstanding=2.8,
            market_cap=560.0,
            industry="Banks - Diversified",
            sector="Financial Services",
        ),
        valuation=ValuationMetrics(),
        data_source="test",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _peer_comps_with_all_medians(target_ticker: str):
    from finrobot.engine.models.financial import PeerComps

    return PeerComps(
        target=_canned_company(target_ticker),
        peers=[_canned_company("P1"), _canned_company("P2"), _canned_company("P3")],
        median_pe=11.0,
        median_pb=1.3,
        median_ev_ebitda=9.0,
        mean_ev_ebitda=9.2,
    )


def test_comps_suppresses_ev_ebitda_for_financial_sector_target():
    """Banks / insurers have no clean above-the-line EBITDA, so a peer EV/EBITDA
    median is a category error the full report suppresses (P/B is the bank lead).
    FMP still reports a mechanical positive EBITDA for banks → a non-None median, so
    the standalone comps artifact must null it (and its mean) to mirror the report;
    P/E and P/B — the relative methods that DO apply — stay."""
    from typing import Any, cast

    from finrobot.artifact.builders import build_comps_artifact
    from finrobot.engine.pipelines.base import PipelineResult

    result = PipelineResult(
        steps={"target_data": "ok", "statistical_bench": "ok"},
        structured_data={
            "target_data": _financial_sector_target_data(),
            "statistical_bench": _peer_comps_with_all_medians("JPM"),
        },
    )
    s = build_comps_artifact(result, "JPM", cast(Any, None)).outputs.structured
    assert s["median_ev_ebitda"] is None
    assert s["mean_ev_ebitda"] is None
    assert s["median_pe"] == 11.0
    assert s["median_pb"] == 1.3


def test_comps_keeps_ev_ebitda_for_non_financial_target():
    """A non-financial issuer keeps its EV/EBITDA median — the suppression is gated
    strictly on is_balance_sheet_financial, never a blanket null (regression-safe)."""
    from typing import Any, cast

    from finrobot.artifact.builders import build_comps_artifact
    from finrobot.engine.pipelines.base import PipelineResult

    result = PipelineResult(
        steps={"target_data": "ok", "statistical_bench": "ok"},
        structured_data={
            "target_data": _target_financial_data(),  # AAPL — no financial industry
            "statistical_bench": _peer_comps_with_all_medians("AAPL"),
        },
    )
    s = build_comps_artifact(result, "AAPL", cast(Any, None)).outputs.structured
    assert s["median_ev_ebitda"] == 9.0
    assert s["mean_ev_ebitda"] == 9.2
