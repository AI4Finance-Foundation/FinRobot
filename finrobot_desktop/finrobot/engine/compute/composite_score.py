"""Composite Score — weighted sub-scores from fundamentals, technicals, catalysts, sentiment.

What this code does that raw LLM cannot:
- Produces a reproducible 0-100 integer score with a deterministic weighting formula.
- Each sub-score has an explicit, auditable threshold table — not vibes.
- Baseline of 50 (neutral) ensures missing data doesn't accidentally push toward buy/sell.
- Score → signal mapping is a simple lookup, not an LLM judgment call.

Weights: fundamental 30%, valuation 30%, catalyst 20%, sentiment 20%
Signal thresholds:
  80-100: STRONG_BUY
  60-79:  BUY
  40-59:  HOLD
  20-39:  SELL
  0-19:   STRONG_SELL
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreRequest(BaseModel):
    # Fundamental inputs
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    gross_margin: float | None = None
    gross_margin_industry_median: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_beat_rate: float | None = Field(default=None, ge=0, le=1)

    # Catalyst inputs
    positive_catalysts: int = Field(default=0, ge=0)
    negative_catalysts: int = Field(default=0, ge=0)

    # Sentiment inputs
    news_sentiment: float | None = Field(default=None, ge=-1, le=1)

    # Valuation inputs
    dcf_upside_pct: float | None = None  # e.g. 0.20 for 20% upside


class CompositeScore(BaseModel):
    total: int = Field(ge=0, le=100)
    fundamental: int = Field(ge=0, le=100)
    valuation: int = Field(ge=0, le=100)
    catalyst: int = Field(ge=0, le=100)
    sentiment: int = Field(ge=0, le=100)
    signal: str  # "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL"
    breakdown: dict[str, str]  # human-readable explanations per sub-score


# ---------------------------------------------------------------------------
# Audit tables — every weight / threshold / delta lives here so reviewers can
# diff scoring changes without reading the function bodies.
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "fundamental": 0.30,
    "valuation": 0.30,
    "catalyst": 0.20,
    "sentiment": 0.20,
}

_BASELINE = 50  # neutral starting score for every sub-component

_SIGNALS: list[tuple[int, str]] = [
    (80, "STRONG_BUY"),
    (60, "BUY"),
    (40, "HOLD"),
    (20, "SELL"),
    (0, "STRONG_SELL"),
]


def _signal_for(total: int) -> str:
    for threshold, label in _SIGNALS:
        if total >= threshold:
            return label
    return "STRONG_SELL"


def _clamp_score(score: int) -> int:
    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Sub-scores — each returns (score, reason_text). Score is clamped to [0,100].
# ---------------------------------------------------------------------------


def _score_fundamental(req: ScoreRequest) -> tuple[int, str]:
    score = _BASELINE
    reasons: list[str] = []

    if req.peg_ratio is not None:
        if req.peg_ratio < 1.0:
            score += 20
            reasons.append(f"PEG {req.peg_ratio:.1f} < 1 (undervalued growth)")
        elif req.peg_ratio < 1.5:
            score += 10
            reasons.append(f"PEG {req.peg_ratio:.1f} reasonable")
        elif req.peg_ratio > 2.5:
            score -= 15
            reasons.append(f"PEG {req.peg_ratio:.1f} > 2.5 (expensive growth)")

    if req.gross_margin is not None and req.gross_margin_industry_median is not None:
        margin_diff = req.gross_margin - req.gross_margin_industry_median
        if margin_diff > 0.15:
            score += 15
            reasons.append(
                f"Gross margin {req.gross_margin * 100:.0f}% vs "
                f"industry {req.gross_margin_industry_median * 100:.0f}% (+{margin_diff * 100:.0f}pp)"
            )
        elif margin_diff > 0.05:
            score += 8
        elif margin_diff < -0.10:
            score -= 10
            reasons.append(
                f"Gross margin {req.gross_margin * 100:.0f}% below industry "
                f"{req.gross_margin_industry_median * 100:.0f}%"
            )

    if req.revenue_growth_yoy is not None:
        if req.revenue_growth_yoy > 0.30:
            score += 15
            reasons.append(f"Revenue growth {req.revenue_growth_yoy * 100:.0f}% YoY (strong)")
        elif req.revenue_growth_yoy > 0.10:
            score += 8
        elif req.revenue_growth_yoy < 0:
            score -= 15
            reasons.append(f"Revenue declining {req.revenue_growth_yoy * 100:.0f}% YoY")

    if req.earnings_beat_rate is not None:
        if req.earnings_beat_rate >= 0.80:
            score += 10
            reasons.append(f"Earnings beat rate {req.earnings_beat_rate * 100:.0f}% (consistent)")
        elif req.earnings_beat_rate < 0.50:
            score -= 10
            reasons.append(f"Earnings beat rate {req.earnings_beat_rate * 100:.0f}% (inconsistent)")

    return _clamp_score(score), "; ".join(reasons) if reasons else "Insufficient data"


def _score_valuation(req: ScoreRequest) -> tuple[int, str]:
    score = _BASELINE
    reasons: list[str] = []

    if req.dcf_upside_pct is not None:
        if req.dcf_upside_pct > 0.30:
            score += 30
            reasons.append(
                f"DCF upside {req.dcf_upside_pct * 100:.0f}% (significant margin of safety)"
            )
        elif req.dcf_upside_pct > 0.15:
            score += 20
            reasons.append(f"DCF upside {req.dcf_upside_pct * 100:.0f}%")
        elif req.dcf_upside_pct > 0:
            score += 10
        elif req.dcf_upside_pct > -0.10:
            score -= 10
        else:
            score -= 25
            reasons.append(f"DCF downside {req.dcf_upside_pct * 100:.0f}% (overvalued)")

    if req.pe_ratio is not None:
        if 0 < req.pe_ratio < 15:
            score += 10
            reasons.append(f"P/E {req.pe_ratio:.0f}x (historically cheap)")
        elif req.pe_ratio > 50:
            score -= 10
            reasons.append(f"P/E {req.pe_ratio:.0f}x (premium valuation)")

    return _clamp_score(score), "; ".join(reasons) if reasons else "Insufficient data"


def _score_catalyst(req: ScoreRequest) -> tuple[int, str]:
    score = _BASELINE
    reasons: list[str] = []
    net = req.positive_catalysts - req.negative_catalysts

    if net > 2:
        score += 25
        reasons.append(
            f"{req.positive_catalysts} positive vs {req.negative_catalysts} negative catalysts"
        )
    elif net > 0:
        score += 12
    elif net < -2:
        score -= 25
        reasons.append(
            f"{req.negative_catalysts} negative vs {req.positive_catalysts} positive catalysts"
        )
    elif net < 0:
        score -= 12

    return _clamp_score(score), "; ".join(reasons) if reasons else "Balanced catalysts"


def _score_sentiment(req: ScoreRequest) -> tuple[int, str]:
    score = _BASELINE
    reasons: list[str] = []

    if req.news_sentiment is not None:
        if req.news_sentiment > 0.3:
            score += 25
            reasons.append(f"Positive news sentiment ({req.news_sentiment:.2f})")
        elif req.news_sentiment > 0.1:
            score += 12
        elif req.news_sentiment < -0.3:
            score -= 25
            reasons.append(f"Negative news sentiment ({req.news_sentiment:.2f})")
        elif req.news_sentiment < -0.1:
            score -= 12

    return _clamp_score(score), "; ".join(reasons) if reasons else "Neutral sentiment"


def calculate_composite_score(req: ScoreRequest) -> CompositeScore:
    """Calculate a 0-100 composite score from sub-components.

    All scoring is deterministic — threshold tables are hardcoded, not inferred
    by LLM. Each sub-score starts at 50 (neutral baseline) so missing inputs
    stay at neutral rather than falsely signalling buy or sell.
    """
    fund, fund_reason = _score_fundamental(req)
    val, val_reason = _score_valuation(req)
    cat, cat_reason = _score_catalyst(req)
    sent, sent_reason = _score_sentiment(req)

    total = round(
        fund * WEIGHTS["fundamental"]
        + val * WEIGHTS["valuation"]
        + cat * WEIGHTS["catalyst"]
        + sent * WEIGHTS["sentiment"]
    )
    total = _clamp_score(total)

    return CompositeScore(
        total=total,
        fundamental=fund,
        valuation=val,
        catalyst=cat,
        sentiment=sent,
        signal=_signal_for(total),
        breakdown={
            "fundamental": fund_reason,
            "valuation": val_reason,
            "catalyst": cat_reason,
            "sentiment": sent_reason,
        },
    )
