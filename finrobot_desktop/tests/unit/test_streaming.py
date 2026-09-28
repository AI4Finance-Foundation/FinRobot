"""Tests for Pipeline progress callback (Track 1 Task 1).

Verifies the ProgressCallback protocol is invoked at start/end of every step
and that progress=None keeps the original behavior (backwards compatibility).
"""

from unittest.mock import MagicMock

from finrobot.engine.pipelines.base import Pipeline, PipelineStep, TextValidator
from finrobot.engine.pipelines.validators import ValidationResult, validate_is_non_empty


class FakeProgress:
    """Captures every ProgressCallback event in insertion order."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def on_step_start(self, step_index: int, total: int, step_name: str) -> None:
        self.events.append(("start", step_index, total, step_name))

    async def on_step_end(
        self,
        step_index: int,
        total: int,
        step_name: str,
        duration_s: float,
        error: str | None = None,
    ) -> None:
        self.events.append(("end", step_index, total, step_name))

    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None:
        self.events.append(("retry", step_index, step_name, attempt))


def _make_step(name: str, output: str = "step output") -> PipelineStep:
    async def fn(agent, deps, prompt, structured_context, ticker):
        return output

    return PipelineStep(
        name=name,
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=fn,
    )


async def test_progress_callback_receives_all_events():
    """Three-step pipeline: expect 3 start + 3 end events in order."""
    progress = FakeProgress()
    steps = [_make_step("s1"), _make_step("s2"), _make_step("s3")]
    pipeline = Pipeline(steps=steps)
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    await pipeline.execute(mock_deps, "TEST", progress=progress)

    starts = [e for e in progress.events if e[0] == "start"]
    ends = [e for e in progress.events if e[0] == "end"]
    assert len(starts) == 3
    assert len(ends) == 3
    assert [e[1] for e in starts] == [1, 2, 3]
    assert [e[3] for e in starts] == ["s1", "s2", "s3"]
    assert all(e[2] == 3 for e in starts)  # total passed correctly


async def test_progress_none_is_backwards_compatible():
    """progress=None (default) must leave Pipeline.execute unchanged."""
    pipeline = Pipeline(steps=[_make_step("s1"), _make_step("s2")])
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    result = await pipeline.execute(mock_deps, "TEST")  # no progress kwarg
    assert set(result.steps.keys()) == {"s1", "s2"}


async def test_progress_retry_events():
    """Validation fails once → retry event emitted before the second attempt."""
    call_count = 0

    def flaky_validate(output: str) -> ValidationResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ValidationResult(passed=False, error="transient")
        return ValidationResult(passed=True)

    async def fn(agent, deps, prompt, structured_context, ticker):
        return "some output"

    step = PipelineStep(
        name="flaky",
        agent=MagicMock(),
        validator=TextValidator(flaky_validate),
        executor=fn,
    )
    pipeline = Pipeline(steps=[step], max_retries=2)
    progress = FakeProgress()
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None

    await pipeline.execute(mock_deps, "TEST", progress=progress)

    retries = [e for e in progress.events if e[0] == "retry"]
    assert len(retries) == 1
    assert retries[0][1] == 1  # step_index
    assert retries[0][2] == "flaky"
    assert retries[0][3] == 1  # attempt number
