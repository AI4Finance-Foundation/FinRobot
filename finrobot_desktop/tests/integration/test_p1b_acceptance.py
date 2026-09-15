import os
import pytest
from pathlib import Path

from finrobot.config import get_settings
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline
from finrobot.engine.pipelines.comps import create_comps_pipeline
from finrobot.engine.pipelines.dcf import create_dcf_pipeline
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider

SKILLS_DIR = Path(get_settings().skills_dir)


def _build_test_env():
    settings = get_settings()
    registry = SkillRegistry(SKILLS_DIR) if SKILLS_DIR.exists() else None
    sub_agents = create_sub_agents(settings, skill_registry=registry)
    cache = DataCache(":memory:")
    data_layer = DataLayer(providers=[YFinanceProvider()], cache=cache)
    deps = FinRobotDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)
    return sub_agents, deps


class TestP1bAcceptance:
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_equity_research_with_sub_agents(self):
        """P1b acceptance: equity research uses sub-agents and strict validators."""
        sub_agents, deps = _build_test_env()
        pipeline = create_equity_research_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")

        assert set(result.steps.keys()) == {
            "data_collection",
            "catalyst_analysis",
            "peer_analysis",
            "financial_modeling",
            "technical_analysis",
            "ownership_governance_analysis",
            "thesis",
            "report",
        }

        # Strict validator checks
        summary = result.format_summary().lower()
        assert any(kw in summary for kw in ["ev/ebitda", "p/e", "peer", "comparable"])
        assert any(kw in summary for kw in ["dcf", "wacc", "discount rate", "terminal"])
        assert any(kw in summary for kw in ["buy", "hold", "sell", "catalyst", "risk"])

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_comps_pipeline(self):
        """P1b acceptance: comps pipeline produces peer multiples table."""
        sub_agents, deps = _build_test_env()
        pipeline = create_comps_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")

        # Collapsed from 6 LLM steps to 3: peer multiples now come from the
        # deterministic shared execute_peer_analysis (statistical_bench), not
        # the old LLM free-text peer_data / multiples_calc steps.
        assert set(result.steps.keys()) == {
            "target_data",
            "statistical_bench",
            "output_gen",
        }

        output = result.format_summary().lower()
        assert any(kw in output for kw in ["ev/ebitda", "p/e", "multiple"])
        assert any(kw in output for kw in ["median", "mean", "average"])

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_dcf_pipeline(self):
        """P1b acceptance: DCF pipeline produces valuation model.

        The DCF pipeline was consolidated post-P1.5 from 6 steps
        (historical_data / projection / wacc / terminal_value / sensitivity
        / output_gen) into 3 deterministic steps (historical_data /
        dcf_calc / output_gen). The compute layer now runs WACC + terminal
        value + sensitivity in-process inside dcf_calc rather than
        round-tripping through LLM steps — keeps numbers reproducible.
        """
        sub_agents, deps = _build_test_env()
        pipeline = create_dcf_pipeline(sub_agents)
        result = await pipeline.execute(deps, "AAPL")

        assert set(result.steps.keys()) == {
            "historical_data",
            "dcf_calc",
            "output_gen",
        }

        output = result.format_summary().lower()
        assert any(kw in output for kw in ["wacc", "discount rate"])
        assert any(kw in output for kw in ["terminal value", "exit multiple", "perpetuity"])

    @pytest.mark.skipif(
        not os.getenv("QUALITY_GATE"),
        reason="Manual quality gate — run with: QUALITY_GATE=1 pytest tests/integration/test_p1b_acceptance.py::TestP1bAcceptance::test_quality_comparison",
    )
    @pytest.mark.asyncio
    async def test_quality_comparison(self):
        """P1b QUALITY GATE: Pipeline output vs single-call LLM output.

        This test is the project's value validation milestone.
        Run manually and review output side-by-side.
        """
        sub_agents, deps = _build_test_env()

        # 1. Pipeline output (5 sub-agents, 5 enforced steps)
        pipeline = create_equity_research_pipeline(sub_agents)
        pipeline_result = await pipeline.execute(deps, "AAPL")
        pipeline_output = pipeline_result.format_summary()

        # 2. Single-call output — a bare agent with ONLY query_financial_data
        from pydantic_ai import Agent, RunContext

        settings = get_settings()
        single_agent = Agent(
            settings.model_name,
            deps_type=FinRobotDeps,
            instructions="You are a financial analyst. Use real data from tools. Never fabricate numbers.",
            defer_model_check=True,
        )

        @single_agent.tool
        async def query_financial_data(
            ctx: RunContext[FinRobotDeps], ticker: str, data_type: str
        ) -> str:
            result = await ctx.deps.data_layer.fetch(data_type, ticker)
            return result.to_context_string()

        single_result = await single_agent.run(
            "Fetch financials, price, and news for AAPL using query_financial_data. "
            "Then write a comprehensive equity research report covering: "
            "financial summary, peer analysis with at least 3 comparable companies, "
            "DCF valuation with WACC and terminal value, investment thesis with "
            "catalysts and risks, and a final recommendation with price target. "
            "Use real data only.",
            deps=deps,
        )
        single_output = single_result.output

        # Print both for manual comparison
        print("\n" + "=" * 80)
        print("PIPELINE OUTPUT (5 sub-agents, 5 enforced steps, skill injection)")
        print("=" * 80)
        print(pipeline_output[:3000])
        print("\n" + "=" * 80)
        print("SINGLE-CALL OUTPUT (1 agent, 1 pass, no pipeline)")
        print("=" * 80)
        print(single_output[:3000])
        print("\n" + "=" * 80)
        print("COMPARE: Does pipeline output have better structure, ")
        print("methodology depth, and data accuracy than single-call?")
        print("If NO → pipeline architecture is over-engineering. Consider pivot.")
        print("=" * 80)
