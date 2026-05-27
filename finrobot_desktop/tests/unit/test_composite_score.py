"""Unit tests for finrobot.engine.compute.composite_score.calculate_composite_score.

External sources for expected values / thresholds:
- PEG ratio thresholds (< 1 = undervalued, > 2.5 = expensive):
  Source: Peter Lynch "One Up On Wall Street", also CFA Institute curriculum
  "Equity Valuation" reading on PEG ratio.
- Gross margin comparison to industry: standard fundamental analysis practice.
  Source: Damodaran data pages (industry median margins publicly available at
  pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/margin.html).
- Revenue growth thresholds: standard analyst convention (>30% = high-growth,
  <0% = declining). Source: CFA Institute "Financial Statement Analysis" reading.
- P/E < 15 = historically cheap threshold: Shiller CAPE mean-reversion range.
  Source: Robert Shiller CAPE data (irrationalexuberance.com).
- Weighted total formula (30/30/20/20): hardcoded in composite_score.py.
  Tests verify arithmetic, not business logic.

These tests verify deterministic arithmetic. No expected value is computed by
the function under test — each is derived by hand and documented below.
"""
from __future__ import annotations


from finrobot.engine.compute.composite_score import (
    ScoreRequest,
    calculate_composite_score,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _req(**kwargs) -> ScoreRequest:
    return ScoreRequest(**kwargs)


# ---------------------------------------------------------------------------
# 1. All-None inputs → neutral score = 50
#    fund=50, val=50, cat=50, sent=50 → total = 50*0.3+50*0.3+50*0.2+50*0.2 = 50
# ---------------------------------------------------------------------------

def test_composite_score_all_none_inputs_is_neutral():
    """All missing inputs → baseline 50 (neutral / HOLD).

    Manual: total = 50*0.30 + 50*0.30 + 50*0.20 + 50*0.20 = 50.
    """
    result = calculate_composite_score(_req())
    assert result.total == 50
    assert result.signal == "HOLD"


# ---------------------------------------------------------------------------
# 2. Signal thresholds
# ---------------------------------------------------------------------------

def test_composite_score_signal_strong_buy():
    """Score >= 80 → STRONG_BUY.

    Achieve via: PEG=0.5 (+20), gross_margin 20pp above industry (+15),
    revenue_growth=35% (+15), earnings_beat=0.85 (+10) → fund = min(110,100)=100.
    DCF upside 40% (+30), PE=10 (+10) → val = 90 (capped 100).
    positive_catalysts=5, negative=0 → net=5>2 → cat=75.
    sentiment=0.5 → sent=75.
    total = 100*0.30 + 100*0.30 + 75*0.20 + 75*0.20 = 30+30+15+15 = 90 → STRONG_BUY.
    """
    result = calculate_composite_score(_req(
        peg_ratio=0.5,
        gross_margin=0.60,
        gross_margin_industry_median=0.40,  # +20pp
        revenue_growth_yoy=0.35,
        earnings_beat_rate=0.85,
        dcf_upside_pct=0.40,
        pe_ratio=10.0,
        positive_catalysts=5,
        negative_catalysts=0,
        news_sentiment=0.5,
    ))
    assert result.total >= 80
    assert result.signal == "STRONG_BUY"


def test_composite_score_signal_strong_sell():
    """Score <= 19 → STRONG_SELL.

    Achieve via: PEG=3.0 (-15), gross_margin 15pp below industry (-10),
    revenue_growth=-20% (-15), earnings_beat=0.40 (-10) → fund=50-15-10-15-10=0.
    DCF upside=-0.20 (-25), PE=60 (-10) → val=50-25-10=15.
    positive_catalysts=0, negative=5 → net=-5 < -2 → cat=50-25=25.
    sentiment=-0.5 → sent=50-25=25.
    total = 0*0.30 + 15*0.30 + 25*0.20 + 25*0.20 = 0+4.5+5+5 = 14.5 → 15 → STRONG_SELL.
    """
    result = calculate_composite_score(_req(
        peg_ratio=3.0,
        gross_margin=0.20,
        gross_margin_industry_median=0.35,  # -15pp
        revenue_growth_yoy=-0.20,
        earnings_beat_rate=0.40,
        dcf_upside_pct=-0.20,
        pe_ratio=60.0,
        positive_catalysts=0,
        negative_catalysts=5,
        news_sentiment=-0.5,
    ))
    assert result.total <= 19
    assert result.signal == "STRONG_SELL"


# ---------------------------------------------------------------------------
# 3. Negative revenue growth (declining company)
# ---------------------------------------------------------------------------

def test_composite_score_negative_revenue_growth_reduces_fund_score():
    """Negative YoY revenue → fundamental score reduced by 15.

    Baseline fund=50, peg=None, margin=None, earnings=None,
    revenue_growth=-0.10 → fund = 50 - 15 = 35.
    """
    result = calculate_composite_score(_req(revenue_growth_yoy=-0.10))
    assert result.fundamental == 35
    assert "declining" in result.breakdown["fundamental"].lower()


# ---------------------------------------------------------------------------
# 4. Zero / near-zero upside (DCF downside)
# ---------------------------------------------------------------------------

def test_composite_score_dcf_downside_reduces_valuation_score():
    """DCF upside < -10% → valuation score reduced by 25 (from baseline 50).

    Source: sniper.py threshold table — val_score -= 25 when dcf_upside < -0.10.
    Manual: val = 50 - 25 = 25.
    """
    result = calculate_composite_score(_req(dcf_upside_pct=-0.30))
    assert result.valuation == 25
    assert "overvalued" in result.breakdown["valuation"].lower()


def test_composite_score_small_dcf_downside_moderate_reduction():
    """DCF upside between -10% and 0% → valuation score reduced by 10.

    Manual: val = 50 - 10 = 40.
    """
    result = calculate_composite_score(_req(dcf_upside_pct=-0.05))
    assert result.valuation == 40


# ---------------------------------------------------------------------------
# 5. P/E edge cases (negative / zero PE for loss-making company)
# ---------------------------------------------------------------------------

def test_composite_score_negative_pe_ratio_no_adjustment():
    """Negative P/E (loss-making company) falls in no scoring branch → no delta.

    The scoring logic has: 0 < pe < 15 (+10) and pe > 50 (-10). Negative P/E
    falls in neither → val_score unchanged from other inputs.
    Manual: dcf_upside=None, pe=-5 → val = 50 (no branch matches negative PE).
    """
    result = calculate_composite_score(_req(pe_ratio=-5.0))
    assert result.valuation == 50


def test_composite_score_zero_pe_ratio_no_adjustment():
    """P/E == 0 falls in 'not 0 < pe < 15' branch → no change.

    Manual: val = 50.
    """
    result = calculate_composite_score(_req(pe_ratio=0.0))
    assert result.valuation == 50


# ---------------------------------------------------------------------------
# 6. Total score clamp: sub-scores are clamped 0–100
# ---------------------------------------------------------------------------

def test_composite_score_total_clamped_0_100():
    """Total score never exceeds 100 or goes below 0 regardless of inputs.

    This is a data-validity invariant, not a business logic test.
    """
    result = calculate_composite_score(_req(
        peg_ratio=0.1,
        gross_margin=0.99,
        gross_margin_industry_median=0.01,
        revenue_growth_yoy=2.0,
        earnings_beat_rate=1.0,
        dcf_upside_pct=10.0,
        pe_ratio=1.0,
        positive_catalysts=100,
        negative_catalysts=0,
        news_sentiment=1.0,
    ))
    assert 0 <= result.total <= 100
    assert 0 <= result.fundamental <= 100
    assert 0 <= result.valuation <= 100
    assert 0 <= result.catalyst <= 100
    assert 0 <= result.sentiment <= 100


def test_composite_score_minimum_clamped_at_zero():
    """Sub-scores cannot go below 0 even with maximally negative inputs."""
    result = calculate_composite_score(_req(
        peg_ratio=100.0,
        gross_margin=0.0,
        gross_margin_industry_median=0.99,
        revenue_growth_yoy=-10.0,
        earnings_beat_rate=0.0,
        dcf_upside_pct=-100.0,
        pe_ratio=1000.0,
        positive_catalysts=0,
        negative_catalysts=100,
        news_sentiment=-1.0,
    ))
    assert result.total >= 0
    assert result.fundamental >= 0
    assert result.valuation >= 0
    assert result.catalyst >= 0
    assert result.sentiment >= 0


# ---------------------------------------------------------------------------
# 7. Weighted total arithmetic — deterministic formula verification
#    fund=60, val=70, cat=80, sent=40
#    total = round(60*0.30 + 70*0.30 + 80*0.20 + 40*0.20)
#          = round(18 + 21 + 16 + 8) = round(63) = 63
# ---------------------------------------------------------------------------

def test_composite_score_weighted_total_arithmetic():
    """Verify weighted total formula with known sub-score values.

    To get fund=60: baseline 50 + PEG 0.9 (< 1.0) → +20 → 70, capped to 70.
    But let's use a simpler approach: only inject revenue_growth=0.15 (+8) → fund=58.
    Since we want exact 60, use PEG=0.9 (+20) alone → fund=70. Not 60.

    Instead use: revenue_growth=0.05 (0<x<0.10 → no branch, 0.10<x<0.30 → +8)
    No: 0.05 < 0.10 so no branch. Let's use 0.15 → +8, fund=58.

    Simplest: verify total for all-None (fund=val=cat=sent=50) → total=50.
    Verified by test 1. Here we verify a non-trivial case.

    Manual: PEG=0.9 → fund = 50+20 = 70; dcf=0.35>0.30 → val=50+30=80;
    net_catalysts=3>2 → cat=50+25=75; sentiment=0.4>0.3 → sent=50+25=75.
    total = round(70*0.30 + 80*0.30 + 75*0.20 + 75*0.20)
          = round(21 + 24 + 15 + 15) = round(75) = 75 → BUY.
    """
    result = calculate_composite_score(_req(
        peg_ratio=0.9,
        dcf_upside_pct=0.35,
        positive_catalysts=3,
        negative_catalysts=0,
        news_sentiment=0.4,
    ))
    assert result.fundamental == 70
    assert result.valuation == 80
    assert result.catalyst == 75
    assert result.sentiment == 75
    assert result.total == 75
    assert result.signal == "BUY"


# ---------------------------------------------------------------------------
# 8. Breakdown dict always contains expected keys
# ---------------------------------------------------------------------------

def test_composite_score_breakdown_keys_present():
    """CompositeScore.breakdown always contains the four sub-score keys."""
    result = calculate_composite_score(_req())
    assert "fundamental" in result.breakdown
    assert "valuation" in result.breakdown
    assert "catalyst" in result.breakdown
    assert "sentiment" in result.breakdown


# ---------------------------------------------------------------------------
# 9. Determinism — same inputs produce identical outputs
# ---------------------------------------------------------------------------

def test_composite_score_deterministic():
    """Identical inputs always produce identical outputs."""
    req = _req(peg_ratio=1.2, dcf_upside_pct=0.20, news_sentiment=0.1)
    r1 = calculate_composite_score(req)
    r2 = calculate_composite_score(req)
    assert r1.total == r2.total
    assert r1.signal == r2.signal


# ---------------------------------------------------------------------------
# 10. Gross margin below industry (loss-making analog)
# ---------------------------------------------------------------------------

def test_composite_score_gross_margin_below_industry():
    """Gross margin more than 10pp below industry → fundamental score -10.

    Manual: baseline 50 - 10 = 40.
    Source: composite_score.py line: fund_score -= 10 when margin_diff < -0.10.
    """
    result = calculate_composite_score(_req(
        gross_margin=0.20,
        gross_margin_industry_median=0.35,  # diff = -0.15 < -0.10
    ))
    assert result.fundamental == 40
    assert "below industry" in result.breakdown["fundamental"].lower()
