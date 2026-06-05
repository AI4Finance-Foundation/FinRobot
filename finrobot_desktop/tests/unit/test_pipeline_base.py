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
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.models.test import TestModel

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.models.financial import StepOutput
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineResult,
    PipelineStep,
    PipelineStepError,
    StructuredValidator,
    TextValidator,
    _PROMPT_MAX_STEP_DATA_CHARS,
    _is_recoverable_exception,
)
from finrobot.engine.pipelines.validators import ValidationResult, validate_is_non_empty


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

    async def test_source_artifact_id_is_forwarded_to_step_executors(self):
        captured: dict[str, object] = {}

        async def executor(agent, deps, prompt, structured_context, ticker, **kwargs):
            captured.update(kwargs)
            return StepOutput(text="ok")

        pipeline = Pipeline(
            steps=[
                PipelineStep(
                    name="s1",
                    agent=MagicMock(),
                    validator=TextValidator(validate_is_non_empty),
                    executor=executor,
                )
            ]
        )

        await pipeline.execute(FakeDeps(), "AAPL", source_artifact_id="art_prev_AAPL_eq")

        assert captured["source_artifact_id"] == "art_prev_AAPL_eq"


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
        assert "step output text" in step_a_line[0], (
            f"Step_a compact line missing text snippet: {step_a_line[0]}"
        )


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


def _minimal_artifact():
    """Smallest valid Artifact a builder could return — meta.language is the
    field under test; everything else uses minimal valid values."""
    from finrobot.artifact.models import (
        Artifact,
        ArtifactAssumptions,
        ArtifactComputeVersion,
        ArtifactInputs,
        ArtifactMeta,
        ArtifactOutputs,
    )

    now = datetime.now(tz=timezone.utc)
    return Artifact(
        id="art_test_AAPL_eq",
        ticker="AAPL",
        type="equity_research",
        inputs=ArtifactInputs(data_source="fake", data_fetched_at=now, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.0.0", formula_id="test_v1"),
        outputs=ArtifactOutputs(structured={}, llm_narrative={}),
        meta=ArtifactMeta(created_at=now, source="cli"),
    )


class TestArtifactLanguageStamping:
    """meta.language is stamped from the run's effective_lang at the single
    write point in execute() — see ADR-0008."""

    def test_artifact_meta_defaults_to_zh(self):
        from finrobot.artifact.models import ArtifactMeta

        # Legacy artifacts (written before this field existed) were all generated
        # in Chinese; the default MUST be 'zh' so old JSON deserializes with
        # correct provenance. Deliberately the opposite of settings.language ('en').
        meta = ArtifactMeta(created_at=datetime.now(tz=timezone.utc), source="cli")
        assert meta.language == "zh"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "lang,expected",
        [("en", "en"), ("zh", "zh"), (None, "en")],  # None → settings.language fallback
    )
    async def test_execute_stamps_effective_lang(self, lang, expected):
        saved: dict = {}

        def builder(result, ticker, deps):
            return _minimal_artifact()

        store = MagicMock()

        async def _save(art):
            saved["artifact"] = art
            return art.id

        store.save = _save

        deps = MagicMock()
        deps.skill_runtime = None
        deps.artifact_store = store
        deps.settings.language = "en"  # fallback target when lang is None

        pipeline = Pipeline(steps=[_make_step("s1")], artifact_builder=builder)
        await pipeline.execute(deps, "AAPL", lang=lang)

        assert saved["artifact"].meta.language == expected


class TestArtifactParentLineageStamping:
    """meta.parent_artifact_id is stamped from the run's source_artifact_id at
    the same single write point in execute() — it records version lineage so the
    diff view can default to comparing against the version a re-run came from."""

    @pytest.mark.asyncio
    async def test_execute_stamps_parent_artifact_id_on_rerun(self):
        saved: dict = {}

        def builder(result, ticker, deps):
            return _minimal_artifact()

        store = MagicMock()

        async def _save(art):
            saved["artifact"] = art
            return art.id

        store.save = _save

        deps = MagicMock()
        deps.skill_runtime = None
        deps.artifact_store = store
        deps.settings.language = "en"

        pipeline = Pipeline(steps=[_make_step("s1")], artifact_builder=builder)
        await pipeline.execute(deps, "AAPL", source_artifact_id="art_prev_AAPL_eq")

        assert saved["artifact"].meta.parent_artifact_id == "art_prev_AAPL_eq"

    @pytest.mark.asyncio
    async def test_execute_leaves_parent_none_for_fresh_run(self):
        saved: dict = {}

        def builder(result, ticker, deps):
            return _minimal_artifact()

        store = MagicMock()

        async def _save(art):
            saved["artifact"] = art
            return art.id

        store.save = _save

        deps = MagicMock()
        deps.skill_runtime = None
        deps.artifact_store = store
        deps.settings.language = "en"

        pipeline = Pipeline(steps=[_make_step("s1")], artifact_builder=builder)
        await pipeline.execute(deps, "AAPL")  # no source_artifact_id

        assert saved["artifact"].meta.parent_artifact_id is None


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

    with caplog.at_level(logging.INFO, logger="finrobot.engine.pipelines.base"):
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


# ---------------------------------------------------------------------------
# Executor-exception retry tests
# ---------------------------------------------------------------------------


class TestIsRecoverableException:
    """Unit tests for the _is_recoverable_exception predicate."""

    def test_agent_run_error_is_recoverable(self):
        assert _is_recoverable_exception(AgentRunError("model overloaded"))

    def test_provider_error_is_recoverable(self):
        assert _is_recoverable_exception(ProviderError("yfinance 429"))

    def test_httpx_timeout_is_recoverable(self):
        import httpx

        assert _is_recoverable_exception(httpx.TimeoutException("timed out"))

    def test_httpx_connect_error_is_recoverable(self):
        import httpx

        assert _is_recoverable_exception(httpx.ConnectError("connection refused"))

    def test_rate_limit_str_is_recoverable(self):
        assert _is_recoverable_exception(RuntimeError("HTTP 429: rate limit exceeded"))

    def test_too_many_requests_is_recoverable(self):
        assert _is_recoverable_exception(ValueError("too many requests"))

    def test_timeout_str_is_recoverable(self):
        assert _is_recoverable_exception(OSError("operation timeout"))

    def test_insufficient_balance_is_not_recoverable(self):
        """402 billing error must not trigger retry."""
        assert not _is_recoverable_exception(RuntimeError("Insufficient Balance (402)"))

    def test_auth_errors_are_not_recoverable(self):
        """401 / bad-key / unknown-model are the user's config to fix — retrying
        just burns quota and delays a clear failure."""
        from pydantic_ai.exceptions import AgentRunError

        assert not _is_recoverable_exception(AgentRunError("401 Unauthorized"))
        assert not _is_recoverable_exception(RuntimeError("Invalid API key provided"))
        assert not _is_recoverable_exception(RuntimeError("Incorrect API key"))
        assert not _is_recoverable_exception(RuntimeError("authentication_error"))
        assert not _is_recoverable_exception(RuntimeError("The model `gpt-foo` does not exist"))

    def test_insufficient_balance_case_insensitive(self):
        assert not _is_recoverable_exception(RuntimeError("INSUFFICIENT BALANCE"))

    def test_generic_value_error_is_not_recoverable(self):
        assert not _is_recoverable_exception(ValueError("bad input schema"))

    def test_context_length_overflow_is_not_recoverable(self):
        """A 400 context-length overflow is deterministic — re-sending the same
        oversized prompt fails identically, so it must abort, not retry."""
        msg = (
            "status_code: 400, model_name: gpt-4o, body: {'message': \"This "
            "model's maximum context length is 128000 tokens. However, your "
            "messages resulted in 146840 tokens. Please reduce the length of "
            "the messages or functions.\", 'type': 'invalid_request_error'}"
        )
        assert not _is_recoverable_exception(AgentRunError(msg))

    def test_context_length_exceeded_type_is_not_recoverable(self):
        assert not _is_recoverable_exception(RuntimeError("context_length_exceeded"))


@pytest.mark.asyncio
async def test_executor_agent_run_error_retries_then_succeeds():
    """AgentRunError on first 2 calls → 3rd call succeeds → step completes."""
    call_count = []

    async def flaky_executor(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        if len(call_count) <= 2:
            raise AgentRunError("model overloaded")
        return "recovered output"

    step = PipelineStep(
        name="flaky_step",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=flaky_executor,
    )
    # max_retries=3 → budget for 3 retries after the initial attempt
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    # Patch asyncio.sleep to avoid real delays in tests.
    import asyncio
    from unittest.mock import patch

    with patch.object(asyncio, "sleep", new=AsyncMock()):
        result = await pipeline.execute(mock_deps, "AAPL")

    # initial attempt + 2 retries = 3 total calls
    assert len(call_count) == 3
    assert result.steps["flaky_step"] == "recovered output"
    assert result.failed_validations == []


@pytest.mark.asyncio
async def test_executor_insufficient_balance_not_retried():
    """Insufficient Balance (non-recoverable) must propagate without retry."""
    call_count = []

    async def billing_error_executor(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        raise RuntimeError("Insufficient Balance (402)")

    step = PipelineStep(
        name="billing_step",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=billing_error_executor,
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    with pytest.raises(RuntimeError, match="Insufficient Balance"):
        await pipeline.execute(mock_deps, "AAPL")

    # Must have been called exactly once — no retries.
    assert len(call_count) == 1


@pytest.mark.asyncio
async def test_executor_provider_error_rate_limit_retries():
    """ProviderError with 'rate limit' message is treated as recoverable."""
    call_count = []

    async def rate_limited_executor(agent, deps, prompt, structured_context, ticker):
        call_count.append(1)
        if len(call_count) <= 1:
            raise ProviderError("rate limit: 429 from yfinance")
        return "data fetched successfully"

    step = PipelineStep(
        name="data_step",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=rate_limited_executor,
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    import asyncio
    from unittest.mock import patch

    with patch.object(asyncio, "sleep", new=AsyncMock()):
        result = await pipeline.execute(mock_deps, "AAPL")

    assert len(call_count) == 2
    assert result.steps["data_step"] == "data fetched successfully"
    assert result.failed_validations == []


# ---------------------------------------------------------------------------
# Critical-step abort: a hard-prerequisite failure must stop the run, not
# continue best-effort into a confusing downstream crash.
# ---------------------------------------------------------------------------


def _always_fail_validator(output) -> ValidationResult:
    return ValidationResult(passed=False, error="boom")


@pytest.mark.asyncio
async def test_critical_step_failure_aborts_pipeline():
    """A critical step that exhausts retries raises PipelineStepError and the
    downstream steps never run (no silent best-effort continue)."""
    downstream_ran: list[str] = []

    async def downstream_executor(agent, deps, prompt, structured_context, ticker):
        downstream_ran.append(ticker)
        return "should never run"

    critical = PipelineStep(
        name="data_collection",
        agent=_make_agent("data"),
        validator=TextValidator(_always_fail_validator),
        critical=True,
    )
    downstream = PipelineStep(
        name="peer_analysis",
        agent=_make_agent("peers"),
        validator=TextValidator(validate_is_non_empty),
        executor=downstream_executor,
    )
    pipeline = Pipeline(steps=[critical, downstream], max_retries=1)

    with pytest.raises(PipelineStepError) as exc:
        await _run_pipeline(pipeline)

    assert exc.value.step_name == "data_collection"
    assert "boom" in str(exc.value)
    assert downstream_ran == []  # aborted before reaching downstream


@pytest.mark.asyncio
async def test_noncritical_step_failure_continues():
    """A non-critical step that fails validation is recorded but the pipeline
    continues — the existing best-effort behavior is preserved."""
    steps = [
        PipelineStep(
            name="soft_step",
            agent=_make_agent("out"),
            validator=TextValidator(_always_fail_validator),
            # critical defaults to False
        ),
        _make_step("next_step"),
    ]
    pipeline = Pipeline(steps=steps, max_retries=1)
    result = await _run_pipeline(pipeline)

    assert "next_step" in result.steps
    assert any(f["step"] == "soft_step" for f in result.failed_validations)


# ---------------------------------------------------------------------------
# Prompt-size guard: required_data text is bounded so a pathological provider
# payload (e.g. a full 10-K) can never flood the prompt past the context window.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_data_is_truncated_to_cap():
    """An oversized to_context_string is capped with a visible marker before it
    reaches the prompt."""

    class HugeDataLayer:
        async def fetch(self, data_type, ticker, **kwargs) -> DataResult:
            return DataResult(
                data={"giant": "x" * (_PROMPT_MAX_STEP_DATA_CHARS * 3)},
                provider="fake",
                ticker=ticker,
                data_type=data_type,
                timestamp=datetime.now(tz=timezone.utc),
            )

    captured: list[str] = []

    async def capture_executor(agent, deps, prompt, structured_context, ticker):
        captured.append(prompt)
        return "ok"

    step = PipelineStep(
        name="data_step",
        agent=_make_agent("ok"),
        required_data=["financials"],
        validator=TextValidator(validate_is_non_empty),
        executor=capture_executor,
    )
    pipeline = Pipeline(steps=[step])
    await pipeline.execute(FakeDeps(data_layer=HugeDataLayer()), "AAPL")

    assert len(captured) == 1
    prompt = captured[0]
    assert "truncated" in prompt
    # The raw payload was 3x the cap; the prompt must be far smaller than that.
    assert len(prompt) < _PROMPT_MAX_STEP_DATA_CHARS * 2


# ---------------------------------------------------------------------------
# BUG-017 — Pipeline.execute honours deps.run_semaphore (app-wide concurrency)
# ---------------------------------------------------------------------------


class TestRunSemaphoreGating:
    """Every caller that passes deps.run_semaphore gets capped inside execute,
    so chat-triggered and Coverage-batch runs share the same bound as REST."""

    @pytest.mark.asyncio
    async def test_execute_acquires_semaphore_when_present(self):
        """A run holds the semaphore for its whole body (1 slot consumed)."""
        import asyncio

        sem = asyncio.Semaphore(1)

        @dataclass
        class DepsWithSem:
            data_layer: FakeDataLayer
            skill_runtime: object
            run_semaphore: asyncio.Semaphore

        observed: list[int] = []

        async def slot_observing_executor(agent, deps, prompt, structured_context, ticker):
            # While this step runs the slot must be held → semaphore exhausted.
            observed.append(sem._value)  # 0 means the one slot is taken
            return "ok"

        step = PipelineStep(
            name="s",
            agent=_make_agent("ok"),
            validator=TextValidator(validate_is_non_empty),
            executor=slot_observing_executor,
        )
        deps = DepsWithSem(FakeDataLayer(), None, sem)
        await Pipeline(steps=[step]).execute(deps, "AAPL")

        assert observed == [0]  # the slot was held during step execution
        assert sem._value == 1  # and released after the run completed

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrent_runs(self):
        """With a 1-slot semaphore, two concurrent runs never overlap."""
        import asyncio

        sem = asyncio.Semaphore(1)

        @dataclass
        class DepsWithSem:
            data_layer: FakeDataLayer
            skill_runtime: object
            run_semaphore: asyncio.Semaphore

        active = 0
        max_active = 0

        async def blocking_executor(agent, deps, prompt, structured_context, ticker):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            # Yield so a second run gets a chance to start if the cap allowed it.
            await asyncio.sleep(0.02)
            active -= 1
            return "ok"

        def make_pipeline() -> Pipeline:
            step = PipelineStep(
                name="s",
                agent=_make_agent("ok"),
                validator=TextValidator(validate_is_non_empty),
                executor=blocking_executor,
            )
            return Pipeline(steps=[step])

        deps = DepsWithSem(FakeDataLayer(), None, sem)
        await asyncio.gather(
            make_pipeline().execute(deps, "AAPL"),
            make_pipeline().execute(deps, "MSFT"),
        )
        # The 1-slot cap must serialise them: never two in flight at once.
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_execute_runs_without_semaphore(self):
        """deps.run_semaphore = None (CLI/SDK) → nullcontext, no cap, runs fine."""

        @dataclass
        class DepsNoSem:
            data_layer: FakeDataLayer
            skill_runtime: object
            run_semaphore: object = None

        step = PipelineStep(
            name="s",
            agent=_make_agent("ok"),
            validator=TextValidator(validate_is_non_empty),
        )
        result = await Pipeline(steps=[step]).execute(DepsNoSem(FakeDataLayer(), None), "AAPL")
        assert "s" in result.steps


# ---------------------------------------------------------------------------
# BUG-058: a non-critical step that DEGRADES (fails validation after all
# retries) must surface that via on_step_end(error=...), not a silent green ✓.
# ---------------------------------------------------------------------------


class _RecordingProgress:
    """Captures on_step_end(error=...) so a test can assert degrade signalling."""

    def __init__(self) -> None:
        self.ends: list[tuple[str, str | None]] = []
        self.retries: list[tuple[str, int]] = []

    async def on_step_start(self, step_index: int, total: int, step_name: str) -> None:
        pass

    async def on_step_end(
        self,
        step_index: int,
        total: int,
        step_name: str,
        duration_s: float,
        error: str | None = None,
    ) -> None:
        self.ends.append((step_name, error))

    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None:
        self.retries.append((step_name, attempt))


@pytest.mark.asyncio
async def test_degraded_noncritical_step_signals_error_to_on_step_end():
    """A non-critical step that fails validation after all retries passes its
    error into on_step_end so the UI can render amber, not a green ✓ (BUG-058)."""
    progress = _RecordingProgress()
    step = PipelineStep(
        name="soft_step",
        agent=_make_agent("out"),
        validator=TextValidator(_always_fail_validator),
    )
    pipeline = Pipeline(steps=[step], max_retries=1)
    result = await pipeline.execute(FakeDeps(), "AAPL", progress=progress)

    # on_step_end fired exactly once, carrying the validation error (degraded).
    assert progress.ends == [("soft_step", "boom")]
    # Failure is still recorded honestly in failed_validations.
    assert any(f["step"] == "soft_step" for f in result.failed_validations)


@pytest.mark.asyncio
async def test_passing_step_signals_no_error_to_on_step_end():
    """A clean pass calls on_step_end with error=None — the event is byte-for-byte
    what it was before BUG-058, so existing green-✓ rendering is unchanged."""
    progress = _RecordingProgress()
    step = _make_step("good_step")
    pipeline = Pipeline(steps=[step], max_retries=1)
    await pipeline.execute(FakeDeps(), "AAPL", progress=progress)

    assert progress.ends == [("good_step", None)]


@pytest.mark.asyncio
async def test_critical_step_emits_no_on_step_end_on_failure():
    """A critical step aborts BEFORE on_step_end (BUG-014/015 semantics): no
    degrade event AND no false green ✓ — the run fails outright instead."""
    progress = _RecordingProgress()
    critical = PipelineStep(
        name="data_collection",
        agent=_make_agent("data"),
        validator=TextValidator(_always_fail_validator),
        critical=True,
    )
    pipeline = Pipeline(steps=[critical], max_retries=1)

    with pytest.raises(PipelineStepError):
        await pipeline.execute(FakeDeps(), "AAPL", progress=progress)

    # No on_step_end was emitted for the aborting critical step.
    assert progress.ends == []


# ---------------------------------------------------------------------------
# BUG-059: a deterministic executor's output cannot change on a re-prompt, so a
# VALIDATION failure must short-circuit the retry loop (degrade immediately)
# instead of burning the whole budget on identical failing output. The
# EXCEPTION-retry path stays intact (transient errors may recover on back-off).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_validation_failure_skips_retries():
    """deterministic=True + a validation failure → executor runs exactly ONCE,
    no retries, and the step degrades (BUG-059)."""
    progress = _RecordingProgress()
    call_count = 0

    async def deterministic_executor(agent, deps, prompt, structured_context, ticker):
        nonlocal call_count
        call_count += 1
        return "always-bad output"

    step = PipelineStep(
        name="financial_modeling",
        agent=MagicMock(),
        validator=TextValidator(_always_fail_validator),
        executor=deterministic_executor,
        deterministic=True,
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL", progress=progress)

    assert call_count == 1  # NOT 1 + 3 retries
    assert progress.retries == []  # no retry events emitted
    assert progress.ends == [("financial_modeling", "boom")]  # degraded
    assert any(f["step"] == "financial_modeling" for f in result.failed_validations)


@pytest.mark.asyncio
async def test_nondeterministic_validation_failure_still_retries():
    """Control: a step WITHOUT deterministic=True still burns its retry budget on
    a validation failure (unchanged behaviour for LLM-consuming steps)."""
    call_count = 0

    async def llm_executor(agent, deps, prompt, structured_context, ticker):
        nonlocal call_count
        call_count += 1
        return "always-bad output"

    step = PipelineStep(
        name="thesis",
        agent=MagicMock(),
        validator=TextValidator(_always_fail_validator),
        executor=llm_executor,
        # deterministic defaults to False
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL")

    assert call_count == 4  # 1 initial + 3 retries
    assert any(f["step"] == "thesis" for f in result.failed_validations)


@pytest.mark.asyncio
async def test_deterministic_exception_still_retries():
    """The deterministic short-circuit is scoped to VALIDATION failures only: a
    transient (recoverable) EXCEPTION still retries with back-off, because a
    provider/FX 429 may genuinely succeed on a later attempt (BUG-059 caveat)."""
    call_count = 0

    async def flaky_deterministic_executor(agent, deps, prompt, structured_context, ticker):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ProviderError("rate limit: 429 from FX provider")
        return "good output with enough content"

    step = PipelineStep(
        name="dcf_calc",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=flaky_deterministic_executor,
        deterministic=True,
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    import asyncio as _asyncio
    from unittest.mock import patch as _patch

    with _patch.object(_asyncio, "sleep", new=AsyncMock()):
        result = await pipeline.execute(mock_deps, "AAPL")

    assert call_count == 2  # exception retried, then succeeded
    assert result.steps["dcf_calc"] == "good output with enough content"
    assert result.failed_validations == []


@pytest.mark.asyncio
async def test_deterministic_first_attempt_pass_is_unaffected():
    """deterministic=True must not penalise the happy path: a first-attempt PASS
    returns immediately with no degrade and no retries."""
    progress = _RecordingProgress()

    async def good_executor(agent, deps, prompt, structured_context, ticker):
        return "good output with enough content"

    step = PipelineStep(
        name="technical_analysis",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=good_executor,
        deterministic=True,
    )
    pipeline = Pipeline(steps=[step], max_retries=3)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "AAPL", progress=progress)

    assert result.failed_validations == []
    assert progress.ends == [("technical_analysis", None)]
    assert progress.retries == []
