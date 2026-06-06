"""Per-pipeline Artifact builder functions.

Each builder follows the ArtifactBuilder Protocol:
    def build(result: PipelineResult, ticker: str, deps: FinRobotDeps) -> Artifact

They are referenced by the corresponding pipeline factory functions via the
Pipeline.artifact_builder field and called automatically by Pipeline.execute().

Design decisions:
- raw_data contains the FinancialData model dump (first data-collection step
  structured output). This is a few KB per artifact — acceptable for v1.
- formula_id is set from the pipeline result where available (e.g. DCFResult
  carries a formula_id field), otherwise falls back to the pipeline name.
- Version is read from finrobot.__version__ at build time.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finrobot.artifact.models import Artifact
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.pipelines.base import PipelineResult

from finrobot.artifact.models import (
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
        import finrobot

        return getattr(finrobot, "__version__", "0.1.0")
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
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        # git absent from PATH (pip-installed users / Docker slim / CI) raises
        # FileNotFoundError; a wedged/slow repo (large tree, index.lock) raises
        # subprocess.TimeoutExpired (a SubprocessError). Both must degrade the
        # provenance stamp to None instead of crashing the final artifact-landing
        # step. The previous except (ImportError/AttributeError/TypeError/
        # ValueError) caught none of these — see BUG-070.
        logger.warning("git commit stamp unavailable, degrading to None: %s", exc)
    return None


def _make_artifact_id(ticker: str | None, type_: str) -> str:
    ts = _now().strftime("%Y-%m-%dT%H:%M:%S")
    # Second-granularity ts collides under async concurrency (double-click Run,
    # Coverage batch racing a manual run): same ticker+type in the same second
    # yields an identical id, and the PRIMARY KEY upsert silently overwrites the
    # first run's payload. Append a uuid suffix to make ids collision-proof;
    # ms is not enough under the same event loop. Prefix + ticker/type columns
    # are preserved so prefix-keyed readers/sorts still work. See BUG-023.
    suffix = uuid.uuid4().hex[:6]
    if ticker:
        return f"art_{ts}_{ticker.upper()}_{type_}_{suffix}"
    return f"art_{ts}__cross_{type_}_{suffix}"


def _extract_financial_data_dump(
    result: "PipelineResult", *step_names: str
) -> tuple[str, datetime, dict[str, Any]]:
    """Extract data_source, fetched_at, and raw_data from the first matching structured step.

    Looks through step_names in order; returns the first FinancialData found.
    Falls back to empty data if none found.
    """
    from finrobot.engine.models.financial import FinancialData

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
            dumped: dict[str, Any] = obj.model_dump(mode="json")
            return dumped
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
            for w in val.warnings:
                if w not in warnings:
                    warnings.append(w)
    return warnings


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------


def build_dcf_artifact(
    result: "PipelineResult",
    ticker: str,
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed DCF pipeline result."""
    from finrobot.engine.models.financial import DCFResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "historical_data")
    dcf = result.structured_data.get("dcf_calc")

    # FCF uses the standard D&A-inclusive formula: EBIT(1-T) + D&A - CapEx - ΔNWC.
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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed LBO pipeline result."""
    from finrobot.engine.models.financial import LBOInputs, LBOResult

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "data_collection")
    lbo_inputs = result.structured_data.get("lbo_parameters")
    lbo_result = result.structured_data.get("lbo_calculation")

    formula_warnings: list[str] = []
    if isinstance(lbo_result, LBOResult):
        if lbo_result.irr_formula_warning:
            formula_warnings.append(lbo_result.irr_formula_warning)
        if lbo_result.capital_structure_warning:
            formula_warnings.append(lbo_result.capital_structure_warning)

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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed comps pipeline result."""
    from finrobot.engine.models.financial import PeerComps

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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed DDM pipeline result."""
    from finrobot.engine.models.financial import DDMInputs, DDMResult

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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed earnings analysis pipeline result."""
    from finrobot.engine.models.financial import EarningsResult

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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed equity research pipeline result."""
    from finrobot.engine.compute.operators.audit import audit_artifact
    from finrobot.engine.models.financial import DCFResult, FinancialData

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "data_collection")
    dcf = result.structured_data.get("financial_modeling")

    formula_warnings: list[str] = []
    assumptions_params: dict[str, Any] = {}

    if isinstance(dcf, DCFResult):
        assumptions_params = _safe_dump(dcf.inputs)

    # Collect all meaningful structured outputs for the combined report.
    # ``valuation_synthesis`` MUST persist alongside ``thesis``: it is the
    # deterministic source of ``thesis.price_target`` (see _execute_thesis).
    # Without persisting it the artifact loses the audit trail and the UI
    # can't render the per-method breakdown that justifies the target.
    structured_out: dict[str, Any] = {}
    for key in (
        "sec_filings",
        "xbrl_facts_snapshot",
        "financial_modeling",
        "peer_analysis",
        "valuation_synthesis",
        "thesis",
        "catalyst_analysis",
        "technical_analysis",
    ):
        val = result.structured_data.get(key)
        if val is not None:
            structured_out[key] = _safe_dump(val)
    ownership = result.structured_data.get("ownership_governance_analysis")
    if ownership is not None:
        structured_out["ownership_governance"] = _safe_dump(ownership)

    # Surface the two currency tags so the report chapters can label every
    # amount in its true currency instead of a hardcoded '$' (BUG-030). They
    # ride inside the generic structured dict (no Artifact model change):
    #   - quote_currency    → per-share & market-cap fields (price, 52w hi/lo,
    #     DCF implied price, sniper levels, price target, market_cap)
    #   - reporting_currency → income-statement / balance-sheet absolutes
    #     (revenue, EBITDA, EV, debt, cash, CEO comp)
    # They DISAGREE for foreign-listed ADRs (TSM: quote=USD, reporting=TWD).
    # Sourced from FinancialData.model_dump (raw_data) which carries both tags
    # at top level; default to USD when absent so US reports are unchanged.
    structured_out["currency"] = {
        "quote_currency": str(raw_data.get("quote_currency") or "USD"),
        "reporting_currency": str(raw_data.get("reporting_currency") or "USD"),
    }

    # Mirror the LLM-authored narrative fields into outputs.llm_narrative so
    # that AGENTS.md consumers can read from a semantically named top-level key
    # instead of drilling into structured.thesis.*.  structured.thesis remains
    # the audit-trail source; llm_narrative is a read convenience copy.
    _LLM_NARRATIVE_KEYS = (
        "tagline",
        "key_takeaways",
        "company_overview",
        "valuation_overview",
        "news_summary",
        "competitor_analysis",
        "recommendation",
        "catalysts",
        "risks",
    )
    thesis_dict = structured_out.get("thesis") or {}
    llm_narrative: dict[str, Any] = {
        k: thesis_dict[k] for k in _LLM_NARRATIVE_KEYS if k in thesis_dict
    }

    # Numeric-audit gate (design doc §7, behavior A). Run the definitional verifiers
    # over the finalized snapshot; surface findings as warnings + a structured block.
    # On a blocked_field (a category-error or dimensionally-corrupt number — bank EV,
    # mixed-currency multiple) withhold the rating + price target: a target built on
    # an untrustworthy number must not be published. This runs in the artifact builder
    # — the single sink every report mode converges on — so the gate is symmetric
    # across Mode A/B without touching individual pipeline steps.
    fin_snapshot = next(
        (v for v in result.structured_data.values() if isinstance(v, FinancialData)),
        None,
    )
    audit = audit_artifact(fin_snapshot)
    structured_out["numeric_audit"] = audit.model_dump(mode="json")
    audit_warnings = [
        f"[NUMERIC-AUDIT/{f.severity}] {f.field_key} ({f.check}): {f.evidence}"
        for f in audit.findings
    ]
    if audit.withhold_valuation:
        thesis_out = structured_out.get("thesis")
        if isinstance(thesis_out, dict):
            thesis_out["recommendation"] = "REVIEW"
            thesis_out["price_target"] = None
        if "recommendation" in llm_narrative:
            llm_narrative["recommendation"] = "REVIEW"

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
            llm_narrative=llm_narrative,
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result) + audit_warnings,
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
    deps: "FinRobotDeps",
) -> "Artifact":
    """Build an Artifact from a completed IC Memo pipeline result."""
    from finrobot.engine.models.financial import ICFinancials

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
        if ic.lbo_result.capital_structure_warning:
            formula_warnings.append(ic.lbo_result.capital_structure_warning)

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
