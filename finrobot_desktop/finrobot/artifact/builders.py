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
import re
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
from finrobot.engine.models.reconcile_tolerances import (
    NARRATIVE_APPROXIMATION_BAND,
    NARRATIVE_DRIFT_TOLERANCE,
)

logger = logging.getLogger(__name__)


# Labeled current-price / market-cap restatements in the data-collection
# "Financial Data Summary" table (the block an equity_research summary_text opens
# with). Anchored on the label so an unrelated prose $-amount is never mistaken
# for the current-price claim.
_MAGNITUDE: dict[str, float] = {
    "TRILLION": 1e12,
    "T": 1e12,
    "BILLION": 1e9,
    "B": 1e9,
    "MILLION": 1e6,
    "M": 1e6,
    "THOUSAND": 1e3,
    "K": 1e3,
}
# Gap between the label and the "$" is only spaces / tabs / table pipes (never a
# newline, so the match stays on the label's own row and never leaps to a "$" on
# another line).
_LABELED_PRICE_RE = re.compile(r"Current Price[ \t|]*\$\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_LABELED_MCAP_RE = re.compile(
    r"Market Cap(?:italization)?[ \t|]*\$\s*([\d,]+(?:\.\d+)?)"
    r"\s*(Trillion|Billion|Million|Thousand|[TBMK])?",
    re.IGNORECASE,
)


def _labeled_price(text: str) -> float | None:
    match = _LABELED_PRICE_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _labeled_market_cap(text: str) -> float | None:
    match = _LABELED_MCAP_RE.search(text)
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value * _MAGNITUDE.get((match.group(2) or "").upper(), 1.0)


def _assert_price_snapshot_coherent(
    ticker: str,
    summary_text: str,
    raw_data: dict[str, Any],
    structured_out: dict[str, Any],
) -> None:
    """Build-time identity gate: every price / market-cap the artifact surfaces
    must ride ONE as-of.

    The FINANCIALS and PRICE canonicals have independent TTLs, so a snapshot can
    carry a headline price from one session while a summary / derived field trails
    a session behind (AAPL 2026-07-02: summary_text $287.98 / $4.230T vs market
    block $294.38 / $4.324T). ``extract_financial_data`` marks the market block to
    the live PRICE and ``financials_with_display_price`` keeps the LLM narrative on
    the same basis; this is the tripwire that FAILS THE BUILD if a future
    regression reintroduces the split — a contradictory current price is a
    fabrication surface (绝不编数字), never shipped. Tolerance is the tight "same
    number" ``NARRATIVE_DRIFT_TOLERANCE``, not the loose 10% approximation band
    (which read the full-session-stale price as a rounding and let it ship).
    """
    market = raw_data.get("market")
    if not isinstance(market, dict):
        return
    canon_price = market.get("current_price")
    canon_mcap = market.get("market_cap")

    def _diverges(claimed: float | None, canonical: float | None) -> bool:
        return (
            isinstance(claimed, (int, float))
            and isinstance(canonical, (int, float))
            and claimed > 0
            and canonical > 0
            and abs(claimed - canonical) > abs(canonical) * NARRATIVE_DRIFT_TOLERANCE
        )

    violations: list[str] = []

    # Deterministic cross-field identity: valuation_synthesis.current_price and the
    # comps target market_cap / P-E are code-computed off the SAME market block, so
    # any divergence is a definite pipeline desync, not LLM variance.
    vs = structured_out.get("valuation_synthesis")
    if isinstance(vs, dict) and _diverges(vs.get("current_price"), canon_price):
        violations.append(
            f"valuation_synthesis.current_price {vs.get('current_price')} vs "
            f"market.current_price {canon_price}"
        )
    # The comps target market_cap is the same underlying cap, USD-normalized by the
    # same FX as the market block (no-op for a US issuer / a USD-quoted ADR), so it
    # must match. P/E is deliberately NOT checked: the target row carries a
    # separately-computed multiple (core vs provider-reported) that can legitimately
    # differ from the marked market-block ratio.
    peer = structured_out.get("peer_analysis")
    target = peer.get("target") if isinstance(peer, dict) else None
    if isinstance(target, dict) and _diverges(target.get("market_cap"), canon_mcap):
        violations.append(
            f"peer target.market_cap {target.get('market_cap')} vs market.market_cap {canon_mcap}"
        )

    # Narrative identity: the data-collection table restates the snapshot verbatim,
    # so its labeled Current Price / Market Cap must match the frozen market block.
    if _diverges(_labeled_price(summary_text), canon_price):
        violations.append(
            f"summary_text Current Price {_labeled_price(summary_text)} vs "
            f"market.current_price {canon_price}"
        )
    if _diverges(_labeled_market_cap(summary_text), canon_mcap):
        violations.append(
            f"summary_text Market Cap {_labeled_market_cap(summary_text)} vs "
            f"market.market_cap {canon_mcap}"
        )

    if violations:
        raise ValueError(
            f"price snapshot as-of split in {ticker} equity_research artifact "
            f"(one artifact must carry one price as-of): " + "; ".join(violations)
        )


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
    the numbers the agent was allowed to assemble). Unmatched amounts split by
    distance to the nearest leaf (see ``report_drift`` module docstring):
    APPROXIMATIONS (within the band of some real leaf — "roughly $400B" against
    $391B) stay in prose and are surfaced for review; ORPHANS (near nothing the
    artifact computed) are redacted from the scanned narrative steps. Both
    outcomes land in the structured ``report_drift`` provenance block. Never a
    rewrite-to-canonical — there is no single safe replacement.
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
    warnings: list[str] = []
    if drift.orphan_tokens:
        for name in narrative_steps:
            step_text = result.steps.get(name)
            if not step_text:
                continue
            redacted = step_text
            for token in drift.orphan_tokens:
                redacted = redacted.replace(token, "[unverified amount redacted]")
            result.steps[name] = redacted
        examples = ", ".join(drift.orphan_tokens[:5])
        warnings.append(
            f"[REPORT-DRIFT/redacted] {drift.orphan_count}/{drift.total_dollar_amounts} "
            f"narrative $-amounts matched nothing the artifact computed and were "
            f"redacted ({examples}) — verify the narrative before publishing"
        )
    structured_out["report_drift"]["redacted"] = sorted(drift.orphan_tokens)
    if drift.approximate_count:
        approx_examples = ", ".join(
            f.token
            for f in drift.unmatched
            if f.nearest_gap is not None and f.nearest_gap <= NARRATIVE_APPROXIMATION_BAND
        )
        warnings.append(
            f"[REPORT-DRIFT/review] {drift.approximate_count}/{drift.total_dollar_amounts} "
            f"narrative $-amounts are approximations of computed values (within "
            f"{NARRATIVE_APPROXIMATION_BAND:.0%}) and were kept ({approx_examples}) "
            f"— verify the rounding language before publishing"
        )
    return warnings


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


def _withhold_summary_note(structured_out: dict[str, Any], lang: str) -> str:
    """One correctly-ATTRIBUTED sentence for a withheld/fairly-valued summary.

    Attribution must reflect the REAL cause, never a hardcoded "numeric audit" (the
    dial withholds on its own terms — a lone method too far from market, method
    divergence, or price inside the fair-value band = fairly valued, not "withheld").
    The thesis ``price_target_basis`` is the single authority (06-24: it leads with
    "FAIRLY VALUED" for an in-band price, "POINT TARGET WITHHELD" otherwise), so a
    fairly-valued price reads as fairly valued; only ``numeric_audit_blocked_field``
    keeps the "numeric audit" wording."""
    thesis = structured_out.get("thesis")
    basis = str((thesis or {}).get("price_target_basis") or "") if isinstance(thesis, dict) else ""
    reason = structured_out.get("withheld_reason")
    if basis.upper().startswith("FAIRLY VALUED"):
        if lang == "zh":
            return "估值合理：现价落在公允价值区间内,故不钉单一目标价;方向性裁决与区间照常给出。"
        return (
            "Fairly valued — price sits within the fair-value range, so no single point "
            "target is stamped; the directional verdict and range still ship."
        )
    if reason == "numeric_audit_blocked_field":
        if lang == "zh":
            return "估值已被数字审计闸门隐藏;请查看 numeric_audit 与 warnings。"
        return "Valuation withheld by numeric audit; see numeric_audit and warnings."
    if isinstance(reason, str) and reason.startswith("contract_"):
        gate = reason.replace("contract_", "contract ", 1)
        if lang == "zh":
            return f"点目标价已由 {gate} 估值闸门撤回;方向性裁决与区间照常给出。"
        return (
            f"Point target withheld by the {gate} valuation gate; the directional verdict "
            "and range still ship."
        )
    # Synthesis dial (single lone method far from market / method divergence) and any
    # other reason: attribute to the synthesis, never to the audit.
    if lang == "zh":
        return "点目标价已由估值合成撤回(单一方法远离市价或方法间背离);方向性裁决与区间照常给出。"
    return (
        "Point target withheld by the valuation synthesis (a single method too far from "
        "market, or method divergence); the directional verdict and range still ship."
    )


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
        note = _withhold_summary_note(structured_out, lang)
        # A single-method artifact (summary_steps present) SUPPRESSES its calc line —
        # it carries the withheld point number ("DDM implies $X") — so the note stands
        # alone. Multi-method equity_research declares no summary_steps: keep its full
        # data-collection summary (parity with a published bank like BAC) and PREFIX
        # the attributed note, instead of collapsing to a bare stub that also
        # misattributed the cause.
        if summary_steps:
            return note
        base = result.format_summary()[:2000]
        return f"{note}\n\n{base}" if base else note
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


def _fmt_usd_humanized(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.2f}T"
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def _fmt_multiple_x(value: Any) -> str:
    try:
        return f"{float(value):.1f}x"
    except (TypeError, ValueError):
        return "n/a"


def _fill_narrative_fallbacks(
    structured_out: dict[str, Any], raw_data: dict[str, Any], ticker: str
) -> list[str]:
    """Fill any narrative field the LLM left NULL with a DETERMINISTIC summary built
    from the frozen structured data — so a report never publishes empty sections.

    The synthesis LLM's optional prose fields (tagline / company_overview /
    valuation_overview / competitor_analysis / news_summary / key_takeaways) come back
    None intermittently under structured-output pressure (TSM 2026-07-02: 5/9 sections
    NULL in one run, all present in the next). Rather than render blank sections (or
    fabricate prose), we assemble a traceable one-liner per missing field from the
    numbers the artifact already froze (peer medians, the deterministic valuation
    basis, catalyst sentiment, company facts) and flag which fields were filled. Every
    value is sourced from ``structured_out`` / ``raw_data`` — no model-authored text,
    no invented numbers. Mutates ``structured_out['thesis']`` in place; returns the
    provenance warning line(s)."""
    thesis = structured_out.get("thesis")
    if not isinstance(thesis, dict):
        return []
    vs = structured_out.get("valuation_synthesis")
    vs = vs if isinstance(vs, dict) else {}
    pa = structured_out.get("peer_analysis")
    pa = pa if isinstance(pa, dict) else {}
    ca = structured_out.get("catalyst_analysis")
    ca = ca if isinstance(ca, dict) else {}
    market = raw_data.get("market") if isinstance(raw_data, dict) else None
    market = market if isinstance(market, dict) else {}
    income = raw_data.get("income") if isinstance(raw_data, dict) else None
    income = income if isinstance(income, dict) else {}
    company = (raw_data.get("company_name") if isinstance(raw_data, dict) else None) or ticker
    verdict = str(thesis.get("recommendation") or "HOLD")
    confidence = str(vs.get("confidence") or "medium")

    def _need(key: str) -> bool:
        return thesis.get(key) in (None, "", [])

    filled: list[str] = []

    if _need("tagline"):
        thesis["tagline"] = (
            f"{ticker}: {verdict} rating ({confidence} confidence) on the deterministic "
            "valuation synthesis."
        )[:120]
        filled.append("tagline")

    if _need("company_overview"):
        industry = market.get("industry")
        sector = market.get("sector")
        loc = f"the {industry} industry" if industry else "its industry"
        if sector:
            loc += f" within the {sector} sector"
        parts = [f"{company} ({ticker}) operates in {loc}."]
        if income.get("revenue"):
            parts.append(
                f"Trailing-twelve-month revenue is approximately {_fmt_usd_humanized(income['revenue'])}."
            )
        if market.get("market_cap"):
            parts.append(
                f"Market capitalization is approximately {_fmt_usd_humanized(market['market_cap'])}."
            )
        # Segment revenue mix (BACKLOG A4, 2026-07-09): cite the largest reported
        # segments from the frozen segment_overview when it landed (SEC XBRL, or
        # FMP's product mix when XBRL had nothing); otherwise the honest
        # "unavailable" line — never a fabricated proportion either way.
        segment_overview = structured_out.get("segment_overview")
        segment_overview = segment_overview if isinstance(segment_overview, dict) else {}
        seg_rows = segment_overview.get("segments")
        seg_rows = seg_rows if isinstance(seg_rows, list) else []
        ranked_segments = sorted(
            (
                s
                for s in seg_rows
                if isinstance(s, dict) and isinstance(s.get("revenue_share"), (int, float))
            ),
            key=lambda s: s["revenue_share"],
            reverse=True,
        )[:2]
        if ranked_segments:
            seg_desc = "; ".join(
                f"{s.get('name') or 'segment'} ({s['revenue_share']:.0%} of segment revenue)"
                for s in ranked_segments
            )
            parts.append(f"The largest reported segments are {seg_desc}.")
        else:
            parts.append(
                "Segment revenue breakdown was not available for this issuer; "
                "see the latest annual report for business-line detail."
            )
        thesis["company_overview"] = " ".join(parts)
        filled.append("company_overview")

    if _need("valuation_overview"):
        # The deterministic price_target_basis IS the traceable valuation explanation
        # (lists the real methods + reasoning) — the ideal fallback.
        basis = str(thesis.get("price_target_basis") or "").strip()
        thesis["valuation_overview"] = basis or (
            "Valuation rests on the deterministic synthesis of the methods shown in the "
            "valuation section."
        )
        filled.append("valuation_overview")

    if _need("competitor_analysis"):
        peers = [
            str(p["ticker"])
            for p in (pa.get("peers") or [])
            if isinstance(p, dict) and p.get("ticker")
        ]
        if peers:
            thesis["competitor_analysis"] = (
                f"Peer set: {', '.join(peers[:8])}. Peer-median P/E "
                f"{_fmt_multiple_x(pa.get('median_pe'))}, peer-median EV/EBITDA "
                f"{_fmt_multiple_x(pa.get('median_ev_ebitda'))}. These are peer-set medians, "
                f"not {ticker}'s own trading multiples."
            )
        else:
            thesis["competitor_analysis"] = (
                f"A comparable peer set was not available for {ticker}; relative-multiple "
                "positioning is therefore not shown."
            )
        filled.append("competitor_analysis")

    if _need("news_summary"):
        sent = ca.get("overall_sentiment")
        net = ca.get("net_sentiment")
        if sent is not None and isinstance(net, (int, float)):
            thesis["news_summary"] = (
                f"Recent news sentiment is {sent} (net sentiment {net:+.2f}), from the "
                "catalyst analysis; see the catalysts and risks sections for the specific events."
            )
        else:
            thesis["news_summary"] = (
                "No material recent-news signal was available; see the catalysts and risks sections."
            )
        filled.append("news_summary")

    if _need("key_takeaways"):
        takeaways = [f"Rating: {verdict} ({confidence} confidence)."]
        target = thesis.get("price_target")
        if isinstance(target, (int, float)):
            takeaways.append(f"Deterministic price target: {_fmt_usd_humanized(target)} per share.")
        else:
            takeaways.append(
                "Point target withheld; the directional verdict and fair-value range still ship."
            )
        if pa.get("median_pe") is not None:
            takeaways.append(f"Peer-median P/E {_fmt_multiple_x(pa.get('median_pe'))}.")
        if isinstance(ca.get("net_sentiment"), (int, float)):
            takeaways.append(f"Net catalyst sentiment {ca['net_sentiment']:+.2f}.")
        thesis["key_takeaways"] = takeaways
        filled.append("key_takeaways")

    if filled:
        # Reader-facing disclosure (ships in the report's warnings section) —
        # plain language, no bracketed engineering tag (external audit
        # 2026-07-07 read "[NARRATIVE-FALLBACK]" as an internal marker leak).
        return [
            f"Narrative note: {', '.join(filled)} were assembled directly from the "
            "report's own computed figures rather than written by the model — every "
            "statement traces to the structured data."
        ]
    return []


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
        # Lightweight non-SOTP segment/business-line revenue mix (BACKLOG A4,
        # 2026-07-09): display-only, populated for tickers the SOTP gate above
        # did NOT fire for. Independent key — never merged into sotp_breakdown
        # (different calibers: one is a reverse-decomposition valuation, this is
        # a sourced revenue-mix table) so the Company Overview chapter can render
        # its segment table without touching the Valuation chapter's SOTP panel.
        "segment_overview",
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

    # Freeze the day-over-day session change the data agent narrated (sourced from the
    # PRICE canonical in execute_financial_data_step). The amount = last_close −
    # prev_close is a real computed number the analyst sees ("Latest Session Change:
    # -$3.75") but is NOT reconstructable from any other frozen field — not price × a
    # stored ratio — so without freezing it the report-drift leaf registry had no match
    # and redacted it as an orphan (MSFT 2026-07-07). Freezing makes it a natural leaf
    # (picked up by collect_numeric_leaves below) AND a traceable artifact field.
    # Absent (<2 price bars → no session to diff) → not frozen, prior behavior.
    price_session = result.structured_data.get("price_session")
    if isinstance(price_session, dict):
        structured_out["price_session"] = price_session

    # Deterministic narrative fallback: fill any prose field the LLM left NULL from the
    # frozen structured data BEFORE mirroring, so no section renders empty and the
    # mirror below carries the filled values. Provenance flagged in the warnings.
    narrative_fallback_warnings = _fill_narrative_fallbacks(structured_out, raw_data, ticker)

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

    summary_text = _summary_text(result, structured_out, deps)
    # Single-as-of gate: the summary narrative, the frozen market block, and every
    # code-derived price/market-cap must agree (绝不编数字 — never ship two prices
    # for one artifact). Fails the build on a regression that reintroduces the
    # canonical-split leak (AAPL 2026-07-02).
    _assert_price_snapshot_coherent(ticker.upper(), summary_text, raw_data, structured_out)

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
            summary_text=summary_text,
            warnings=_collect_warnings(result) + audit_warnings + narrative_fallback_warnings,
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
