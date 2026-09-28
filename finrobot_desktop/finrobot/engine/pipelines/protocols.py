from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from finrobot.artifact.models import Artifact
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.pipelines.result import PipelineResult

from pydantic_ai import Agent

from finrobot.engine.models.financial import StepOutput
from finrobot.engine.pipelines.validators import ValidationResult


class ProgressCallback(Protocol):
    """Called at start/end of each pipeline step and on every retry.

    This is a structural Protocol: any object implementing these three async
    methods can be passed to Pipeline.execute(progress=...). CLI, server SSE,
    and SDK consumers each provide their own implementation.
    """

    async def on_step_start(self, step_index: int, total: int, step_name: str) -> None: ...

    async def on_step_end(
        self,
        step_index: int,
        total: int,
        step_name: str,
        duration_s: float,
        error: str | None = None,
    ) -> None:
        """Signal a step finished. ``error`` is non-None when the step DEGRADED
        — it ran to completion but failed validation after all retries on a
        non-critical step (BUG-058). Consumers render that as a warning, not a
        success ✓."""
        ...

    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# Strategy protocols for step execution and validation
# ---------------------------------------------------------------------------


class StepExecutor(Protocol):
    """How a pipeline step produces its output.

    ``**kwargs`` carries per-run overrides forwarded verbatim from
    ``Pipeline.execute(**kwargs)`` (e.g. ``peers=[...]`` for comps). Every
    executor accepts them so the call site stays uniform; executors that don't
    need an override simply ignore the extras.
    """

    async def __call__(
        self,
        agent: Agent,
        deps: "FinRobotDeps",
        prompt: str,
        structured_context: dict[str, object],
        ticker: str,
        **kwargs: object,
    ) -> "StepOutput | str": ...


class StepValidator(Protocol):
    """How a pipeline step validates its output."""

    def __call__(self, output: str | object) -> ValidationResult: ...


class DefaultAgentExecutor:
    """Runs agent.run(prompt) — the default for steps without custom execute_fn."""

    async def __call__(
        self,
        agent: Agent,
        deps: "FinRobotDeps",
        prompt: str,
        structured_context: dict[str, object],
        ticker: str,
        **_kwargs: object,
    ) -> str:
        result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        return result.output  # type: ignore[no-any-return]


class TextValidator:
    """Wraps a Callable[[str], ValidationResult] for text-only validation."""

    def __init__(self, fn: Callable[[str], ValidationResult]) -> None:
        self._fn = fn

    def __call__(self, output: str | object) -> ValidationResult:
        return self._fn(str(output))


class StructuredValidator:
    """Validates structured output, falling back to text validation."""

    def __init__(
        self,
        structured_fn: Callable[..., ValidationResult],
        text_fn: Callable[[str], ValidationResult],
    ) -> None:
        self._structured_fn = structured_fn
        self._text_fn = text_fn

    def __call__(self, output: str | object) -> ValidationResult:
        if not isinstance(output, str):
            return self._structured_fn(output)
        return self._text_fn(output)


class ArtifactBuilder(Protocol):
    """Callable that converts a completed PipelineResult into an Artifact.

    Each pipeline factory provides its own builder. The builder is stored
    on the Pipeline instance and called by execute() after all steps succeed.

    Signature::

        def my_builder(
            result: PipelineResult,
            ticker: str,
            deps: FinRobotDeps,
        ) -> Artifact: ...
    """

    def __call__(
        self,
        result: "PipelineResult",
        ticker: str,
        deps: "FinRobotDeps",
    ) -> "Artifact": ...
