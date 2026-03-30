import logging
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from finagent.engine.pipelines.validators import ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    """A single enforced step in a financial analysis pipeline."""
    name: str
    agent: Agent
    validate: Callable[[str], ValidationResult]
    required_data: list[str] = field(default_factory=list)
    skill_section: str | None = None   # which part of the skill to inject


@dataclass
class Pipeline:
    """Code-enforced sequence of analysis steps.

    Each step:
    1. Receives structured data from previous steps (not free-text)
    2. Gets skill methodology injected as system prompt (P1a+)
    3. Runs a dedicated agent
    4. Output is validated before proceeding
    5. If validation fails, step retries (up to max_retries, default 2)
    """
    steps: list[PipelineStep]
    max_retries: int = 2

    async def execute(self, ctx: "RunContext", ticker: str, **kwargs) -> "PipelineResult":
        results: dict[str, str] = {}
        total = len(self.steps)

        for i, step in enumerate(self.steps, start=1):
            print(f"Step {i}/{total}: {step.name}...", flush=True)

            # 1. Gather required data
            step_data = await self._gather_data(ctx, step.required_data, ticker, results)

            # 2. Load skill methodology (P1a+ — None in P0)
            methodology = ""
            if step.skill_section and ctx.deps.skill_runtime:
                skill = ctx.deps.skill_runtime.get(step.skill_section)
                if skill:
                    methodology = skill.full_content

            # 3. Run agent with methodology + data
            prompt = self._build_step_prompt(step, step_data, methodology)
            step_result = await step.agent.run(prompt, deps=ctx.deps)

            # 4. Validate output, retry up to max_retries
            for attempt in range(self.max_retries):
                validation = step.validate(step_result.output)
                if validation.passed:
                    break
                logger.warning(
                    f"Step '{step.name}' attempt {attempt + 1}/{self.max_retries} "
                    f"failed validation: {validation.error}"
                )
                step_result = await step.agent.run(
                    f"Previous output failed validation: {validation.error}\n"
                    f"Fix the issues and try again.\n\n{step_result.output}",
                    deps=ctx.deps,
                )
            else:
                # Retries exhausted — continue with best-effort output rather than crash
                logger.warning(
                    f"Pipeline step '{step.name}' failed validation after "
                    f"{self.max_retries} retries. Continuing with best-effort output."
                )

            # 5. Store for next steps
            results[step.name] = step_result.output
            print(f"Step {i}/{total}: {step.name} ✓", flush=True)

        return PipelineResult(steps=results)

    async def _gather_data(
        self,
        ctx: "RunContext",
        required_data: list[str],
        ticker: str,
        previous_results: dict[str, str],
    ) -> str:
        if not required_data:
            # Use previous step results as context
            if not previous_results:
                return ""
            parts = []
            for step_name, output in previous_results.items():
                parts.append(f"=== {step_name} ===\n{output}")
            return "\n\n".join(parts)

        # Fetch required data types via DataLayer
        parts = []
        for data_type in required_data:
            try:
                result = await ctx.deps.data_layer.fetch(data_type, ticker)
                parts.append(result.to_context_string())
            except Exception as e:
                logger.warning(f"Failed to fetch {data_type} for {ticker}: {e}")
                parts.append(f"[{data_type}: data unavailable — {e}]")
        return "\n\n".join(parts)

    def _build_step_prompt(self, step: PipelineStep, step_data: str, methodology: str) -> str:
        parts = [f"Step: {step.name}"]
        if step_data:
            parts.append(f"Data:\n{step_data}")
        if methodology:
            parts.append(f"Methodology:\n{methodology}")
        parts.append("Produce a detailed, structured analysis for this step.")
        return "\n\n".join(parts)


class PipelineResult(BaseModel):
    steps: dict[str, str]

    def format_summary(self) -> str:
        """Concatenate all step outputs into a readable Markdown report."""
        if not self.steps:
            return ""
        parts = ["# FinAgent Analysis Report\n"]
        for step_name, output in self.steps.items():
            title = step_name.replace("_", " ").title()
            parts.append(f"## {title}\n\n{output}")
        return "\n\n---\n\n".join(parts)
