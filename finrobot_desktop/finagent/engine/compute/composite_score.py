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


def calculate_composite_score(req: ScoreRequest) -> CompositeScore:
    """Calculate a 0-100 composite score from sub-components.

    All scoring is deterministic — threshold tables are hardcoded, not inferred
    by LLM. Each sub-score starts at 50 (neutral baseline) so missing inputs
    stay at neutral rather than falsely signalling buy or sell.
    """
    breakdown: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # Fundamental score — 30% weight
    # -------------------------------------------------------------------------
    fund_score = 50  # neutral baseline
    fund_reasons: list[str] = []

    if req.peg_ratio is not None:
        if req.peg_ratio < 1.0:
            fund_score += 20
            fund_reasons.append(f"PEG {req.peg_ratio:.1f} < 1 (undervalued growth)")
        elif req.peg_ratio < 1.5:
            fund_score += 10
            fund_reasons.append(f"PEG {req.peg_ratio:.1f} reasonable")
        elif req.peg_ratio > 2.5:
            fund_score -= 15
            fund_reasons.append(f"PEG {req.peg_ratio:.1f} > 2.5 (expensive growth)")

    if req.gross_margin is not None and req.gross_margin_industry_median is not None:
        margin_diff = req.gross_margin - req.gross_margin_industry_median
        if margin_diff > 0.15:
            fund_score += 15
            fund_reasons.append(
                f"Gross margin {req.gross_margin*100:.0f}% vs "
                f"industry {req.gross_margin_industry_median*100:.0f}% (+{margin_diff*100:.0f}pp)"
            )
        elif margin_diff > 0.05:
            fund_score += 8
        elif margin_diff < -0.10:
            fund_score -= 10
            fund_reasons.append(
                f"Gross margin {req.gross_margin*100:.0f}% below industry "
                f"{req.gross_margin_industry_median*100:.0f}%"
            )

    if req.revenue_growth_yoy is not None:
        if req.revenue_growth_yoy > 0.30:
            fund_score += 15
            fund_reasons.append(
                f"Revenue growth {req.revenue_growth_yoy*100:.0f}% YoY (strong)"
            )
        elif req.revenue_growth_yoy > 0.10:
            fund_score += 8
        elif req.revenue_growth_yoy < 0:
            fund_score -= 15
            fund_reasons.append(
                f"Revenue declining {req.revenue_growth_yoy*100:.0f}% YoY"
            )

    if req.earnings_beat_rate is not None:
        if req.earnings_beat_rate >= 0.80:
            fund_score += 10
            fund_reasons.append(
                f"Earnings beat rate {req.earnings_beat_rate*100:.0f}% (consistent)"
            )
        elif req.earnings_beat_rate < 0.50:
            fund_score -= 10
            fund_reasons.append(
                f"Earnings beat rate {req.earnings_beat_rate*100:.0f}% (inconsistent)"
            )

    fund_score = max(0, min(100, fund_score))
    breakdown["fundamental"] = (
        "; ".join(fund_reasons) if fund_reasons else "Insufficient data"
    )

    # -------------------------------------------------------------------------
    # Valuation score — 30% weight
    # -------------------------------------------------------------------------
    val_score = 50
    val_reasons: list[str] = []

    if req.dcf_upside_pct is not None:
        if req.dcf_upside_pct > 0.30:
            val_score += 30
            val_reasons.append(
                f"DCF upside {req.dcf_upside_pct*100:.0f}% (significant margin of safety)"
            )
        elif req.dcf_upside_pct > 0.15:
            val_score += 20
            val_reasons.append(f"DCF upside {req.dcf_upside_pct*100:.0f}%")
        elif req.dcf_upside_pct > 0:
            val_score += 10
        elif req.dcf_upside_pct > -0.10:
            val_score -= 10
        else:
            val_score -= 25
            val_reasons.append(
                f"DCF downside {req.dcf_upside_pct*100:.0f}% (overvalued)"
            )

    if req.pe_ratio is not None:
        if 0 < req.pe_ratio < 15:
            val_score += 10
            val_reasons.append(f"P/E {req.pe_ratio:.0f}x (historically cheap)")
        elif req.pe_ratio > 50:
            val_score -= 10
            val_reasons.append(f"P/E {req.pe_ratio:.0f}x (premium valuation)")

    val_score = max(0, min(100, val_score))
    breakdown["valuation"] = (
        "; ".join(val_reasons) if val_reasons else "Insufficient data"
    )

    # -------------------------------------------------------------------------
    # Catalyst score — 20% weight
    # -------------------------------------------------------------------------
    cat_score = 50
    cat_reasons: list[str] = []
    net_catalysts = req.positive_catalysts - req.negative_catalysts

    if net_catalysts > 2:
        cat_score += 25
        cat_reasons.append(
            f"{req.positive_catalysts} positive vs {req.negative_catalysts} negative catalysts"
        )
    elif net_catalysts > 0:
        cat_score += 12
    elif net_catalysts < -2:
        cat_score -= 25
        cat_reasons.append(
            f"{req.negative_catalysts} negative vs {req.positive_catalysts} positive catalysts"
        )
    elif net_catalysts < 0:
        cat_score -= 12

    cat_score = max(0, min(100, cat_score))
    breakdown["catalyst"] = (
        "; ".join(cat_reasons) if cat_reasons else "Balanced catalysts"
    )

    # -------------------------------------------------------------------------
    # Sentiment score — 20% weight
    # -------------------------------------------------------------------------
    sent_score = 50
    sent_reasons: list[str] = []

    if req.news_sentiment is not None:
        if req.news_sentiment > 0.3:
            sent_score += 25
            sent_reasons.append(
                f"Positive news sentiment ({req.news_sentiment:.2f})"
            )
        elif req.news_sentiment > 0.1:
            sent_score += 12
        elif req.news_sentiment < -0.3:
            sent_score -= 25
            sent_reasons.append(
                f"Negative news sentiment ({req.news_sentiment:.2f})"
            )
        elif req.news_sentiment < -0.1:
            sent_score -= 12

    sent_score = max(0, min(100, sent_score))
    breakdown["sentiment"] = (
        "; ".join(sent_reasons) if sent_reasons else "Neutral sentiment"
    )

    # -------------------------------------------------------------------------
    # Weighted total
    # -------------------------------------------------------------------------
    total = round(
        fund_score * 0.30
        + val_score * 0.30
        + cat_score * 0.20
        + sent_score * 0.20
    )
    total = max(0, min(100, total))

    return CompositeScore(
        total=total,
        fundamental=fund_score,
        valuation=val_score,
        catalyst=cat_score,
        sentiment=sent_score,
        signal=_signal_for(total),
        breakdown=breakdown,
    )
