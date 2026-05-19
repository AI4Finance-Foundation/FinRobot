"""Per-pipeline Artifact builder functions.

Each builder follows the ArtifactBuilder Protocol:
    def build(result: PipelineResult, ticker: str, deps: FinAgentDeps) -> Artifact

They are referenced by the corresponding pipeline factory functions via the
Pipeline.artifact_builder field and called automatically by Pipeline.execute().

Design decisions:
- raw_data contains the FinancialData model dump (first data-collection step
  structured output). This is a few KB per artifact — acceptable for v1.
- formula_id is set from the pipeline result where available (e.g. DCFResult
  carries a formula_id field), otherwise falls back to the pipeline name.
- Version is read from finagent.__version__ at build time.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finagent.artifact.models import Artifact
    from finagent.engine.deps import FinAgentDeps
    from finagent.engine.pipelines.base import PipelineResult

from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _get_version() -> str:
    try:
        import finagent

        return getattr(finagent, "__version__", "0.1.0")
    except ImportError:
        return "0.1.0"


def _get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return None


def _make_artifact_id(ticker: str | None, type_: str) -> str:
    ts = _now().strftime("%Y-%m-%dT%H:%M:%S")
    if ticker:
        return f"art_{ts}_{ticker.upper()}_{type_}"
    return f"art_{ts}__cross_{type_}"


def _extract_financial_data_dump(
    result: "PipelineResult", *step_names: str
) -> tuple[str, datetime, dict[str, Any]]:
    """Extract data_source, fetched_at, and raw_data from the first matching structured step.

    Looks through step_names in order; returns the first FinancialData found.
    Falls back to empty data if none found.
    """
    from finagent.engine.models.financial import FinancialData

    for name in step_names:
        val = result.structured_data.get(name)
        if isinstance(val, FinancialData):
            return (
                val.data_source,
                val.timestamp,
                val.model_dump(mode="json"),
            )
    return "unknown", _now(), {}


def _safe_dump(obj: Any) -> dict[str, Any]:
    """Dump a Pydantic model or return empty dict on failure."""
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")  # type: ignore[return-value]
        except (ImportError, AttributeError, TypeError, ValueError):
            return {}
    if isinstance(obj, dict):
        return obj
    return {}


def _make_base_compute_version(
    formula_id: str,
    formula_warnings: list[str] | None = None,
) -> ArtifactComputeVersion:
    return ArtifactComputeVersion(
        version=_get_version(),
        git_commit=_get_git_commit(),
        formula_id=formula_id,
        formula_warnings=formula_warnings or [],
    )


def _collect_warnings(result: "PipelineResult") -> list[str]:
    """Collect warnings from all structured data objects in the result."""
    warnings: list[str] = list(result.warnings)
    for val in result.structured_data.values():
        if hasattr(val, "warnings"):
            for w in val.warnings:  # type: ignore[union-attr]
                if w not in warnings:
                    warnings.append(w)
    return warnings


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------


def build_dcf_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed DCF pipeline result."""
    from finagent.engine.models.financial import DCFResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "historical_data")
    dcf = result.structured_data.get("dcf_calc")

    # Standard D&A-inclusive formula is now the only path — simplified-FCF
    # branch (and its overstate/understate warning) was removed in Phase B.
    formula_id = "dcf_standard_with_da_v2"
    formula_warnings: list[str] = []
    assumptions_params: dict[str, Any] = {}

    if isinstance(dcf, DCFResult):
        assumptions_params = _safe_dump(dcf.inputs)

    return Artifact(
        id=_make_artifact_id(ticker, "dcf"),
        ticker=ticker.upper(),
        type="dcf",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(parameters=assumptions_params),
        compute_version=_make_base_compute_version(formula_id, formula_warnings),
        outputs=ArtifactOutputs(
            structured=_safe_dump(dcf),
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:dcf",
        ),
    )


# ---------------------------------------------------------------------------
# LBO
# ---------------------------------------------------------------------------


def build_lbo_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed LBO pipeline result."""
    from finagent.engine.models.financial import LBOInputs, LBOResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "data_collection")
    lbo_inputs = result.structured_data.get("lbo_parameters")
    lbo_result = result.structured_data.get("lbo_calculation")

    formula_warnings: list[str] = []
    if isinstance(lbo_result, LBOResult) and lbo_result.irr_formula_warning:
        formula_warnings = [lbo_result.irr_formula_warning]

    return Artifact(
        id=_make_artifact_id(ticker, "lbo"),
        ticker=ticker.upper(),
        type="lbo",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(
            parameters=_safe_dump(lbo_inputs) if isinstance(lbo_inputs, LBOInputs) else {},
        ),
        compute_version=_make_base_compute_version("lbo_v1", formula_warnings),
        outputs=ArtifactOutputs(
            structured=_safe_dump(lbo_result),
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:lbo",
        ),
    )


# ---------------------------------------------------------------------------
# Comps
# ---------------------------------------------------------------------------


def build_comps_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed comps pipeline result."""
    from finagent.engine.models.financial import PeerComps

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "target_data")
    peer_comps = result.structured_data.get("statistical_bench")

    # Collect peer tickers for cross_tickers field
    cross_tickers: list[str] = []
    if isinstance(peer_comps, PeerComps):
        cross_tickers = [p.ticker for p in peer_comps.peers]

    return Artifact(
        id=_make_artifact_id(ticker, "comps"),
        ticker=ticker.upper(),
        cross_tickers=cross_tickers,
        type="comps",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(parameters={"peers": cross_tickers}),
        compute_version=_make_base_compute_version("comps_multiples_v1"),
        outputs=ArtifactOutputs(
            structured=_safe_dump(peer_comps),
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:comps",
        ),
    )


# ---------------------------------------------------------------------------
# DDM
# ---------------------------------------------------------------------------


def build_ddm_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed DDM pipeline result."""
    from finagent.engine.models.financial import DDMInputs, DDMResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "historical_data")
    ddm_inputs = result.structured_data.get("ddm_params")
    ddm_result = result.structured_data.get("ddm_calc")

    return Artifact(
        id=_make_artifact_id(ticker, "ddm"),
        ticker=ticker.upper(),
        type="ddm",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(
            parameters=_safe_dump(ddm_inputs) if isinstance(ddm_inputs, DDMInputs) else {},
        ),
        compute_version=_make_base_compute_version("ddm_gordon_growth_v1"),
        outputs=ArtifactOutputs(
            structured=_safe_dump(ddm_result) if isinstance(ddm_result, DDMResult) else {},
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:ddm",
        ),
    )


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------


def build_earnings_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed earnings analysis pipeline result."""
    from finagent.engine.models.financial import EarningsResult

    # Earnings pipeline doesn't use the standard financial data collection step
    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "financial_context")
    earnings = result.structured_data.get("earnings_data")

    params: dict[str, Any] = {}
    if isinstance(earnings, EarningsResult):
        params = {
            "ticker": earnings.ticker,
            "quarters_analyzed": len(earnings.surprises),
            "beat_threshold_pct": 2.0,
        }

    return Artifact(
        id=_make_artifact_id(ticker, "earnings"),
        ticker=ticker.upper(),
        type="earnings",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(parameters=params),
        compute_version=_make_base_compute_version("earnings_surprise_v1"),
        outputs=ArtifactOutputs(
            structured=_safe_dump(earnings),
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:earnings",
        ),
    )


# ---------------------------------------------------------------------------
# Equity Research
# ---------------------------------------------------------------------------


def build_equity_research_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed equity research pipeline result."""
    from finagent.engine.models.financial import DCFResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "data_collection")
    dcf = result.structured_data.get("financial_modeling")

    formula_warnings: list[str] = []
    assumptions_params: dict[str, Any] = {}

    if isinstance(dcf, DCFResult):
        assumptions_params = _safe_dump(dcf.inputs)

    # Collect all meaningful structured outputs for the combined report
    structured_out: dict[str, Any] = {}
    for key in ("financial_modeling", "peer_analysis", "thesis", "catalyst_analysis"):
        val = result.structured_data.get(key)
        if val is not None:
            structured_out[key] = _safe_dump(val)

    return Artifact(
        id=_make_artifact_id(ticker, "equity_research"),
        ticker=ticker.upper(),
        type="equity_research",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(parameters=assumptions_params),
        compute_version=_make_base_compute_version(
            "equity_research_dcf_standard_with_da_v2"
            if isinstance(dcf, DCFResult)
            else "equity_research_v1",
            formula_warnings,
        ),
        outputs=ArtifactOutputs(
            structured=structured_out,
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:equity_research",
        ),
    )


# ---------------------------------------------------------------------------
# IC Memo
# ---------------------------------------------------------------------------


def build_ic_memo_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinAgentDeps",
) -> "Artifact":
    """Build an Artifact from a completed IC Memo pipeline result."""
    from finagent.engine.models.financial import ICFinancials

    ic = result.structured_data.get("financial_analysis")

    data_source = "unknown"
    fetched_at = _now()
    raw_data: dict[str, Any] = {}
    assumptions_params: dict[str, Any] = {}
    formula_warnings: list[str] = []

    if isinstance(ic, ICFinancials):
        data_source = ic.financial_data.data_source
        fetched_at = ic.financial_data.timestamp
        raw_data = ic.financial_data.model_dump(mode="json")
        assumptions_params = {
            "dcf_inputs": _safe_dump(ic.dcf_result.inputs),
            "lbo_inputs": {},  # LBOInputs stored in lbo_result.inputs if available
        }
        if ic.lbo_result.irr_formula_warning:
            formula_warnings.append(ic.lbo_result.irr_formula_warning)

    structured_out: dict[str, Any] = {}
    if isinstance(ic, ICFinancials):
        structured_out = {
            "dcf_result": _safe_dump(ic.dcf_result),
            "lbo_result": _safe_dump(ic.lbo_result),
        }

    return Artifact(
        id=_make_artifact_id(ticker, "ic_memo"),
        ticker=ticker.upper(),
        type="ic_memo",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=fetched_at,
            raw_data=raw_data,
        ),
        assumptions=ArtifactAssumptions(parameters=assumptions_params),
        compute_version=_make_base_compute_version("ic_memo_dcf_lbo_v1", formula_warnings),
        outputs=ArtifactOutputs(
            structured=structured_out,
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result),
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:ic_memo",
        ),
    )
