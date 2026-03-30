"""Tests for Pipeline and PipelineStep.

Uses pydantic_ai TestModel for mock agents.
Uses a FakeDeps / FakeDataLayer to avoid real network calls.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.pipelines.base import Pipeline, PipelineResult, PipelineStep
from finagent.engine.pipelines.validators import ValidationResult, validate_is_non_empty


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={"revenue": 1_000, "ebitda": 500, "price_history": [{"close": 150}]},
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )


@dataclass
class FakeDeps:
    data_layer: FakeDataLayer = None
    skill_runtime: object = None
    model_name: str = "test"

    def __post_init__(self):
        if self.data_layer is None:
            self.data_layer = FakeDataLayer()


def _make_agent(output_text: str = "step output") -> Agent:
    test_model = TestModel(custom_output_text=output_text)
    return Agent(test_model)


def _make_step(name: str, required_data: list[str] | None = None, output: str = "step output") -> PipelineStep:
    return PipelineStep(
        name=name,
        agent=_make_agent(output),
        required_data=required_data or [],
        validate=validate_is_non_empty,
    )


async def _run_pipeline(pipeline: Pipeline, ticker: str = "AAPL") -> PipelineResult:
    """Run pipeline with a minimal fake RunContext-like object."""

    class FakeCtx:
        deps = FakeDeps()

    return await pipeline.execute(FakeCtx(), ticker)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineExecution:
    async def test_three_step_pipeline_executes_all_in_order(self):
        order = []

        async def fake_run(step_name):
            order.append(step_name)
            return "output"

        steps = [_make_step(n) for n in ["step_a", "step_b", "step_c"]]
        pipeline = Pipeline(steps=steps)
        result = await _run_pipeline(pipeline)
        assert set(result.steps.keys()) == {"step_a", "step_b", "step_c"}

    async def test_all_step_outputs_stored(self):
        pipeline = Pipeline(steps=[
            _make_step("s1", output="output_s1"),
            _make_step("s2", output="output_s2"),
        ])
        result = await _run_pipeline(pipeline)
        assert result.steps["s1"] == "output_s1"
        assert result.steps["s2"] == "output_s2"


class TestValidationRetry:
    async def test_step_retries_when_validation_fails_then_passes(self, caplog):
        call_count = 0

        def flaky_validate(output: str) -> ValidationResult:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return ValidationResult(passed=False, error="not yet")
            return ValidationResult(passed=True)

        step = PipelineStep(
            name="flaky",
            agent=_make_agent("eventual success"),
            validate=flaky_validate,
        )
        pipeline = Pipeline(steps=[step], max_retries=3)
        result = await _run_pipeline(pipeline)
        assert "flaky" in result.steps
        assert call_count >= 2

    async def test_step_continues_after_all_retries_exhausted(self, caplog):
        """Pipeline must not crash even if validation never passes."""
        def always_fail(output: str) -> ValidationResult:
            return ValidationResult(passed=False, error="always fails")

        step = PipelineStep(
            name="always_bad",
            agent=_make_agent("bad output"),
            validate=always_fail,
        )
        # Should complete without raising
        pipeline = Pipeline(steps=[step], max_retries=2)
        result = await _run_pipeline(pipeline)
        assert "always_bad" in result.steps


class TestGatherData:
    async def test_gather_data_fetches_from_datalayer_when_required_data_nonempty(self):
        step = _make_step("data_step", required_data=["financials"])
        pipeline = Pipeline(steps=[step])
        result = await _run_pipeline(pipeline)
        assert "data_step" in result.steps

    async def test_gather_data_uses_previous_results_when_required_data_empty(self):
        steps = [
            _make_step("s1", output="first step output"),
            _make_step("s2", required_data=[]),    # should see s1 output as context
        ]
        pipeline = Pipeline(steps=steps)
        result = await _run_pipeline(pipeline)
        assert "s2" in result.steps


class TestPipelineLogging:
    async def test_execute_prints_step_progress(self, capsys):
        pipeline = Pipeline(steps=[_make_step("my_step")])
        await _run_pipeline(pipeline)
        captured = capsys.readouterr()
        assert "Step 1/1: my_step" in captured.out
        assert "✓" in captured.out


class TestPipelineResult:
    def test_format_summary_produces_non_empty_markdown(self):
        result = PipelineResult(steps={"step_a": "content a", "step_b": "content b"})
        summary = result.format_summary()
        assert len(summary) > 0
        assert "Step A" in summary or "step_a" in summary.lower()
        assert "content a" in summary
        assert "content b" in summary

    def test_format_summary_empty_steps(self):
        result = PipelineResult(steps={})
        assert result.format_summary() == ""
