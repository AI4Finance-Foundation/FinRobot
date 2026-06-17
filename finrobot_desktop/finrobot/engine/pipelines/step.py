from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from pydantic_ai import Agent

from finrobot.engine.data.types import DataType
from finrobot.engine.pipelines.protocols import (
    DefaultAgentExecutor,
    StepExecutor,
    StepValidator,
)

SkillSection: TypeAlias = str | tuple[str, ...]


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
    skill_section: SkillSection | None = None
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
    Do NOT set on steps where a re-run can legitimately differ: any executor
    that consumes the re-prompt or makes an LLM call anywhere in its call
    chain (LLM-narrative steps reword; catalyst_analysis re-classifies news),
    and any executor that swallows transient per-item fetch errors into a
    smaller-but-valid output (peer_analysis drops failed peers, so a
    min_peers validation failure may be provider flakiness a retry fixes)."""
    critical: bool = False
    """When True, a failure after all retries ABORTS the pipeline (raises
    PipelineStepError) rather than appending to failed_validations and
    continuing. Set on hard-prerequisite steps (the data-collection step that
    produces the FinancialData every downstream step reads) — continuing past
    them only yields a confusing crash several steps later (e.g. peer_analysis:
    "target FinancialData not available")."""
    derived_keys: tuple[str, ...] = ()
    """Extra structured_context keys this step's executor writes that are DERIVED
    from its (about-to-be-validated) output — NOT its own ``name``, NOT inputs it
    merely refreshes. The runner stores output BEFORE validating, then on a
    VALIDATION failure pops ``name`` so the rejected output can't feed
    downstream. But an executor that ALSO writes a sibling key built from that
    same output (financial_modeling builds ``valuation_synthesis`` from the
    DCFResult before it is validated) would leave that sibling behind, so the
    rejected numbers still reach the published target via the synthesis
    (Critical-2). List those sibling keys here so they roll back together.
    Inputs / normalizations the executor refreshes (``data_collection``,
    ``price_fx_to_usd``) are valid regardless of this step's output and must NOT
    be listed."""


def iter_skill_sections(skill_section: SkillSection | None) -> tuple[str, ...]:
    """Normalize one-or-many skill ids while keeping legacy single-id callers."""
    if skill_section is None:
        return ()
    if isinstance(skill_section, str):
        return (skill_section,)
    return skill_section
