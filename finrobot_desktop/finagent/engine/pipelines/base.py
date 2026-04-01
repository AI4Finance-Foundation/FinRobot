import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from finagent.engine.models.financial import StepOutput
from finagent.engine.pipelines.validators import ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    """A single enforced step in a financial analysis pipeline."""
    name: str
    agent: Agent
    validate: Callable[[str], ValidationResult]
    required_data: list[str] = field(default_factory=list)
    skill_section: str | None = None

    # NEW in P1.5: custom execution hook
    execute_fn: Callable[..., Awaitable["StepOutput | str"]] | None = None
    """Optional async function that replaces the default agent.run() behavior.

    Signature: async (agent, deps, prompt, structured_context, ticker) -> StepOutput | str
    """

    # NEW in P1.5: typed output validator
    validate_structured: Callable[[Any], ValidationResult] | None = None
    """Optional validator for structured data (e.g., validate_dcf_result(DCFResult))."""


@dataclass
class Pipeline:
    """Code-enforced sequence of analysis steps."""
    steps: list[PipelineStep]
    max_retries: int = 2

    async def execute(self, deps: "FinAgentDeps", ticker: str, **kwargs) -> "PipelineResult":
        results: dict[str, str] = {}
        structured_results: dict[str, Any] = {}
        failed_validations: list[str] = []
        total = len(self.steps)

        for i, step in enumerate(self.steps, start=1):
            logger.info(f"Step {i}/{total}: {step.name}...")

            step_data = await self._gather_data(deps, step.required_data, ticker, results)

            methodology = ""
            if step.skill_section and deps.skill_runtime:
                skill = deps.skill_runtime.get(step.skill_section)
                if skill:
                    methodology = skill.full_content

            prompt = self._build_step_prompt(step, step_data, methodology, structured_results)

            # Execute: custom fn OR default agent.run()
            if step.execute_fn is not None:
                output = await step.execute_fn(step.agent, deps, prompt, structured_results, ticker)
            else:
                step_result = await step.agent.run(prompt, deps=deps)
                output = step_result.output

            # Parse output
            if isinstance(output, StepOutput):
                results[step.name] = output.text
                if output.structured is not None:
                    structured_results[step.name] = output.structured
                    logger.info(f"Step '{step.name}' produced structured data: {type(output.structured).__name__}")
            elif isinstance(output, str):
                results[step.name] = output
            else:
                results[step.name] = str(output)

            # Validate: typed (if available + structured data) OR text
            if step.validate_structured is not None and step.name in structured_results:
                validation = step.validate_structured(structured_results[step.name])
            else:
                validation = step.validate(results[step.name])

            # Retry on validation failure
            if not validation.passed:
                for attempt in range(self.max_retries):
                    logger.warning(
                        f"Step '{step.name}' attempt {attempt + 1}/{self.max_retries} "
                        f"failed validation: {validation.error}"
                    )
                    retry_prompt = (
                        f"Previous output failed validation: {validation.error}\n"
                        f"Fix the issues and try again.\n\n{results[step.name]}"
                    )
                    if step.execute_fn is not None:
                        output = await step.execute_fn(step.agent, deps, retry_prompt, structured_results, ticker)
                    else:
                        step_result = await step.agent.run(retry_prompt, deps=deps)
                        output = step_result.output

                    if isinstance(output, StepOutput):
                        results[step.name] = output.text
                        if output.structured is not None:
                            structured_results[step.name] = output.structured
                    elif isinstance(output, str):
                        results[step.name] = output
                    else:
                        results[step.name] = str(output)

                    if step.validate_structured is not None and step.name in structured_results:
                        validation = step.validate_structured(structured_results[step.name])
                    else:
                        validation = step.validate(results[step.name])

                    if validation.passed:
                        break
                else:
                    logger.warning(
                        f"Pipeline step '{step.name}' failed validation after "
                        f"{self.max_retries} retries. Continuing with best-effort output."
                    )
                    failed_validations.append(step.name)

            logger.info(f"Step {i}/{total}: {step.name} \u2713")

        return PipelineResult(steps=results, structured_data=structured_results, failed_validations=failed_validations)

    async def _gather_data(
        self,
        deps: "FinAgentDeps",
        required_data: list[str],
        ticker: str,
        previous_results: dict[str, str],
    ) -> str:
        if not required_data:
            if not previous_results:
                return ""
            parts = []
            for step_name, output in previous_results.items():
                parts.append(f"=== {step_name} ===\n{output}")
            return "\n\n".join(parts)

        parts = []
        for data_type in required_data:
            try:
                result = await deps.data_layer.fetch(data_type, ticker)
                parts.append(result.to_context_string())
            except Exception as e:
                logger.warning(f"Failed to fetch {data_type} for {ticker}: {e}")
                parts.append(f"[{data_type}: data unavailable — {e}]")
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
    structured_data: dict[str, Any] = Field(default_factory=dict)
    failed_validations: list[str] = Field(default_factory=list)

    def get_data(self, step_name: str) -> Any:
        """Get structured data from a previous step. Returns None if not found."""
        return self.structured_data.get(step_name)

    def format_summary(self) -> str:
        """Concatenate all step outputs into a readable Markdown report."""
        if not self.steps:
            return ""
        parts = ["# FinAgent Analysis Report\n"]
        if self.failed_validations:
            names = ", ".join(self.failed_validations)
            parts[0] += (
                f"\n> **Warning:** The following steps did not pass validation "
                f"and may contain inaccuracies: {names}\n"
            )
        for step_name, output in self.steps.items():
            title = step_name.replace("_", " ").title()
            parts.append(f"## {title}\n\n{output}")
        return "\n\n---\n\n".join(parts)
