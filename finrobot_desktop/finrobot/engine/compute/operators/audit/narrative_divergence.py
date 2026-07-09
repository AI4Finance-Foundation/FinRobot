"""Momentum-vs-verdict narrative backstop (ADR-0005 operator layer, zero I/O).

Unlike the sibling verifiers in this package (``sector_sign`` / ``currency_caliber``
/ ``ev_bridge`` / ``ttm_period``), this module does not assess whether a NUMBER is
dimensionally/definitionally correct against ``field_registry`` caliber — it
assesses whether the THESIS NARRATIVE explains itself when the directional verdict
strongly disagrees with the stock's own recent price action. It therefore does
NOT produce a :class:`~finrobot.engine.models.numeric_claim.Finding` (that model
is keyed on ``field_key`` against the static caliber registry and feeds
``ArtifactAudit``'s publishable/caveated/withhold-valuation gate — none of which
apply to a missing narrative paragraph). Instead ``audit_momentum_narrative_hedge``
returns a plain human-readable warning string that the thesis step appends onto
``StepOutput.warnings`` — the SAME channel the sell-side street-range disclosure
line (BACKLOG A9/B1) already uses: a non-blocking, reader-facing compute warning,
never a new machine code.

BACKLOG A2 (P1-1, narrative contrarian hedge): a research thesis that recommends
BUY into a stock down more than 15% over the trailing year, or SELL into a stock
up more than 30%, without saying WHY it disagrees with the market's own recent
verdict, reads as if it never looked at the price chart. The thesis prompt
(``finrobot.engine.pipelines._thesis_prompt.build_thesis_prompt``) instructs the
LLM to fill ``ThesisResult.momentum_divergence_note`` in exactly this situation;
this module is the deterministic backstop that catches a non-cooperative LLM that
skipped it — mirroring the numeric-override pattern used everywhere else in this
pipeline (core contract①: inject an authoritative instruction, then hard-enforce
it in code), just for narrative completeness instead of a number. It NEVER
touches verdict / price_target / confidence — an incomplete narrative degrades
the READ, not the call (core contract②).
"""

from __future__ import annotations

from dataclasses import dataclass

from finrobot.engine.models.financial import FinancialData

# BUY: strongly divergent when the stock is down MORE than 15% over the trailing
# year (a "catching a falling knife" call the reader will want defended). SELL:
# strongly divergent when the stock is UP more than 30% (a "calling the top of a
# rally" call). These are narrative-COMPLETENESS triggers, not valuation
# parameters — they never touch price_target / verdict / confidence, only whether
# the LLM is required to explain the divergence. Kept here as the single source
# of truth; ``build_thesis_prompt`` imports ``is_momentum_divergent`` from this
# module rather than re-deriving the threshold, so the prompt instruction and the
# post-run backstop can never drift apart.
BUY_DIVERGENCE_1Y_RETURN_PCT = -15.0
SELL_DIVERGENCE_1Y_RETURN_PCT = 30.0


@dataclass(frozen=True)
class MomentumContext:
    """Three deterministic momentum reads for the thesis prompt (all pure ratios
    derived from the SAME canonical PRICE snapshot as ``MarketData.price_52w_high``
    / ``price_52w_low`` — self-consistent, currency-invariant).

    Fields:
        one_year_return_pct:        trailing-52-week PRICE return in percent
            (dividends excluded — see ``MarketData.trailing_1y_return_pct``
            docstring). None when the price series is too short.
        range_position_52w:         ``(current - low) / (high - low)``, 0.0 =
            sitting at the 52-week low, 1.0 = sitting at the 52-week high. Can
            read slightly outside [0, 1] on a live new-high/new-low print made
            after the bar series was fixed — an honest reading, not clamped.
            None when either bound is missing or the range has zero width.
        drawdown_from_52w_high_pct: ``(current - high) / high * 100`` — zero or
            negative; e.g. -35.0 means the stock trades 35% below its 52-week
            high. None when the high is missing or non-positive.
    """

    one_year_return_pct: float | None
    range_position_52w: float | None
    drawdown_from_52w_high_pct: float | None


def compute_momentum_context(financial_data: FinancialData | None) -> MomentumContext:
    """Derive the three momentum reads from a (possibly USD-normalized)
    ``FinancialData`` snapshot. Pure — no I/O. Returns an all-None context when
    ``financial_data`` is None (data_collection step degraded / not yet run) —
    never fabricates a momentum read from partial data.
    """
    if financial_data is None:
        return MomentumContext(None, None, None)
    market = financial_data.market
    current = market.current_price
    high = market.price_52w_high
    low = market.price_52w_low

    range_position: float | None = None
    if high is not None and low is not None and high > low and current > 0:
        range_position = (current - low) / (high - low)

    drawdown: float | None = None
    if high is not None and high > 0 and current > 0:
        drawdown = (current - high) / high * 100

    return MomentumContext(
        one_year_return_pct=market.trailing_1y_return_pct,
        range_position_52w=range_position,
        drawdown_from_52w_high_pct=drawdown,
    )


def is_momentum_divergent(verdict: str | None, one_year_return_pct: float | None) -> bool:
    """True when ``verdict`` strongly disagrees with the stock's own 1y momentum.

    None-safe: an unknown verdict or a missing 1-year return (no/short price
    history) never fabricates a divergence call — it simply returns False (绝不
    编数字: never flag a condition that cannot be computed).
    """
    if verdict is None or one_year_return_pct is None:
        return False
    v = verdict.strip().upper()
    if v == "BUY":
        return one_year_return_pct < BUY_DIVERGENCE_1Y_RETURN_PCT
    if v == "SELL":
        return one_year_return_pct > SELL_DIVERGENCE_1Y_RETURN_PCT
    return False


def audit_momentum_narrative_hedge(
    verdict: str | None,
    one_year_return_pct: float | None,
    hedge_note: str | None,
) -> str | None:
    """Non-blocking warning when a divergent verdict ships with no hedge note.

    Returns None whenever ``is_momentum_divergent`` is False (nothing to
    require) OR ``hedge_note`` is a non-empty string (the LLM cooperated).
    Otherwise returns a ready-to-render warning string — append it directly to
    the thesis step's ``StepOutput.warnings``. Never gates verdict / target /
    confidence (core contract②): a missing hedge paragraph degrades the READ,
    not the call.
    """
    if not is_momentum_divergent(verdict, one_year_return_pct):
        return None
    if hedge_note is not None and hedge_note.strip():
        return None
    assert verdict is not None  # narrowed by is_momentum_divergent above
    assert one_year_return_pct is not None  # narrowed by is_momentum_divergent above
    direction = "up" if one_year_return_pct > 0 else "down"
    return (
        f"[NARRATIVE-MOMENTUM] {verdict} recommendation despite the stock being "
        f"{direction} {abs(one_year_return_pct):.1f}% over the trailing year — the "
        "thesis narrative does not explain what the market is pricing in or why "
        "this call differs from recent price action."
    )
