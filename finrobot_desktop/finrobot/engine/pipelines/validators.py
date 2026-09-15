import logging
import math as _math
import re
from statistics import median as _median

from pydantic import BaseModel

from finrobot.engine.compute.operators.multiples import (
    PEER_EV_EBITDA_SANITY_MAX,
    PEER_EV_EBITDA_SANITY_MIN,
    PEER_EV_REVENUE_SANITY_MAX,
    PEER_EV_REVENUE_SANITY_MIN,
    PEER_PE_SANITY_MAX,
    PEER_PE_SANITY_MIN,
)
from finrobot.engine.models.financial import (
    CatalystAnalysis,
    DDMInputs,
    DDMResult,
    FinancialData,
    LBOInputs,
    LBOResult,
    PeerComps,
    DCFResult,
    ThesisResult,
)

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    passed: bool
    error: str | None = None


def validate_is_non_empty(output: str) -> ValidationResult:
    """P0 validator. Passes if output is a non-empty, non-whitespace string."""
    if output and output.strip():
        return ValidationResult(passed=True)
    return ValidationResult(passed=False, error="Output is empty or whitespace")


def validate_technical_analysis(output: object) -> ValidationResult:
    """Technical-analysis step validator.

    The payload itself is always returned (with partial None branches when
    individual computes fail), so we only fail when none of the three
    branches produced anything — that means the artifact would have a
    chapter-09 placeholder forever.

    Exception: when the upstream DCF degraded gracefully (no DCFResult to seed
    the overlays), the step emits an all-None payload carrying
    ``TECHNICAL_DCF_UNAVAILABLE_MARKER``. That is an honest, expected degrade —
    we PASS so the run continues to a relative-valuation report instead of
    re-triggering a non-critical degrade and stamping a misleading green check.
    """
    from finrobot.engine.compute.coordinators.technical_payload import (
        TECHNICAL_DCF_UNAVAILABLE_MARKER,
        TechnicalAnalysis,
    )

    if not isinstance(output, TechnicalAnalysis):
        return ValidationResult(
            passed=False,
            error=f"technical_analysis output must be TechnicalAnalysis, got {type(output).__name__}",
        )
    if TECHNICAL_DCF_UNAVAILABLE_MARKER in output.warnings:
        return ValidationResult(passed=True)
    if output.monte_carlo is None and output.sniper is None and output.historical_bands is None:
        joined = "; ".join(output.warnings) or "no diagnostics"
        return ValidationResult(
            passed=False,
            error=f"all technical-analysis branches failed: {joined}",
        )
    return ValidationResult(passed=True)


def validate_ownership_governance(output: object) -> ValidationResult:
    """Ownership & Governance validator for SEC-backed structured output."""
    from finrobot.engine.models.sec import OwnershipGovernanceAnalysis

    if not isinstance(output, OwnershipGovernanceAnalysis):
        return ValidationResult(
            passed=False,
            error=(
                "ownership_governance_analysis output must be "
                f"OwnershipGovernanceAnalysis, got {type(output).__name__}"
            ),
        )
    populated = (
        bool(output.insider_transactions)
        or bool(output.institutional_holdings)
        or output.proxy_compensation is not None
        or bool(output.schedule13_alerts)
    )
    if populated or output.degraded_sections:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error="ownership_governance_analysis produced no data and no degraded sections",
    )


def validate_has_fields(output: str, fields: list[str]) -> ValidationResult:
    """P0 validator. Checks that output string mentions all required field names."""
    normalized = output.lower()
    missing = [f for f in fields if f.replace("_", " ").lower() not in normalized]
    if not missing:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Output missing required fields: {', '.join(missing)}",
    )


# Non-ticker acronyms to exclude from peer detection
_NON_TICKER_ACRONYMS = {
    "WACC",
    "DCF",
    "EBITDA",
    "GAAP",
    "IFRS",
    "FCF",
    "ROIC",
    "ROE",
    "ROA",
    "EPS",
    "YOY",
    "QOQ",
    "CAGR",
    "IPO",
    "LBO",
    "SEC",
    "GDP",
    "CPI",
    "FED",
    "NYSE",
    "ETF",
    "CEO",
    "CFO",
    "COO",
    "BUY",
    "SELL",
    "HOLD",
    "NOTE",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CNY",
}


_TICKER_REGEX = re.compile(r"\b([A-Z]{2,5})\b")


def _extract_ticker_candidates(output: str) -> set[str]:
    """Return 2–5 letter uppercase tokens from output, minus known non-ticker acronyms."""
    return set(_TICKER_REGEX.findall(output)) - _NON_TICKER_ACRONYMS


def validate_has_peers(output: str, min_peers: int = 3) -> ValidationResult:
    """Strict validator for peer analysis step.
    Checks that output mentions at least `min_peers` distinct company names/tickers."""
    tickers = _extract_ticker_candidates(output)
    if len(tickers) >= min_peers:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least {min_peers} peer tickers, found {len(tickers)}: {tickers}",
    )


# Keyword-based text validators: a step's free-text output must mention the
# expected concepts before it can pass. Used by equity_research's text steps.
def validate_has_thesis(output: str) -> ValidationResult:
    """Strict validator for thesis construction step.
    Checks that output contains investment thesis structure.
    Must find at least 2 of the thesis indicators."""
    lower = output.lower()
    indicators = [
        any(
            kw in lower for kw in ["buy", "hold", "sell", "overweight", "underweight", "outperform"]
        ),
        any(kw in lower for kw in ["catalyst", "upside", "driver", "tailwind"]),
        any(kw in lower for kw in ["risk", "downside", "headwind", "threat"]),
        any(kw in lower for kw in ["price target", "target price", "implied value"]),
    ]
    found = sum(indicators)
    if found >= 2:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 2 thesis indicators, found {found}",
    )


# Below this the assembled report is structurally broken — empty, errored, or
# truncated to a stub. A re-prompt may recover it, so this DOES fail/retry.
_REPORT_MIN_CHARS = 200
# A healthy assembled report clears this. Falling short is almost always thin
# UPSTREAM content: the report agent only reformats already-produced numbers and
# narrative (it is forbidden from adding analysis — see report_agent.md), so
# re-prompting the formatter cannot manufacture missing content. We warn but
# PASS — retrying would just burn the pipeline's most expensive call for no
# chance of a different result, and the step uses its best-effort output anyway.
_REPORT_SOFT_TARGET_CHARS = 1200


def validate_report_format(output: str) -> ValidationResult:
    """Language-agnostic structural validator for the final report step.

    The report step only assembles already-computed numbers and already-written
    narrative into Markdown. A failure therefore means the ASSEMBLY is
    structurally broken (empty / no headers / no data / truncated stub) — the one
    class of problem a re-prompt might fix. The previous implementation gated on
    ``str.split()`` word count and an English-only section-keyword list, both of
    which systematically false-failed Chinese reports (CJK has no spaces, so
    split() under-counts ~10x; Chinese headers contain no English keywords) —
    every zh report retried 3x and degraded regardless of quality.
    """
    text = output.strip() if output else ""

    # Structural: empty / errored / truncated to a stub.
    if len(text) < _REPORT_MIN_CHARS:
        return ValidationResult(
            passed=False,
            error=f"Report too short to be a valid assembly: {len(text)} chars "
            f"(min {_REPORT_MIN_CHARS})",
        )

    # Structural: a report must be sectioned. Counts Markdown header SYNTAX, not
    # words — language-agnostic.
    headers = re.findall(r"^#{1,3}\s+\S", output, re.MULTILINE)
    if len(headers) < 3:
        return ValidationResult(
            passed=False, error=f"Expected at least 3 section headers, found {len(headers)}"
        )

    # Substance: a financial report must contain numbers (prices, multiples,
    # dates, growth rates). Catches prose-only boilerplate. Replaces the old
    # English section-keyword check with a language-agnostic signal.
    if not re.search(r"\d", output):
        return ValidationResult(passed=False, error="Report contains no numeric data")

    # Soft signal: structurally sound but thin. Almost always thin upstream
    # content — re-prompting the formatter won't help, so warn, don't fail.
    if len(text) < _REPORT_SOFT_TARGET_CHARS:
        logger.warning(
            "Report assembled but shorter than expected (%d chars < %d soft target) — "
            "likely thin upstream content, not a formatting fault; passing without retry.",
            len(text),
            _REPORT_SOFT_TARGET_CHARS,
        )

    return ValidationResult(passed=True)


def validate_has_comps_table(output: str) -> ValidationResult:
    """Strict validator for comps pipeline output.
    Checks for multiples table structure."""
    tickers = _extract_ticker_candidates(output)
    if len(tickers) < 3:
        return ValidationResult(
            passed=False,
            error=f"Expected at least 3 company tickers, found {len(tickers)}: {tickers}",
        )

    # At least 2 multiples keywords
    lower = output.lower()
    multiples_kws = ["ev/ebitda", "p/e", "ev/revenue", "multiple"]
    multiples_found = sum(1 for kw in multiples_kws if kw in lower)
    if multiples_found < 2:
        return ValidationResult(
            passed=False,
            error=f"Expected at least 2 multiples keywords, found {multiples_found}",
        )

    # Statistical terms
    stats_kws = ["median", "mean", "average"]
    if not any(kw in lower for kw in stats_kws):
        return ValidationResult(
            passed=False, error="Missing statistical terms (median/mean/average)"
        )

    return ValidationResult(passed=True)


def validate_dcf_output(output: str) -> ValidationResult:
    """Strict validator for DCF pipeline output.
    Checks for DCF model components. Must find at least 3."""
    lower = output.lower()
    indicators = [
        any(kw in lower for kw in ["wacc", "discount rate", "cost of capital"]),
        any(kw in lower for kw in ["terminal value", "terminal growth"]),
        any(kw in lower for kw in ["free cash flow", "fcf"]),
        any(kw in lower for kw in ["sensitivity", "scenario"]),
        any(
            kw in lower
            for kw in [
                "implied price",
                "implied value",
                "valuation range",
                "fair value",
                "price target",
            ]
        ),
    ]
    found = sum(indicators)
    if found >= 3:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 3 DCF components, found {found}",
    )


_VALID_RECOMMENDATIONS = {
    "BUY",
    "HOLD",
    "SELL",
    "OVERWEIGHT",
    "UNDERWEIGHT",
    "OUTPERFORM",
    "UNDERPERFORM",
}
"""Canonical investment-bank recommendations (uppercase per CLAUDE.md spec).

`validate_thesis` normalizes incoming values via ``.upper()`` so historical
artifacts using mixed case (`Buy`/`Hold`/`Sell`) still validate.
"""


# Peer multiple sanity ranges are owned by the compute layer
# (``finrobot.engine.compute.operators.multiples``): calculate_multiples NULLS any
# out-of-band multiple AND records the drop on ``CompanyFinancials.sanity_drops``.
# validate_peer_comps imports the same constants for a standalone defense-in-depth
# re-check (it catches peers built WITHOUT that gating — externally/LLM-supplied or
# hand-constructed rows), and additionally surfaces the recorded floor drops as
# non-fatal warnings so a silently thinned median is no longer invisible.


def validate_financial_data(
    data: FinancialData,
    ebitda_margin_range: tuple[float, float] = (-5.0, 0.9),
) -> ValidationResult:
    """Validate extracted financial data is reasonable.

    Args:
        ebitda_margin_range: (min, max) for EBITDA/revenue ratio.
            Default (-500%, 90%) covers pre-revenue biotech through high-margin software.
            Tighten for specific industry analysis if needed.
    """
    if data.income.revenue <= 0:
        return ValidationResult(passed=False, error="Revenue must be positive")
    if data.market.market_cap <= 0:
        return ValidationResult(passed=False, error="Market cap must be positive")
    # None ≠ 0: a missing EBITDA is "not reported", not an out-of-range value —
    # skip the margin sanity band rather than crash or flag it as a failure.
    if data.income.ebitda is not None:
        margin = data.income.ebitda / data.income.revenue
        margin_min, margin_max = ebitda_margin_range
        if not (margin_min <= margin <= margin_max):
            return ValidationResult(
                passed=False,
                error=f"EBITDA margin {margin:.1%} out of range ({margin_min:.0%} to {margin_max:.0%})",
            )
    if data.market.pe_ratio is not None and data.market.pe_ratio <= 0:
        return ValidationResult(passed=False, error="PE ratio must be positive if set")
    return ValidationResult(passed=True)


def _outlier_warnings(comps: PeerComps) -> list[str]:
    """Return warnings for any peer multiple that deviates > 5x from the peer median.

    The 5x threshold is deliberately generous — it targets pathological FX /
    unit-mismatch artifacts (TSM PE=1.85 vs median ~30x → 16x deviation) while
    leaving room for genuine outliers in cyclical/distressed sectors (e.g. a
    steel company at 0.8x EV/EBITDA vs sector median 5x is only a 6x ratio but
    is economically interpretable).

    This is a warning, not a hard failure — the comps result is still usable
    with the outlier peer present (it will have been excluded from the median by
    the sanity floor in ``calculate_multiples``). The warning surfaces the
    situation so the analyst can investigate.

    The deviation baseline is the PUBLISHED median (comps.median_*) whenever it
    exists — the same number the peer table prints. Re-deriving a median here
    (over all peers, outlier included) printed a SECOND "peer median" that
    contradicted the table (MSFT: footnote 33.60x vs table 28.77x, external
    audit 2026-07-07); the published NM-capped median is also the better
    baseline, since the outlier no longer drags its own yardstick.
    """
    warnings: list[str] = []

    def _check(
        label: str,
        vals: list[tuple[str, float]],
        published_median: float | None,
    ) -> None:
        if len(vals) < 2:
            return
        med = published_median if published_median else _median(v for _, v in vals)
        if med == 0:
            return
        for ticker, v in vals:
            ratio = max(v, med) / min(v, med)
            if ratio > 5:
                warnings.append(
                    f"{ticker} {label} {v:.2f}x deviates >{ratio:.0f}x from peer median {med:.2f}x"
                )

    ev_ebitda_vals = [(p.ticker, p.ev_ebitda) for p in comps.peers if p.ev_ebitda is not None]
    _check("EV/EBITDA", ev_ebitda_vals, comps.median_ev_ebitda)

    pe_vals = [(p.ticker, p.pe_ratio) for p in comps.peers if p.pe_ratio is not None]
    _check("P/E", pe_vals, comps.median_pe)

    ev_rev_vals = [(p.ticker, p.ev_revenue) for p in comps.peers if p.ev_revenue is not None]
    _check("EV/Revenue", ev_rev_vals, comps.median_ev_revenue)

    return warnings


def validate_peer_comps(comps: PeerComps) -> ValidationResult:
    """Validate peer analysis result.

    Collects ALL range violations across the peer set (no short-circuit) so a
    single bad ticker doesn't mask other data issues. The EV/EBITDA range is a
    garbage filter, not a "meaningfulness" filter — see
    ``finrobot.engine.compute.operators.multiples`` for the cyclical-trough rationale.

    Additionally emits non-fatal outlier warnings (> 5x from peer median) via
    ``comps.warnings`` so downstream consumers can surface data quality issues
    without blocking the pipeline.
    """
    if len(comps.peers) < 3:
        return ValidationResult(
            passed=False, error=f"Need at least 3 peers, got {len(comps.peers)}"
        )
    violations: list[str] = []
    floor_drops: list[str] = []
    for peer in comps.peers:
        if peer.revenue <= 0:
            violations.append(f"{peer.ticker} has non-positive revenue")
        # Standalone defense-in-depth guard: in the normal pipeline these bounds
        # are PRE-ENFORCED by calculate_multiples (``_sanity``/``_gate`` null any
        # out-of-band multiple), so a peer that flowed through it can never trip
        # these branches. They still earn their keep for peers built WITHOUT that
        # gating — externally/LLM-supplied multiples, hand-constructed rows — which
        # only this validator catches. What was actually missing (and what the old
        # code falsely implied this loop did) is visibility into the SILENT floor
        # drops; that is now surfaced via ``floor_drops`` below.
        if peer.ev_ebitda is not None and not (
            PEER_EV_EBITDA_SANITY_MIN <= peer.ev_ebitda <= PEER_EV_EBITDA_SANITY_MAX
        ):
            violations.append(
                f"{peer.ticker} EV/EBITDA {peer.ev_ebitda:.2f}x out of range "
                f"{PEER_EV_EBITDA_SANITY_MIN}-{PEER_EV_EBITDA_SANITY_MAX}x"
            )
        if peer.ev_revenue is not None and not (
            PEER_EV_REVENUE_SANITY_MIN <= peer.ev_revenue <= PEER_EV_REVENUE_SANITY_MAX
        ):
            violations.append(
                f"{peer.ticker} EV/Revenue {peer.ev_revenue:.2f}x out of range "
                f"{PEER_EV_REVENUE_SANITY_MIN}-{PEER_EV_REVENUE_SANITY_MAX}x"
            )
        if peer.pe_ratio is not None and not (
            PEER_PE_SANITY_MIN <= peer.pe_ratio <= PEER_PE_SANITY_MAX
        ):
            violations.append(
                f"{peer.ticker} P/E {peer.pe_ratio:.2f}x out of range "
                f"{PEER_PE_SANITY_MIN}-{PEER_PE_SANITY_MAX}x"
            )
        # The genuinely new signal: multiples that HAD computable inputs but were
        # nulled by the floor (excluded from medians) — previously invisible.
        floor_drops.extend(f"{peer.ticker}: {drop}" for drop in peer.sanity_drops)
    if violations:
        return ValidationResult(
            passed=False,
            error="Peer comps failed sanity check: " + "; ".join(violations),
        )
    if comps.median_ev_ebitda is None:
        return ValidationResult(passed=False, error="Median EV/EBITDA statistics not computed")

    # Non-fatal data-quality warnings → comps.warnings (caller may mutate):
    # floor drops (out-of-band multiples excluded from medians) + cross-sectional
    # outliers (>5x from peer median).
    if floor_drops:
        comps.warnings.extend(floor_drops)
    outlier_warnings = _outlier_warnings(comps)
    if outlier_warnings:
        comps.warnings.extend(outlier_warnings)

    return ValidationResult(passed=True)


def validate_dcf_result(result: DCFResult) -> ValidationResult:
    """Validate DCF output."""
    if result.wacc <= 0:
        return ValidationResult(passed=False, error=f"WACC must be positive, got {result.wacc}")
    if result.wacc > 0.25:
        return ValidationResult(passed=False, error=f"WACC {result.wacc:.4f} exceeds maximum 0.25")
    if result.wacc < 0.03:
        return ValidationResult(passed=False, error=f"WACC {result.wacc:.4f} below minimum 0.03")
    if result.implied_price <= 0:
        return ValidationResult(passed=False, error="Implied price must be positive")
    if result.enterprise_value <= 0:
        return ValidationResult(passed=False, error="Enterprise value must be positive")
    for fcf in result.projected_fcf:
        if not _math.isfinite(fcf):
            return ValidationResult(passed=False, error=f"Non-finite FCF value: {fcf}")
    return ValidationResult(passed=True)


def validate_thesis(thesis: ThesisResult) -> ValidationResult:
    """Validate thesis structure.

    Recommendation is normalized to uppercase before checking — agent prompts
    follow CLAUDE.md's "BUY HOLD SELL（投行惯例）" convention but mixed-case
    historical artifacts should still validate.
    """
    recommendation = thesis.recommendation.upper()
    if recommendation not in _VALID_RECOMMENDATIONS:
        return ValidationResult(
            passed=False,
            error=(
                f"Recommendation '{thesis.recommendation}' must be one of "
                f"{sorted(_VALID_RECOMMENDATIONS)} (case-insensitive)"
            ),
        )
    # The verdict is ALWAYS directional (BUY/HOLD/SELL — REVIEW deleted). The
    # POINT target is now decoupled from the verdict: it may be None (honestly
    # withheld — the only number available would be fabricated, while the verdict
    # still ships from the directional read) OR a positive value. A non-positive
    # target is the only invalid state — it is neither a defensible point nor an
    # honest withhold. A withheld SELL (price_target=None) MUST pass.
    if thesis.price_target is not None and thesis.price_target <= 0:
        return ValidationResult(
            passed=False, error="Price target must be positive or None (withheld)"
        )
    if len(thesis.catalysts) < 1:
        return ValidationResult(passed=False, error="At least 1 catalyst required")
    if len(thesis.risks) < 1:
        return ValidationResult(passed=False, error="At least 1 risk required")
    return ValidationResult(passed=True)


# ---------------------------------------------------------------------------
# LBO validators (P2d)
# ---------------------------------------------------------------------------


def validate_lbo_inputs(data: LBOInputs) -> ValidationResult:
    """Validate LLM-selected LBO assumptions are financially plausible."""
    if data.entry_ev_ebitda <= 0:
        return ValidationResult(passed=False, error="entry_ev_ebitda must be positive")
    if data.leverage_multiple >= 12:
        return ValidationResult(
            passed=False,
            error=f"leverage_multiple {data.leverage_multiple:.1f}x is unrealistically high (≥12×)",
        )
    if data.ebitda_margin <= 0:
        return ValidationResult(passed=False, error="ebitda_margin must be positive for LBO target")
    return ValidationResult(passed=True)


def validate_lbo_result(result: LBOResult) -> ValidationResult:
    """Validate LBO output values are within plausible bounds."""
    # Check entry equity first: when it is non-positive (debt ≥ entry EV) the
    # structure is impossible and the operator emits moic/irr = None (undefined,
    # NOT a total loss). Catch it here before the bounds checks dereference None.
    if result.entry_equity <= 0:
        return ValidationResult(passed=False, error="Entry equity must be positive")
    if result.moic is None or result.irr is None:
        return ValidationResult(
            passed=False, error="LBO returns undefined (non-positive entry equity)"
        )
    # moic == 0 with irr == -1 is the RATIFIED total-loss sentinel (positive entry
    # equity wiped at exit — BUG-011): a correctly-computed, meaningful outcome, not
    # an error. Rejecting it degraded a genuine total loss and leaked the deep-red
    # headline anyway. Only a NEGATIVE multiple (arithmetically impossible) fails.
    if result.moic < 0:
        return ValidationResult(passed=False, error=f"MOIC {result.moic:.2f}x cannot be negative")
    if not (-1.0 <= result.irr <= 10.0):
        return ValidationResult(
            passed=False, error=f"IRR {result.irr:.2%} out of bounds [-100%, 1000%]"
        )
    return ValidationResult(passed=True)


# ---------------------------------------------------------------------------
# Catalyst validators (P6)
# ---------------------------------------------------------------------------


def validate_catalyst_analysis(analysis: CatalystAnalysis) -> ValidationResult:
    """Validate catalyst analysis output."""
    if not analysis.events:
        return ValidationResult(passed=False, error="No catalyst events found")
    if not (-5.0 <= analysis.net_sentiment <= 5.0):
        return ValidationResult(
            passed=False,
            error=f"net_sentiment {analysis.net_sentiment} out of range [-5, 5]",
        )
    if analysis.overall_sentiment not in ("bullish", "bearish", "neutral"):
        return ValidationResult(
            passed=False,
            error=f"Invalid overall_sentiment: {analysis.overall_sentiment}",
        )
    return ValidationResult(passed=True)


# ---------------------------------------------------------------------------
# DDM validators (bank/dividend valuation)
# ---------------------------------------------------------------------------


def validate_ddm_inputs(data: DDMInputs) -> ValidationResult:
    """Validate LLM-selected DDM assumptions are financially plausible."""
    if data.dividend_per_share <= 0:
        return ValidationResult(passed=False, error="dividend_per_share must be positive")
    coe = data.risk_free_rate + data.beta * data.equity_risk_premium
    if coe <= 0:
        return ValidationResult(
            passed=False, error=f"Implied cost of equity {coe:.4f} must be positive"
        )
    if data.terminal_growth_rate >= coe:
        return ValidationResult(
            passed=False,
            error=f"Terminal growth {data.terminal_growth_rate:.1%} must be less than "
            f"cost of equity {coe:.1%}",
        )
    return ValidationResult(passed=True)


def validate_ddm_result(result: DDMResult) -> ValidationResult:
    """Validate DDM output values are within plausible bounds."""
    # Output-side invariant (defense-in-depth vs a ddm.py regression). The lower
    # bound is NOT independent confirmation: when validate_ddm_inputs ran it
    # already checked coe = rf + β·ERP > 0 with the identical formula, so a passing
    # input set guarantees coe > 0 here. Kept only to catch a compute-layer sign
    # flip; folded into one band check so it does not masquerade as a second,
    # independent gate. The upper bound (0.25) is the only genuinely new constraint.
    if not (0 < result.cost_of_equity <= 0.25):
        return ValidationResult(
            passed=False,
            error=f"Cost of equity {result.cost_of_equity:.4f} out of bounds (0, 0.25]",
        )
    if result.equity_value_per_share <= 0:
        return ValidationResult(passed=False, error="Equity value per share must be positive")
    if not _math.isfinite(result.equity_value_per_share):
        return ValidationResult(
            passed=False, error=f"Non-finite equity value: {result.equity_value_per_share}"
        )
    return ValidationResult(passed=True)


def validate_ddm_output(output: str) -> ValidationResult:
    """Strict validator for DDM pipeline output.

    Checks for DDM model components. Must find at least 3.
    """
    lower = output.lower()
    indicators = [
        any(kw in lower for kw in ["cost of equity", "discount rate"]),
        any(kw in lower for kw in ["dividend", "dps"]),
        any(kw in lower for kw in ["terminal value", "terminal growth", "gordon growth"]),
        any(
            kw in lower
            for kw in [
                "implied price",
                "implied value",
                "equity value",
                "fair value",
                "price target",
            ]
        ),
        any(
            kw in lower for kw in ["book value", "roe", "return on equity", "p/b", "price-to-book"]
        ),
    ]
    found = sum(indicators)
    if found >= 3:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 3 DDM components, found {found}",
    )
