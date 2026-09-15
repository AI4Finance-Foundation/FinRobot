from __future__ import annotations

import logging

from pydantic_ai import Agent

from finrobot.engine.data.types import DataType
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import (
    execute_financial_data_step,
    execute_peer_analysis,
)
from finrobot.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_has_comps_table,
    validate_financial_data,
    validate_peer_comps,
)

logger = logging.getLogger(__name__)


def create_comps_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step comps analysis pipeline (SDK-only, capability folded into research)."""
    from finrobot.artifact.builders import build_comps_artifact

    return Pipeline(
        artifact_builder=build_comps_artifact,
        steps=[
            PipelineStep(
                name="target_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=execute_financial_data_step,
                # statistical_bench reads this FinancialData as the peer target —
                # abort if it fails rather than crash there.
                critical=True,
            ),
            # Deterministic peer analysis: the LLM only SELECTS peer tickers
            # (judgment); code fetches each peer's financials, FX-normalizes to
            # USD, and computes multiples + medians via calculate_multiples /
            # calculate_peer_statistics. Every multiple is provenance-tracked —
            # the LLM never emits free-text numbers. The step is named
            # "statistical_bench" so build_comps_artifact reads the structured
            # PeerComps from the same key.
            PipelineStep(
                name="statistical_bench",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[],
                executor=execute_peer_analysis,
                validator=StructuredValidator(
                    validate_peer_comps,
                    validate_is_non_empty,
                ),
            ),
            PipelineStep(
                name="output_gen",
                skill_section="comps-analysis",
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_has_comps_table),
            ),
        ],
    )
