"""Tests for Pipeline and PipelineStep.

Uses pydantic_ai TestModel for mock agents.
Uses a FakeDeps / FakeDataLayer to avoid real network calls.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataResult
from finagent.engine.models.financial import StepOutput
from finagent.engine.pipelines.base import (
    Pipeline,
    PipelineResult,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
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


def _make_step(
    name: str, required_data: list[str] | None = None, output: str = "step output"
) -> PipelineStep:
    return PipelineStep(
        name=name,
        agent=_make_agent(output),
        required_data=required_data or [],
        validator=TextValidator(validate_is_non_empty),
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

        def make_fn(step_name):
            async def fn(agent, deps, prompt, structured_context, ticker):
                order.append(step_name)
                return f"output from {step_name}"

            return fn

        steps = [
            PipelineStep(
                name=n,
                agent=MagicMock(),
                validator=TextValidator(validate_is_non_empty),
                executor=make_fn(n),
            )
            for n in ["step_a", "step_b", "step_c"]
        ]
        mock_deps = MagicMock()
        mock_deps.skill_runtime = None
        pipeline = Pipeline(steps=steps)
        result = await pipeline.execute(mock_deps, "AAPL")
        # Verify ORDER was preserved, not just that all steps ran
        assert order == ["step_a", "step_b", "step_c"]
        assert set(result.steps.keys()) == {"step_a", "step_b", "step_c"}

    async def test_all_step_outputs_stored(self):
        pipeline = Pipeline(
            steps=[
                _make_step("s1", output="output_s1"),
                _make_step("s2", output="output_s2"),
            ]
        )
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
            validator=TextValidator(flaky_validate),
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
            validator=TextValidator(always_fail),
        )
        # Should complete without raising
        pipeline = Pipeline(steps=[step], max_retries=2)
        result = await _run_pipeline(pipeline)
        assert "always_bad" in result.steps
        assert len(result.failed_validations) == 1
        assert result.failed_validations[0]["step"] == "always_bad"
        assert "always fails" in result.failed_validations[0]["error"]


class TestGatherData:
    async def test_gather_data_fetches_from_datalayer_when_required_data_nonempty(self):
        step = _make_step("data_step", required_data=["financials"])
        pipeline = Pipeline(steps=[step])
        result = await _run_pipeline(pipeline)
        assert "data_step" in result.steps

    async def test_gather_data_uses_previous_results_when_required_data_empty(self):
        steps = [
            _make_step("s1", output="first step output"),
            _make_step("s2", required_data=[]),  # should see s1 output as context
        ]
        pipeline = Pipeline(steps=steps)
        result = await _run_pipeline(pipeline)
        assert "s2" in result.steps

    async def test_compact_context_includes_snippet_for_unstructured_steps(self):
        """D6: steps without structured_context get 300-char text snippet."""
        captured_prompts: list[str] = []

        async def capture_fn(agent, deps, prompt, structured_context, ticker):
            captured_prompts.append(prompt)
            return "step output text that is meaningful"

        # All steps have empty required_data so compact mode kicks in for
        # step_d (which has 3 prior results, compacting step_a and step_b).
        steps = [
            PipelineStep(
                name="step_a",
                agent=MagicMock(),
                validator=TextValidator(validate_is_non_empty),
                executor=capture_fn,
            ),
            PipelineStep(
                name="step_b",
                agent=MagicMock(),
                validator=TextValidator(validate_is_non_empty),
                executor=capture_fn,
            ),
            PipelineStep(
                name="step_c",
                agent=MagicMock(),
                validator=TextValidator(validate_is_non_empty),
                executor=capture_fn,
            ),
            PipelineStep(
                name="step_d",
                agent=MagicMock(),
                validator=TextValidator(validate_is_non_empty),
                executor=capture_fn,
            ),
        ]
        mock_deps = MagicMock()
        mock_deps.skill_runtime = None
        pipeline = Pipeline(steps=steps)
        await pipeline.execute(mock_deps, "TEST")

        # step_d's prompt uses compact mode for step_a and step_b.
        # Since executor returns plain string (no StepOutput), there's no
        # structured data for step_a/step_b -> the D6 snippet should include text.
        last_prompt = captured_prompts[-1]  # step_d

        # The compacted section for step_a (which has no structured data)
        # must include the text snippet, not just a pointer to structured_context.
        # Find the line for step_a's compact summary.
        step_a_line = [
            line for line in last_prompt.splitlines() if "step_a" in line and "Previous" in line
        ]
        assert len(step_a_line) == 1, f"Expected one compact line for step_a, got: {step_a_line}"
        # D6 fix: the compact line should contain actual text content
        assert (
            "step output text" in step_a_line[0]
        ), f"Step_a compact line missing text snippet: {step_a_line[0]}"


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

    def test_format_summary_includes_data_source_notes(self):
        """Warnings from structured data appear in Data Source Notes section."""

        class FakeModel:
            warnings = [
                "Data discrepancy: revenue differs by 33% (fmp: 100 vs yfinance: 75).",
                "total_debt not available — defaulted to 0",
            ]
            data_source = "fmp"

        result = PipelineResult(
            steps={"data_collection": "some output"},
            structured_data={"data_collection": FakeModel()},
        )
        summary = result.format_summary()
        assert "## Data Source Notes" in summary
        assert "revenue differs by 33%" in summary
        assert "total_debt not available" in summary
        assert "Primary data source (fmp)" in summary

    def test_format_summary_no_notes_when_no_warnings(self):
        """No Data Source Notes section when there are no warnings."""

        class CleanModel:
            warnings: list[str] = []

        result = PipelineResult(
            steps={"step_a": "output"},
            structured_data={"step_a": CleanModel()},
        )
        summary = result.format_summary()
        assert "Data Source Notes" not in summary


# --- P1.5 additions ---


@pytest.mark.asyncio
async def test_executor_called_instead_of_agent_run():
    """Custom executor replaces default agent.run()"""
    executor_called = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        executor_called.append(True)
        return StepOutput(text="structured result", structured={"key": "val"})

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock()

    step = PipelineStep(
        name="test_step",
        agent=mock_agent,
        validator=TextValidator(validate_is_non_empty),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step])

    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert executor_called == [True]
    mock_agent.run.assert_not_called()
    assert "test_step" in result.structured_data


@pytest.mark.asyncio
async def test_default_executor_uses_agent_run():
    """Without custom executor, DefaultAgentExecutor calls agent.run()"""
    mock_result = MagicMock()
    mock_result.output = "agent output"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    step = PipelineStep(
        name="test_step",
        agent=mock_agent,
        validator=TextValidator(validate_is_non_empty),
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    mock_agent.run.assert_called_once()
    assert result.steps["test_step"] == "agent output"


@pytest.mark.asyncio
async def test_structured_validator_called_when_structured_data_present():
    """StructuredValidator receives structured data when available"""
    validated_with = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text="result", structured={"data": True})

    def my_structured_validator(data):
        validated_with.append(data)
        return ValidationResult(passed=True)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validator=StructuredValidator(my_structured_validator, validate_is_non_empty),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    await pipeline.execute(mock_deps, "AAPL")
    assert len(validated_with) == 1
    # Pydantic converts dict to BaseModel, which is acceptable
    from pydantic import BaseModel

    assert isinstance(validated_with[0], (dict, BaseModel))


@pytest.mark.asyncio
async def test_step_output_stored_in_structured_data():
    """StepOutput structured field stored in result.structured_data"""

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text="hello", structured={"value": 42})

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert result.structured_data["test_step"] == {"value": 42}
    assert result.steps["test_step"] == "hello"


@pytest.mark.asyncio
async def test_str_output_no_structured_data():
    """str output → no entry in structured_data (backward compat)"""
    mock_result = MagicMock()
    mock_result.output = "plain string"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    step = PipelineStep(
        name="test_step", agent=mock_agent, validator=TextValidator(validate_is_non_empty)
    )
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
    step = PipelineStep(name="s", agent=MagicMock(), validator=TextValidator(validate_is_non_empty))

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
        validator=TextValidator(validate_is_non_empty),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    with caplog.at_level(logging.INFO, logger="finagent.engine.pipelines.base"):
        await pipeline.execute(mock_deps, "AAPL")

    log_messages = " ".join(caplog.messages)
    assert "test_step" in log_messages
    # Pydantic converts dict to BaseModel, so we check for either
    assert "dict" in log_messages or "BaseModel" in log_messages


@pytest.mark.asyncio
async def test_retry_with_custom_executor():
    """Retry path: validation fails → executor called again → passes on retry."""
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
        validator=TextValidator(my_validate),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step], max_retries=2)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert len(call_count) == 2  # called once initially, once on retry
    assert result.steps["test_step"] == "good output with enough content"


@pytest.mark.asyncio
async def test_retry_revalidates_structured_data():
    """Retry path with StructuredValidator: re-validates structured data on retry."""
    call_count = []

    async def my_fn(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        val = -5 if len(call_count) == 1 else 10  # bad then good
        return StepOutput(text="result", structured={"value": val})

    def my_structured_validator(data):
        if isinstance(data, dict):
            value = data.get("value")
        else:
            value = getattr(data, "value", None) if hasattr(data, "value") else None

        if value is None:
            return ValidationResult(passed=False, error="value is missing")
        if value < 0:
            return ValidationResult(passed=False, error="value must be positive")
        return ValidationResult(passed=True)

    step = PipelineStep(
        name="test_step",
        agent=MagicMock(),
        validator=StructuredValidator(my_structured_validator, validate_is_non_empty),
        executor=my_fn,
    )
    pipeline = Pipeline(steps=[step], max_retries=2)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")
    assert len(call_count) == 2
    assert result.structured_data["test_step"]["value"] == 10
