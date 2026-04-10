import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import StepOutput
from finagent.engine.pipelines.validators import ValidationResult

logger = logging.getLogger(__name__)


class ProgressCallback(Protocol):
    """Called at start/end of each pipeline step and on every retry.

    This is a structural Protocol: any object implementing these three async
    methods can be passed to Pipeline.execute(progress=...). CLI, server SSE,
    and SDK consumers each provide their own implementation.
    """

    async def on_step_start(
        self, step_index: int, total: int, step_name: str
    ) -> None: ...

    async def on_step_end(
        self, step_index: int, total: int, step_name: str, duration_s: float
    ) -> None: ...

    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None: ...


@dataclass
class PipelineStep:
    """A single enforced step in a financial analysis pipeline."""

    name: str
    agent: Agent
    validate: Callable[[str], ValidationResult]
    required_data: list[str | DataType] = field(default_factory=list)
    skill_section: str | None = None

    # NEW in P1.5: custom execution hook
    execute_fn: Callable[..., Awaitable["StepOutput | str"]] | None = None
    """Optional async function that replaces the default agent.run() behavior.

    Signature: async (agent, deps, prompt, structured_context, ticker) -> StepOutput | str
    """

    # NEW in P1.5: typed output validator
    validate_structured: Callable[[object], ValidationResult] | None = None
    """Optional validator for structured data (e.g., validate_dcf_result(DCFResult))."""


@dataclass
class Pipeline:
    """Code-enforced sequence of analysis steps."""

    steps: list[PipelineStep]
    max_retries: int = 3

    async def execute(
        self,
        deps: "FinAgentDeps",
        ticker: str,
        progress: ProgressCallback | None = None,
        **kwargs,
    ) -> "PipelineResult":
        results: dict[str, str] = {}
        structured_results: dict[str, object] = {}
        failed_validations: list[dict[str, str]] = []
        total = len(self.steps)

        for i, step in enumerate(self.steps, start=1):
            logger.info(f"Step {i}/{total}: {step.name}...")
            if progress is not None:
                await progress.on_step_start(i, total, step.name)

            step_data = await self._gather_data(deps, step.required_data, ticker, results)

            methodology = ""
            if step.skill_section and deps.skill_runtime:
                skill = deps.skill_runtime.get(step.skill_section)
                if skill:
                    methodology = skill.full_content

            prompt = self._build_step_prompt(step, step_data, methodology, structured_results)

            t0 = time.monotonic()
            validation_error = await self._run_step(
                step, deps, prompt, ticker, results, structured_results,
                step_index=i, progress=progress,
            )
            elapsed = time.monotonic() - t0
            if validation_error:
                failed_validations.append({"step": step.name, "error": validation_error})

            if progress is not None:
                await progress.on_step_end(i, total, step.name, elapsed)

            logger.info(f"Step {i}/{total}: {step.name} \u2713")

        return PipelineResult(
            steps=results, structured_data=structured_results, failed_validations=failed_validations
        )

    async def _execute_step_once(
        self,
        step: PipelineStep,
        deps: "FinAgentDeps",
        prompt: str,
        structured_results: dict[str, object],
        ticker: str,
    ) -> StepOutput | str:
        """Execute a single step once (via execute_fn or default agent.run()).

        Returns the raw output before it is stored into results dicts.
        """
        if step.execute_fn is not None:
            return await step.execute_fn(step.agent, deps, prompt, structured_results, ticker)
        step_result = await step.agent.run(prompt, deps=deps)
        return step_result.output

    @staticmethod
    def _store_output(
        step_name: str,
        output: StepOutput | str,
        results: dict[str, str],
        structured_results: dict[str, object],
    ) -> None:
        """Parse step output and store text/structured data into the result dicts."""
        if isinstance(output, StepOutput):
            results[step_name] = output.text
            if output.structured is not None:
                structured_results[step_name] = output.structured
                logger.info(
                    f"Step '{step_name}' produced structured data: "
                    f"{type(output.structured).__name__}"
                )
        elif isinstance(output, str):
            results[step_name] = output
        else:
            results[step_name] = str(output)

    @staticmethod
    def _validate_step(
        step: PipelineStep,
        step_name: str,
        results: dict[str, str],
        structured_results: dict[str, object],
    ) -> "ValidationResult":
        """Choose the right validator and return the validation result."""
        if step.validate_structured is not None and step_name in structured_results:
            return step.validate_structured(structured_results[step_name])
        return step.validate(results[step_name])

    async def _run_step(
        self,
        step: PipelineStep,
        deps: "FinAgentDeps",
        prompt: str,
        ticker: str,
        results: dict[str, str],
        structured_results: dict[str, object],
        step_index: int = 0,
        progress: ProgressCallback | None = None,
    ) -> str | None:
        """Execute a single pipeline step with retry logic.

        Encapsulates: execution -> output storage -> validation -> retry loop.
        Returns the validation error string if the step failed after all retries,
        or None if the step passed validation.
        """
        # First attempt
        output = await self._execute_step_once(step, deps, prompt, structured_results, ticker)
        self._store_output(step.name, output, results, structured_results)
        validation = self._validate_step(step, step.name, results, structured_results)

        if validation.passed:
            return None

        # Retry loop
        for attempt in range(self.max_retries):
            logger.warning(
                f"Step '{step.name}' retry {attempt + 1}/{self.max_retries}: "
                f"{validation.error}"
            )
            if progress is not None:
                await progress.on_step_retry(
                    step_index, step.name, attempt + 1, validation.error or ""
                )
            retry_prompt = (
                f"Previous output failed validation: {validation.error}\n"
                f"Fix the issues and try again.\n\n{results[step.name]}"
            )
            output = await self._execute_step_once(
                step, deps, retry_prompt, structured_results, ticker,
            )
            self._store_output(step.name, output, results, structured_results)
            validation = self._validate_step(step, step.name, results, structured_results)

            if validation.passed:
                return None

        logger.warning(
            f"Pipeline step '{step.name}' failed validation after "
            f"{self.max_retries} retries: {validation.error}. "
            f"Continuing with best-effort output."
        )
        return validation.error

    async def _gather_data(
        self,
        deps: "FinAgentDeps",
        required_data: "list[str | DataType]",
        ticker: str,
        previous_results: dict[str, str],
    ) -> str:
        if not required_data:
            if not previous_results:
                return ""
            # Compact mode: pass the last 2 steps' full text + 1-line summaries of
            # everything before them. Step N often needs both step N-1 and N-2
            # (e.g., thesis reads financial_modeling AND peer_analysis), so 2 is
            # the sweet spot between context completeness and prompt size. Structured
            # data from earlier steps is still available via structured_context.
            keys = list(previous_results.keys())
            parts: list[str] = []
            for name in keys[:-2]:
                text = previous_results[name]
                word_count = len(text.split())
                parts.append(
                    f"[Previous: {name} \u2014 {word_count} words, "
                    f"see structured_context for data]"
                )
            for name in keys[-2:]:
                parts.append(f"=== {name} ===\n{previous_results[name]}")
            return "\n\n".join(parts)

        parts = []
        for data_type in required_data:
            try:
                result = await deps.data_layer.fetch(data_type, ticker)
                parts.append(result.to_context_string())
            except (ProviderError, ValueError, KeyError) as e:
                logger.warning(f"Failed to fetch {data_type} for {ticker}: {e}")
                parts.append(f"[{data_type}: data unavailable \u2014 {e}]")
        return "\n\n".join(parts)

    def _build_step_prompt(
        self,
        step: PipelineStep,
        step_data: str,
        methodology: str,
        structured_context: dict,
    ) -> str:
        parts = [f"Step: {step.name}"]
        if step_data:
            parts.append(f"Data:\n{step_data}")
        if methodology:
            parts.append(f"Methodology:\n{methodology}")
        if structured_context:
            sc_parts = ["Structured Data from Previous Steps:"]
            for name, model in structured_context.items():
                if hasattr(model, "model_dump_json"):
                    sc_parts.append(f"### {name}:\n```json\n{model.model_dump_json(indent=2)}\n```")
                else:
                    sc_parts.append(f"### {name}:\n```\n{model}\n```")
            parts.append("\n".join(sc_parts))
        parts.append("Produce a detailed, structured analysis for this step.")
        return "\n\n".join(parts)


class PipelineResult(BaseModel):
    steps: dict[str, str]
    structured_data: dict[str, object] = Field(default_factory=dict)
    failed_validations: list[dict[str, str]] = Field(default_factory=list)

    def get_data(self, step_name: str) -> object | None:
        """Get structured data from a previous step. Returns None if not found."""
        return self.structured_data.get(step_name)

    @property
    def has_failures(self) -> bool:
        return len(self.failed_validations) > 0

    def format_summary(self) -> str:
        """Concatenate all step outputs into a readable Markdown report."""
        if not self.steps:
            return ""
        parts = ["# FinAgent Analysis Report\n"]
        if self.failed_validations:
            warning_lines = [
                "\n> **Warning — validation failures:**",
            ]
            for failure in self.failed_validations:
                step = failure.get("step", "unknown")
                error = failure.get("error", "unspecified error")
                warning_lines.append(f"> - **{step}**: {error}")
            warning_lines.append(
                "> \n> Results from failed steps may contain inaccuracies. "
                "Verify before acting on this data.\n"
            )
            parts[0] += "\n".join(warning_lines)
        for step_name, output in self.steps.items():
            title = step_name.replace("_", " ").title()
            parts.append(f"## {title}\n\n{output}")
        return "\n\n---\n\n".join(parts)
