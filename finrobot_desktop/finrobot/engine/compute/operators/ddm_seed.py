"""Single authoritative DDMInputs builder — banks and dividend-paying stocks.

What this code does that raw LLM cannot:
- Deterministically derives every DDM assumption from the provider's reported
  dividend / payout / ROE / beta — never lets the LLM "pick" a growth rate from
  a typically-3-8% prompt. Dividend growth is the textbook sustainable growth
  ``g = ROE × (1 − payout)`` decayed to perpetuity, not a narrative guess.
- Normalizes the terminal payout to ``1 − g/ROE`` (the payout a mature firm can
  sustain at its ROE and terminal growth) so the Gordon perpetuity doesn't carry
  a low trailing payout forever — the error that values JPM (28% payout, 16.5%
  ROE) at a third of its price. See ``calculate_ddm`` terminal step.
- Records the *source* of each assumption in ``assumption_provenance`` so the UI
  can render "g = ROE 16.5% × (1−28%) = 11.8%，衰减到永续 2.5%" instead of an
  opaque number.

This module is the only sanctioned producer of DDMInputs in the codebase.
The legacy LLM ``_execute_ddm_params`` path (Agent with output_type=DDMInputs)
is removed; the DDM pipeline calls ``seed_ddm_inputs``.

Mirrors ``dcf_seed`` / ``lbo_seed``: the market-wide macro defaults and the
``_decay_growth_schedule`` / ``_pick_with_provenance`` helpers are reused from
``dcf_seed`` (the same convention ``lbo_seed`` follows) rather than redefined.
"""

from __future__ import annotations

from typing import Final

from finrobot.engine.compute.operators.dcf_seed import (
    _BETA_BAND_CEILING,
    _BETA_BAND_FLOOR,
    _BETA_OUT_OF_BAND_REASON,
    DEFAULT_EQUITY_RISK_PREMIUM,
    DEFAULT_PROJECTION_YEARS,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH,
    _decay_growth_schedule,
    _pick_with_provenance,
)
from finrobot.engine.data.industry_defaults import IndustryDefault, get_industry_default
from finrobot.engine.data.normalize.contracts import NormalizedFinancials
from finrobot.engine.models.financial import DDMInputs, FinancialData

# Generic payout used only when the provider reports neither a payout ratio nor
# enough (DPS + positive EPS) to derive one. Market-wide, not per-company, so it
# doesn't violate the "no hardcoded per-company defaults" rule — parallel to
# dcf_seed's 1% ΔNWC fallback.
_DEFAULT_PAYOUT_RATIO: Final[float] = 0.5

# Sustainable dividend growth is clamped to this ceiling before decay — beyond
# it the Gordon multi-stage convergence stops being meaningful.
_MAX_SUSTAINABLE_GROWTH: Final[float] = 0.40

# CAPM beta clamp — same band dcf_seed uses, tighter than the DDMInputs Field
# ceiling (≤ 3) so an outlier provider beta can't blow up cost of equity.
_BETA_FLOOR: Final[float] = 0.3
_BETA_CAP: Final[float] = 2.5


def seed_ddm_inputs(
    financials: FinancialData,
    normalized: NormalizedFinancials,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
    terminal_growth_rate: float = DEFAULT_TERMINAL_GROWTH,
    projection_years: int = DEFAULT_PROJECTION_YEARS,
) -> DDMInputs:
    """Build a complete DDMInputs from one ticker's snapshot.

    ``financials`` supplies the validated market fields (shares, price, beta,
    net income, industry). ``normalized`` supplies the dividend-specific fields
    (DPS, payout, ROE, book value) that ``FinancialData`` does not carry — both
    describe the same snapshot; the executor builds ``normalized`` via
    ``normalize_financials`` on the same DataResult.

    Field derivation:
      - dividend_per_share: provider DPS → payout × net_income / shares.
      - payout_ratio: provider → DPS / EPS → generic 50%.
      - dividend_growth_rates: sustainable ``g = ROE × (1 − payout)`` clamped to
        [0, 40%], linearly decayed to ``terminal_growth_rate``. ROE missing ⇒
        generic growth start (same fallback as dcf_seed).
      - terminal_payout_ratio: ``1 − g/ROE`` (floored at trailing payout); None
        when ROE missing, which leaves calculate_ddm on the naive Gordon path.
      - beta: provider beta → industry levered beta, clamped to [0.3, 2.5].
      - risk_free / ERP / terminal: market-wide macro defaults (shared with DCF).

    Raises:
        ValueError: when no positive dividend can be established (DDM is
            inapplicable to a non-dividend-payer).
    """
    industry: IndustryDefault = get_industry_default(financials.market.industry)
    prov: dict[str, str] = {}

    net_income = financials.income.net_income
    shares = financials.market.shares_outstanding
    current_price = financials.market.current_price

    # ----- dividend_per_share -----------------------------------------------
    dps = normalized.dividend_per_share
    if dps is not None and dps > 0:
        prov["dividend_per_share"] = f"${dps:.2f} (provider-reported annualized DPS)"
    else:
        payout_raw = normalized.payout_ratio
        if (
            payout_raw
            and payout_raw > 0
            and net_income is not None
            and net_income > 0
            and shares > 0
        ):
            dps = payout_raw * net_income / shares
            prov["dividend_per_share"] = (
                f"${dps:.2f} (payout ratio {payout_raw:.1%} × net income ÷ shares; provider did not report DPS directly)"
            )
        else:
            raise ValueError(
                f"DDM requires a positive dividend for {financials.ticker}; provider "
                "supplied neither dividend_per_share nor (payout_ratio + net_income)."
            )

    # ----- payout_ratio ------------------------------------------------------
    payout = normalized.payout_ratio
    if payout is not None and 0 < payout <= 1:
        prov["payout_ratio"] = f"{payout:.1%} (provider-reported payout ratio)"
    else:
        eps = net_income / shares if (net_income is not None and shares > 0) else 0.0
        if eps > 0:
            payout = dps / eps
            prov["payout_ratio"] = f"{payout:.1%} (DPS ÷ EPS; provider did not report payout ratio)"
        else:
            payout = _DEFAULT_PAYOUT_RATIO
            prov["payout_ratio"] = (
                f"{payout:.1%} (generic benchmark; neither payout ratio nor EPS available)"
            )
    payout = max(0.0, min(1.0, payout))

    # ----- dividend_growth_rates --------------------------------------------
    # Sustainable growth g = retention × ROE = (1 − payout) × ROE — the rate at
    # which a firm reinvesting at ROE grows book value (and, at constant payout,
    # EPS and DPS). Decays linearly to terminal growth over the explicit window.
    roe = normalized.return_on_equity
    if roe is not None and roe > 0:
        g = max(0.0, min(_MAX_SUSTAINABLE_GROWTH, roe * (1 - payout)))
        growth_source = (
            f"sustainable growth g = ROE {roe:.1%} × (1 − payout ratio {payout:.1%}) = {g:.1%}"
        )
    else:
        g = max(terminal_growth_rate * 2, 0.05)
        growth_source = f"ROE unavailable; using a generic {g:.1%} growth starting point"
    growth_schedule = _decay_growth_schedule(g, terminal_growth_rate, projection_years)
    if g > terminal_growth_rate:
        prov["dividend_growth_rates"] = (
            f"{growth_source}, fading linearly to terminal {terminal_growth_rate:.1%} over the next {projection_years}yr"
        )
    else:
        prov["dividend_growth_rates"] = (
            f"{growth_source}, held flat at this rate over the next {projection_years}yr (terminal {terminal_growth_rate:.1%})"
        )

    # ----- terminal_payout_ratio --------------------------------------------
    # At terminal growth, the payout consistent with a sustained ROE is
    # 1 − g/ROE (the rest is the retention needed to grow book at g). Floored at
    # the trailing payout — a maturing firm returns more, never less. None when
    # ROE is unknown, leaving calculate_ddm on the constant-payout Gordon path.
    if roe is not None and roe > terminal_growth_rate:
        terminal_payout: float | None = max(payout, min(1.0, 1 - terminal_growth_rate / roe))
        prov["terminal_payout_ratio"] = (
            f"{terminal_payout:.1%} (terminal payout ratio = 1 − terminal growth {terminal_growth_rate:.1%} / "
            f"ROE {roe:.1%})"
        )
    else:
        terminal_payout = None
        prov["terminal_payout_ratio"] = (
            "payout ratio held constant in perpetuity (ROE unavailable; cannot normalize terminal payout)"
        )

    # ----- beta (CAPM) -------------------------------------------------------
    beta_chosen, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider-reported 5y adjusted beta",
        industry_value=industry.levered_beta,
        industry_label=f"{industry.industry} industry levered beta",
        floor=_BETA_BAND_FLOOR,
        ceiling=_BETA_BAND_CEILING,
        rejected_ticker_reason=_BETA_OUT_OF_BAND_REASON,
        reject_value_fmt="{:.2f}",
    )
    # Pre-existing DDM clamp — load-bearing for crash safety: DDMInputs.beta is
    # Field(ge=0, le=3), tighter than DCF's le=5, so a high in-band raw beta whose
    # Blume value would exceed 3 (e.g. raw 4.8 → 3.53) MUST be capped here or the
    # construction raises. Left exactly as found; the negative-beta fix only changes
    # the _pick_with_provenance call above (out-of-band → industry proxy).
    beta_final = max(_BETA_FLOOR, min(_BETA_CAP, beta_chosen))
    prov["beta"] = f"{beta_final:.2f} ({beta_source})"

    prov["risk_free_rate"] = f"{risk_free_rate:.1%} (current 10Y US Treasury yield)"
    prov["equity_risk_premium"] = f"{equity_risk_premium:.1%} (Damodaran implied ERP)"
    prov["terminal_growth_rate"] = f"{terminal_growth_rate:.1%} (long-run US nominal GDP growth)"
    prov["shares_outstanding"] = f"current shares outstanding {shares / 1e9:.2f}B shares"
    prov["current_price"] = f"current share price ${current_price:.2f}"

    book_value_per_share = normalized.book_value_per_share
    if roe is not None:
        prov["return_on_equity"] = f"{roe:.1%} (provider-reported ROE)"
    if book_value_per_share is not None and book_value_per_share > 0:
        prov["book_value_per_share"] = (
            f"${book_value_per_share:.2f} (provider-reported book value per share)"
        )

    # Clamp to DDMInputs Field bounds before constructing so an industry-fallback
    # edge case can't raise (terminal_growth ≤ 0.05, beta ≤ 3, dps > 0).
    return DDMInputs(
        dividend_per_share=dps,
        dividend_growth_rates=growth_schedule,
        payout_ratio=payout,
        risk_free_rate=max(0.0, min(0.15, risk_free_rate)),
        beta=beta_final,
        equity_risk_premium=max(0.0, min(0.15, equity_risk_premium)),
        terminal_growth_rate=max(0.0, min(0.05, terminal_growth_rate)),
        terminal_payout_ratio=terminal_payout,
        shares_outstanding=shares,
        current_price=current_price,
        book_value_per_share=book_value_per_share,
        return_on_equity=roe,
        assumption_provenance=prov,
    )
