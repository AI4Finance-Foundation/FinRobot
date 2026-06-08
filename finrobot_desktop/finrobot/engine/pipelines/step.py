from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import Agent

from finrobot.engine.data.types import DataType
from finrobot.engine.pipelines.protocols import (
    DefaultAgentExecutor,
    StepExecutor,
    StepValidator,
)


class PipelineStepError(RuntimeError):
    """A critical pipeline step failed after exhausting retries.

    Raised by Pipeline.execute() to ABORT the run instead of continuing
    best-effort. Subclasses RuntimeError so the runs.py handler already catches
    it and transitions the run to ``failed`` with this message.
    """

    def __init__(self, step_name: str, error: str) -> None:
        self.step_name = step_name
        self.error = error
        super().__init__(f"Critical step '{step_name}' failed: {error}")


@dataclass
class PipelineStep:
    """A single enforced step in a financial analysis pipeline."""

    name: str
    agent: Agent
    validator: StepValidator
    executor: StepExecutor = field(default_factory=DefaultAgentExecutor)
    required_data: list[str | DataType] = field(default_factory=list)
    skill_section: str | None = None
    deterministic: bool = False
    """When True, the executor is a PURE function of structured_context +
    data_layer — it ignores the (re-)prompt entirely (e.g. _execute_dcf_calc,
    _execute_financial_modeling). On a VALIDATION failure, re-running it
    re-produces byte-identical failing output, so the validation-retry loop is
    a no-op that burns the whole budget (and, for provider-heavy executors,
    re-fetches every input each attempt) before degrading (BUG-059). For such
    steps a validation failure short-circuits straight to degrade. The
    EXCEPTION-retry path is untouched: a transient provider/FX error (429,
    timeout) genuinely may succeed on a back-off retry, so those still loop.
    Do NOT set on steps whose executor consumes the re-prompt (peer_analysis
    re-selects peers; LLM-narrative steps reword)."""
    critical: bool = False
    """When True, a failure after all retries ABORTS the pipeline (raises
    PipelineStepError) rather than appending to failed_validations and
    continuing. Set on hard-prerequisite steps (the data-collection step that
    produces the FinancialData every downstream step reads) — continuing past
    them only yields a confusing crash several steps later (e.g. peer_analysis:
    "target FinancialData not available")."""
