"""Tests for Pipeline and PipelineStep.

Uses pydantic_ai TestModel for mock agents.
Uses a FakeDeps / FakeDataLayer to avoid real network calls.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.models.financial import StepOutput
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
    """Run pipeline with FakeDeps (P1a: execute takes deps directly)."""
    return await pipeline.execute(FakeDeps(), ticker)


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
        assert result.failed_validations == ["always_bad"]


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
    async def test_execute_logs_step_progress(self, caplog):
        with caplog.at_level(logging.INFO):
            pipeline = Pipeline(steps=[_make_step("my_step")])
            await _run_pipeline(pipeline)
        assert any("Step 1/1: my_step" in r.message for r in caplog.records)
        assert any("\u2713" in r.message for r in caplog.records)


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


# --- P1.5 additions ---


@pytest.mark.asyncio
async def test_execute_fn_called_instead_of_agent_run():
    """execute_fn replaces agent.run()"""
    execute_fn_called = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        execute_fn_called.append(True)
        return StepOutput(text="structured result", structured={"key": "val"})

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock()

    step = PipelineStep(
        name="test_step",
        agent=mock_agent,
        validate=validate_is_non_empty,
        execute_fn=my_fn,
    )
    pipeline = Pipeline(steps=[step])

    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert execute_fn_called == [True]
    mock_agent.run.assert_not_called()
    assert "test_step" in result.structured_data


@pytest.mark.asyncio
async def test_no_execute_fn_uses_agent_run():
    """Without execute_fn, default agent.run() is used"""
    mock_result = MagicMock()
    mock_result.output = "agent output"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    step = PipelineStep(
        name="test_step",
        agent=mock_agent,
        validate=validate_is_non_empty,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    mock_agent.run.assert_called_once()
    assert result.steps["test_step"] == "agent output"


@pytest.mark.asyncio
async def test_validate_structured_called_when_structured_data_present():
    """validate_structured is called when step returns structured data"""
    validated_with = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text="result", structured={"data": True})

    def my_validator(data):
        validated_with.append(data)
        return ValidationResult(passed=True)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validate=validate_is_non_empty,
        execute_fn=my_fn,
        validate_structured=my_validator,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    await pipeline.execute(mock_deps, "AAPL")
    assert len(validated_with) == 1
    assert validated_with[0] == {"data": True}


@pytest.mark.asyncio
async def test_step_output_stored_in_structured_data():
    """StepOutput structured field stored in result.structured_data"""
    async def my_fn(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text="hello", structured=42)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validate=validate_is_non_empty,
        execute_fn=my_fn,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert result.structured_data["test_step"] == 42
    assert result.steps["test_step"] == "hello"


@pytest.mark.asyncio
async def test_str_output_no_structured_data():
    """str output → no entry in structured_data (backward compat)"""
    mock_result = MagicMock()
    mock_result.output = "plain string"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    step = PipelineStep(name="test_step", agent=mock_agent, validate=validate_is_non_empty)
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert "test_step" not in result.structured_data


def test_pipeline_result_get_data():
    r = PipelineResult(steps={"s1": "text"}, structured_data={"s1": {"key": "val"}})
    assert r.get_data("s1") == {"key": "val"}
    assert r.get_data("missing") is None


def test_build_step_prompt_includes_structured_context():
    pipeline = Pipeline(steps=[])
    step = PipelineStep(name="s", agent=MagicMock(), validate=validate_is_non_empty)

    class FakeModel:
        def model_dump_json(self, indent=2):
            return '{"revenue": 100}'

    prompt = pipeline._build_step_prompt(step, "data", "methodology", {"prev_step": FakeModel()})
    assert "prev_step" in prompt
    assert "revenue" in prompt


@pytest.mark.asyncio
async def test_pipeline_logs_structured_data_type(caplog):
    """Acceptance criterion 1: logger.info emits structured data type name."""
    async def my_fn(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text="result", structured={"key": "val"})

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validate=validate_is_non_empty,
        execute_fn=my_fn,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    with caplog.at_level(logging.INFO, logger="finagent.engine.pipelines.base"):
        await pipeline.execute(mock_deps, "AAPL")

    log_messages = " ".join(caplog.messages)
    assert "test_step" in log_messages
    assert "dict" in log_messages  # type({"key": "val"}).__name__ == "dict"


@pytest.mark.asyncio
async def test_retry_with_execute_fn():
    """Retry path: validation fails → execute_fn called again → passes on retry."""
    call_count = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        if len(call_count) == 1:
            return StepOutput(text="bad", structured=None)
        return StepOutput(text="good output with enough content", structured=None)

    def my_validate(text):
        if text == "bad":
            return ValidationResult(passed=False, error="too short")
        return ValidationResult(passed=True)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validate=my_validate,
        execute_fn=my_fn,
    )
    pipeline = Pipeline(steps=[step], max_retries=2)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert len(call_count) == 2  # called once initially, once on retry
    assert result.steps["test_step"] == "good output with enough content"


@pytest.mark.asyncio
async def test_retry_revalidates_structured_data():
    """Retry path with validate_structured: re-validates structured data on retry."""
    call_count = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        val = -5 if len(call_count) == 1 else 10  # bad then good
        return StepOutput(text="result", structured={"value": val})

    def my_validator(data):
        if data["value"] < 0:
            return ValidationResult(passed=False, error="value must be positive")
        return ValidationResult(passed=True)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validate=validate_is_non_empty,
        execute_fn=my_fn,
        validate_structured=my_validator,
    )
    pipeline = Pipeline(steps=[step], max_retries=2)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert len(call_count) == 2
    assert result.structured_data["test_step"]["value"] == 10
