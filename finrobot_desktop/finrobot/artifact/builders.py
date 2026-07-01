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
from collections.abc import Callable
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
from finrobot.engine.compute.operators.report_drift import (
    collect_numeric_leaves,
    detect_report_drift,
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


def _extract_financial_data(result: "PipelineResult", *step_names: str) -> Any | None:
    """Return the first FinancialData structured output from named steps."""
    from finrobot.engine.models.financial import FinancialData

    for name in step_names:
        val = result.structured_data.get(name)
        if isinstance(val, FinancialData):
            return val
    return None


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


def _forward_estimates_provenance(forward: Any) -> dict[str, Any] | None:
    """Slim forward-estimate provenance for the artifact (fiscal year / source /
    confidence). The forward NUMBERS already ride inside valuation_synthesis; this
    is only what the report needs to frozenly label + footnote the forward comps
    row, so it must be the snapshot's provenance, not a later live refetch.

    ``ForwardFinancials`` is a frozen dataclass (no ``model_dump``), so read by
    attribute. Returns ``None`` unless a real forward estimate landed — gated on
    ``fiscal_period`` so the yfinance/unavailable degrade doesn't persist an empty
    provenance block.
    """
    fiscal_period = getattr(forward, "fiscal_period", None)
    if forward is None or fiscal_period is None:
        return None
    return {
        "fiscal_period": str(fiscal_period),
        "source": str(getattr(forward, "source", "") or "") or None,
        "confidence": str(getattr(forward, "confidence", "") or "") or None,
    }


def _numeric_audit_warnings(audit: Any) -> list[str]:
    return [
        f"[NUMERIC-AUDIT/{f.severity}] {f.field_key} ({f.check}): {f.evidence}"
        for f in audit.findings
    ]


def _attach_numeric_audit(
    structured_out: dict[str, Any],
    result: "PipelineResult",
    deps: Any,
    *financial_step_names: str,
    withhold_keys: tuple[str, ...] = (),
    snapshot: Any | None = None,
    rich_withhold: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Attach the numeric audit to a valuation artifact — the single sink every
    builder routes through, so the gate is Mode A/B symmetric and no type can be
    silently left un-audited.

    Snapshot: taken from ``snapshot`` when the builder already holds the
    ``FinancialData`` object (equity_research; ic_memo, whose snapshot is NESTED in
    ``ICFinancials.financial_data`` — never a top-level step, so a step-name lookup
    would silently audit ``None``), else extracted from the named pipeline steps.

    Withhold on ``withhold_valuation``: a ``rich_withhold`` callback runs the
    type-specific degrade (equity_research nulls the thesis TARGET + sets
    valuation_withheld + syncs the llm_narrative mirror — the directional verdict
    is PRESERVED; corrupt data withholds the value, never the judgment); otherwise
    the scalar ``withhold_keys`` are nulled (plain dcf/lbo/ddm). ``comps`` /
    ``ic_memo`` pass neither — the block is still attached for the audit banner +
    output-contract C4 to read, but nothing is auto-withheld.
    """

    from finrobot.engine.compute.operators.audit import audit_artifact

    fin_snapshot = (
        snapshot if snapshot is not None else _extract_financial_data(result, *financial_step_names)
    )
    audit = audit_artifact(fin_snapshot)
    audit_payload = audit.model_dump(mode="json")
    capability_warnings = _data_capability_warnings(deps)
    if capability_warnings:
        audit_payload["artifact_status"] = "caveated"
        audit_payload["data_capability"] = {
            "artifact_status": "caveated",
            "reasons": capability_warnings,
        }
    structured_out["numeric_audit"] = audit_payload
    if audit.withhold_valuation:
        if rich_withhold is not None:
            rich_withhold(structured_out)
        elif withhold_keys:
            structured_out["valuation_withheld"] = True
            structured_out["withheld_reason"] = "numeric_audit_blocked_field"
            for key in withhold_keys:
                if key in structured_out:
                    structured_out[key] = None
    return _numeric_audit_warnings(audit) + capability_warnings


def _report_drift_flag(
    structured_out: dict[str, Any],
    raw_data: dict[str, Any],
    result: "PipelineResult",
    *narrative_steps: str,
) -> list[str]:
    """Plan-B report reconcile — the shared sink for every builder whose pipeline
    has LLM narrative steps, so no artifact type is silently left unscanned
    (same symmetry rule as ``_attach_numeric_audit``).

    Every $-amount an LLM narrative prints should trace to SOME numeric leaf of
    what the artifact freezes (structured snapshot + raw FinancialData — exactly
    the numbers the agent was allowed to assemble). Unmatched amounts are not
    allowed to ship as prose numbers: redact the exact unmatched tokens from the
    scanned narrative steps, then return a warning + structured ``report_drift``
    provenance block. This is deliberately narrower than rewriting to a
    canonical value — there may be no single safe replacement.
    """
    text = "\n\n".join(
        step_text for name in narrative_steps if (step_text := result.steps.get(name))
    )
    if not text:
        return []
    drift = detect_report_drift(
        text,
        collect_numeric_leaves({"structured": structured_out, "raw": raw_data}),
    )
    if not drift.unmatched_count:
        return []
    structured_out["report_drift"] = drift.model_dump(mode="json")
    redacted_tokens = {f.token for f in drift.unmatched}
    for name in narrative_steps:
        text = result.steps.get(name)
        if not text:
            continue
        redacted = text
        for token in redacted_tokens:
            redacted = redacted.replace(token, "[unverified amount redacted]")
        result.steps[name] = redacted
    structured_out["report_drift"]["redacted"] = sorted(redacted_tokens)
    examples = ", ".join(f.token for f in drift.unmatched[:5])
    return [
        f"[REPORT-DRIFT/redacted] {drift.unmatched_count}/{drift.total_dollar_amounts} "
        f"narrative $-amounts matched no computed value and were redacted "
        f"({examples}) — verify the narrative before publishing"
    ]


def _data_capability_warnings(deps: Any) -> list[str]:
    settings = getattr(deps, "settings", None)
    if settings is None or not hasattr(settings, "fmp_api_key"):
        return []
    if getattr(settings, "fmp_api_key", ""):
        return []
    return [
        "[DATA-CAPABILITY/caveat] FMP API key unavailable — financial statements "
        "fall back to non-cross-validated sources; D&A, earnings surprises, and "
        "provider cross-checks may be incomplete. Artifact is data-quality CAVEATED "
        "(the directional verdict still ships; a price target may be withheld)."
    ]


def _summary_text(
    result: "PipelineResult",
    structured_out: dict[str, Any],
    deps: Any,
    *,
    summary_steps: tuple[str, ...] = (),
) -> str:
    # Single source of truth: only claim "withheld" when a target number was
    # ACTUALLY nulled (``valuation_withheld`` set by _attach_numeric_audit or the
    # equity_research block). A blocked-field audit verdict alone is NOT enough —
    # comps/lbo may flag-but-publish, and announcing "withheld" while the numbers
    # still ship in ``structured`` would contradict the published data.
    if structured_out.get("valuation_withheld") is True:
        lang = getattr(getattr(deps, "settings", None), "language", "en")
        if lang == "zh":
            return "估值已被数字审计闸门隐藏；请查看 numeric_audit 与 warnings。"
        return "Valuation withheld by numeric audit; see numeric_audit and warnings."
    # A single-method artifact's summary must be ABOUT that method and stay a
    # SUMMARY: surface the pipeline's deterministic calc-step narrative (e.g.
    # "DDM implies $X per share … cost of equity Y% …") — every number traced to
    # the compute layer, zero drift. ``summary_steps`` is a PRIORITY list (first
    # non-empty wins), NOT a concatenation: we deliberately do NOT normally fall
    # through to the LLM ``*_narrative`` step — it balloons into a full report that
    # RESTATES financial figures (a contract-① drift surface) and editorialises a
    # single-method recommendation. The narrative is only a fallback if the
    # deterministic calc step is somehow empty; ``format_summary`` (the generic
    # "# FinRobot Analysis Report" that concatenates EVERY step — for these
    # pipelines it led with the historical_data table and pushed the model result
    # past the 2k truncation) is the last resort, kept for pipelines that declare
    # no summary_steps (e.g. equity_research).
    for step in summary_steps:
        text = (result.steps.get(step) or "").strip()
        if text:
            return text[:4000]
    return result.format_summary()[:2000]


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
    """The artifact's machine-readable warning haul.

    Delegates to ``PipelineResult.collect_warnings`` (the single source of
    truth) so the artifact and the /runs detail endpoint never drift apart:
    run-level degrades + failed-validation lines + structured-object warnings.
    Per-builder ``audit_warnings``/``drift``/``contract`` lines are appended on
    top at each call site.
    """
    return result.collect_warnings()


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
    structured_out = _safe_dump(dcf)
    audit_warnings = _attach_numeric_audit(
        structured_out,
        result,
        deps,
        "historical_data",
        withhold_keys=("implied_price",),
    )
    audit_warnings += _report_drift_flag(structured_out, raw_data, result, "output_gen")

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
            structured=structured_out,
            summary_text=_summary_text(
                result, structured_out, deps, summary_steps=("dcf_calc", "output_gen")
            ),
            warnings=_collect_warnings(result) + audit_warnings,
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
    structured_out = _safe_dump(lbo_result)
    # LBO returns (IRR/MOIC) are entirely derived from the target's EBITDA, so a
    # dimensionally-corrupt target (blocked_field) makes the headline returns
    # untrustworthy — withhold them like DCF withholds implied_price. The ev/equity
    # breakdown stays visible (with the audit banner) for transparency.
    audit_warnings = _attach_numeric_audit(
        structured_out, result, deps, "data_collection", withhold_keys=("irr", "moic")
    )
    audit_warnings += _report_drift_flag(structured_out, raw_data, result, "lbo_narrative")

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
            structured=structured_out,
            summary_text=_summary_text(
                result, structured_out, deps, summary_steps=("lbo_calculation", "lbo_narrative")
            ),
            warnings=_collect_warnings(result) + audit_warnings,
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
    from finrobot.engine.primitives.industry import is_balance_sheet_financial

    data_source, fetched_at, raw_data = _extract_financial_data_dump(result, "target_data")
    peer_comps = result.structured_data.get("statistical_bench")

    # Collect peer tickers for cross_tickers field
    cross_tickers: list[str] = []
    if isinstance(peer_comps, PeerComps):
        cross_tickers = [p.ticker for p in peer_comps.peers]
    structured_out = _safe_dump(peer_comps)
    # Financial-sector issuers (banks / insurers) have no clean above-the-line
    # EBITDA, so a peer EV/EBITDA median is a category error — the full report
    # suppresses it (is_balance_sheet_financial is the single authority; P/B is the
    # bank/insurer lead multiple). FMP still reports a mechanical positive EBITDA for
    # banks, so the median is non-None and would otherwise headline a meaningless
    # multiple on the standalone comps page. Null it here to mirror the report; the
    # P/E and P/B medians (the relative methods that DO apply) stay visible.
    target_fin = _extract_financial_data(result, "target_data")
    if target_fin is not None and is_balance_sheet_financial(
        industry=target_fin.market.industry, sector=target_fin.market.sector
    ):
        structured_out["median_ev_ebitda"] = None
        structured_out["mean_ev_ebitda"] = None
    audit_warnings = _attach_numeric_audit(structured_out, result, deps, "target_data")
    audit_warnings += _report_drift_flag(structured_out, raw_data, result, "output_gen")

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
            structured=structured_out,
            summary_text=_summary_text(
                result, structured_out, deps, summary_steps=("statistical_bench", "output_gen")
            ),
            warnings=_collect_warnings(result) + audit_warnings,
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
    structured_out = _safe_dump(ddm_result) if isinstance(ddm_result, DDMResult) else {}
    audit_warnings = _attach_numeric_audit(
        structured_out,
        result,
        deps,
        "historical_data",
        withhold_keys=("equity_value_per_share",),
    )
    audit_warnings += _report_drift_flag(structured_out, raw_data, result, "ddm_narrative")

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
            structured=structured_out,
            summary_text=_summary_text(
                result, structured_out, deps, summary_steps=("ddm_calc", "ddm_narrative")
            ),
            warnings=_collect_warnings(result) + audit_warnings,
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

    # Two LLM free-text narrative steps (earnings_analysis / forward_outlook)
    # feed this artifact — it was the ONE builder outside the shared drift
    # sink, directly contradicting the sink's "no artifact type is silently
    # left unscanned" symmetry rule.
    structured_out = _safe_dump(earnings)
    drift_warnings = _report_drift_flag(
        structured_out, raw_data, result, "earnings_analysis", "forward_outlook"
    )

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
            structured=structured_out,
            summary_text=result.format_summary()[:2000],
            warnings=_collect_warnings(result) + drift_warnings,
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
        # Scenario SOTP (Batch 3B v1): the reverse-SOTP market-implied
        # decomposition for option-value names. An INDEPENDENT channel — it is NOT
        # a method in valuation_synthesis (kept out of point synthesis so it never
        # trips the method-corroboration span gate METHOD_CORROBORATION_SPAN_K), so
        # it must persist on its own key for the valuation chapter to render the
        # floor / implied-option-premium panel.
        "sotp_breakdown",
        "thesis",
        "catalyst_analysis",
        "technical_analysis",
        # Multi-year HistoricalMetrics (revenue/margin/cash-flow/EPS trends). The
        # pipeline already builds it (execute_financial_data_step); persisting it
        # here freezes the financial-trend charts into the artifact so the report
        # chapter reads them from the snapshot instead of a live ['historical']
        # refetch — a structural quantity the narrative's growth/trend claims are
        # computed from, so an export-window restatement / new fiscal year would
        # otherwise let the chart endpoints contradict the frozen prose.
        "historical_metrics",
    ):
        val = result.structured_data.get(key)
        if val is not None:
            structured_out[key] = _safe_dump(val)
    ownership = result.structured_data.get("ownership_governance_analysis")
    if ownership is not None:
        structured_out["ownership_governance"] = _safe_dump(ownership)

    # Forward-estimate provenance (FY1 consensus the comps-forward path used).
    # The numbers themselves already ride inside valuation_synthesis.methods; we
    # persist ONLY the provenance — which fiscal year, what source, how confident
    # — so the report can frozenly label the forward comps row ("FY2026E") and
    # footnote its source WITHOUT a live /api/valuation/aggregate refetch.
    forward_estimates = _forward_estimates_provenance(
        result.structured_data.get("forward_financials")
    )
    if forward_estimates is not None:
        structured_out["forward_estimates"] = forward_estimates

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

    # Numeric-audit gate (design doc §7, behavior A) — runs through the shared
    # sink so every report mode is Mode A/B symmetric and ic_memo gets the same
    # gate (it was the one builder this never ran on). equity_research's withhold
    # is richer than a scalar null — it must null the thesis TARGET while KEEPING
    # the directional verdict (corrupt data withholds the VALUE, never the
    # judgment — 绝不编数字 cuts both ways: don't fabricate a number on bad data,
    # but don't refuse to judge either) — so it passes a rich_withhold callback.
    fin_snapshot = next(
        (v for v in result.structured_data.values() if isinstance(v, FinancialData)),
        None,
    )

    def _withhold_equity_research(structured: dict[str, Any]) -> None:
        # Value-integrity guardrail: the target is built on a number the audit
        # flagged corrupt/uncross-validated, so the POINT TARGET is withheld
        # (绝不编数字). The directional recommendation is PRESERVED — it reads from
        # the market-implied direction, not the corrupt figure. No "REVIEW" verdict.
        structured["valuation_withheld"] = True
        structured["withheld_reason"] = "numeric_audit_blocked_field"
        thesis_out = structured.get("thesis")
        if isinstance(thesis_out, dict):
            thesis_out["price_target"] = None

    audit_warnings = _attach_numeric_audit(
        structured_out,
        result,
        deps,
        snapshot=fin_snapshot,
        rich_withhold=_withhold_equity_research,
    )

    # Top-level ``valuation_withheld`` is the single "point target withheld" signal,
    # and it must be cause-INDEPENDENT. _attach_numeric_audit sets it for the
    # data-corruption path (JPM: blocked EV field), but the synthesis dial withholds
    # the point on its OWN terms too — single-method out-of-calibration / method
    # divergence (RIVN) — which nulls thesis.price_target via resolve_canonical_thesis
    # yet left the top-level flag at None. Same withheld state, two values depending
    # on cause. Mirror the synthesis flag so every withhold path agrees (the contract
    # judge _is_withheld and _summary_text both read this).
    vs_struct = structured_out.get("valuation_synthesis")
    if (
        isinstance(vs_struct, dict)
        and vs_struct.get("valuation_withheld") is True
        and structured_out.get("valuation_withheld") is not True
    ):
        structured_out["valuation_withheld"] = True
        structured_out.setdefault("withheld_reason", "valuation_synthesis_dial")

    # data_collection is ALSO an LLM free-text narrative (the data agent's
    # prose summary) and format_summary() puts it FIRST — the artifact's
    # summary_text opened with the one narrative the drift scan skipped.
    audit_warnings += _report_drift_flag(
        structured_out, raw_data, result, "report", "data_collection"
    )

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
            summary_text=_summary_text(result, structured_out, deps),
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
    audit_warnings: list[str] = []
    if isinstance(ic, ICFinancials):
        structured_out = {
            "dcf_result": _safe_dump(ic.dcf_result),
            "lbo_result": _safe_dump(ic.lbo_result),
        }
        # Close the ic_memo gap: its FinancialData snapshot is NESTED in
        # ICFinancials.financial_data (not a top-level step), so feed it
        # explicitly. ic_memo has no single per-share headline to withhold → the
        # block is attached (for the audit banner + contract C4) without an
        # auto-withhold. Mode A/B symmetric, same sink as every other type.
        audit_warnings = _attach_numeric_audit(
            structured_out, result, deps, snapshot=ic.financial_data
        )
    audit_warnings += _report_drift_flag(
        structured_out,
        raw_data,
        result,
        "situation_overview",
        "investment_thesis",
        "risk_factors",
        "recommendation",
    )

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
            warnings=_collect_warnings(result) + audit_warnings,
        ),
        meta=ArtifactMeta(
            created_at=_now(),
            source="pipeline:ic_memo",
        ),
    )
