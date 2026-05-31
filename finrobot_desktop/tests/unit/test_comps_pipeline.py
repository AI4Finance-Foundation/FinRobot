import asyncio
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
    def test_none_falls_back_to_llm(self):
        # The default path passes no `peers` kwarg → None → LLM selection.
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
        # If the override path leaked into LLM selection this would raise a
        # different error; instead the candidates in the failure are exactly the
        # supplied set, proving the LLM was bypassed.
        async def _boom(*_a, **_k):
            raise AssertionError("LLM peer selection must not run when --peers is given")

        monkeypatch.setattr(_helpers, "_llm_select_peers", _boom)
        with pytest.raises(ValueError, match="QCOM"):
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
