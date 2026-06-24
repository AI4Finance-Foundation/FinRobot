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
    _BETA_IMPLAUSIBLY_LOW_REASON,
    _BETA_OUT_OF_BAND_REASON,
    _BETA_RELATIVE_FLOOR,
    _BETA_RELATIVE_INDUSTRY_MIN,
    DEFAULT_EQUITY_RISK_PREMIUM,
    DEFAULT_PROJECTION_YEARS,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH,
    _decay_growth_schedule,
    _pick_with_provenance,
)
from finrobot.engine.compute.operators.wacc import adjust_beta_blume
from finrobot.engine.data.industry_defaults import IndustryDefault, get_industry_default
from finrobot.engine.primitives.industry import is_bank
from finrobot.engine.data.normalize.contracts import NormalizedFinancials
from finrobot.engine.models.financial import DDMInputs, FinancialData

# Generic payout used only when the provider reports neither a payout ratio nor
# enough (DPS + positive EPS) to derive one. Market-wide, not per-company, so it
# doesn't violate the "no hardcoded per-company defaults" rule — parallel to
# dcf_seed's 1% ΔNWC fallback.
_DEFAULT_PAYOUT_RATIO: Final[float] = 0.5

# When the provider reports a payout ratio AND the issuer's own DPS/EPS imply one,
# a gap beyond this tolerance means the provider used a different denominator (KO
# 2026-06-24: provider dividendPayoutRatioTTM 80.1% vs DPS $2.08 / EPS $3.18 = 65.3%,
# a 14.8pp gap that understates g = ROE×(1−payout) for low-β payers). Past this we
# trust the self-derived ratio (consistent with the report's own DPS/EPS); banks /
# normal payers agree within it (JPM 1.3pp, PG 0.7pp) and keep the provider value.
_PAYOUT_DISAGREE_TOL: Final[float] = 0.10

# A provider per-share DPS whose implied yield (DPS / price) disagrees with the
# provider's OWN dividend_yield beyond this is a per-ordinary-share vs per-ADR-price
# mismatch (LYG: DPS/price 0.64% vs dividend_yield 3.35%, ~5x — the 1:N ADR ratio the
# per-share field misses but the dimensionless yield carries). Past this, trust the
# caliber-consistent yield × price. Detected on the yield disagreement, NOT a currency
# flag, because by DDM time the snapshot is USD-normalized (reporting == quote == USD).
# Absolute 0.5pp OR 25% relative, whichever larger, so normal payers (yield ≈ DPS/price)
# are unaffected. Bug-3, 2026-06-24.
_ADR_YIELD_DISAGREE_ABS: Final[float] = 0.005
_ADR_YIELD_DISAGREE_REL: Final[float] = 0.25

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
    # Foreign-ADR guard: the provider's per-share DPS is per-ORDINARY-share while
    # current_price is per-ADR (a 1:N ADR ratio the per-share field misses but the
    # dimensionless dividend_yield carries) — LYG's DPS/price implies 0.64% vs the
    # provider's own dividend_yield 3.35%. When the two disagree beyond tolerance, trust
    # the caliber-consistent yield × price (no double-FX: yield is dimensionless, price
    # is the quote-currency per-ADR price). Bug-3, 2026-06-24.
    dps = normalized.dividend_per_share
    div_yield = normalized.dividend_yield
    implied_yield = (
        dps / current_price if (dps is not None and dps > 0 and current_price > 0) else None
    )
    adr_div_mismatch = (
        div_yield is not None
        and 0 < div_yield < 1
        and implied_yield is not None
        and current_price > 0
        and abs(implied_yield - div_yield)
        > max(_ADR_YIELD_DISAGREE_ABS, _ADR_YIELD_DISAGREE_REL * div_yield)
    )
    if adr_div_mismatch and div_yield is not None:
        dps = div_yield * current_price
        prov["dividend_per_share"] = (
            f"${dps:.2f} (per-ADR DPS = provider dividend_yield {div_yield:.2%} × price "
            f"${current_price:.2f}; the per-share DPS implied a {implied_yield:.2%} yield "
            f"— per-ordinary-share vs per-ADR-price mismatch)"
        )
    elif dps is not None and dps > 0:
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
    # Prefer the issuer's OWN DPS/EPS-derived payout when it materially disagrees with
    # the provider's reported ratio (FMP's dividendPayoutRatioTTM uses a different
    # denominator — KO 80.1% vs self-derived 65.3%, a 14.8pp gap, verified live
    # 2026-06-24). An inflated payout understates g = ROE×(1−payout) for low-β dividend
    # payers. The self-derived ratio is the one consistent with the DPS/EPS the same
    # report shows; banks / normal payers agree within tolerance and keep the provider
    # value. Bug-2, 2026-06-24.
    eps = net_income / shares if (net_income is not None and shares > 0) else 0.0
    derived_payout = dps / eps if eps > 0 else None
    provider_payout = normalized.payout_ratio
    if (
        derived_payout is not None
        and provider_payout is not None
        and 0 < provider_payout <= 1
        and abs(provider_payout - derived_payout) > _PAYOUT_DISAGREE_TOL
    ):
        payout = derived_payout
        prov["payout_ratio"] = (
            f"{payout:.1%} (self-derived DPS ${dps:.2f} ÷ EPS ${eps:.2f}; provider "
            f"reported {provider_payout:.1%} but disagrees by "
            f"{abs(provider_payout - derived_payout) * 100:.0f}pp — using the ratio "
            f"self-consistent with this report's DPS/EPS)"
        )
    elif provider_payout is not None and 0 < provider_payout <= 1:
        payout = provider_payout
        prov["payout_ratio"] = f"{payout:.1%} (provider-reported payout ratio)"
    elif derived_payout is not None:
        payout = derived_payout
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
    raw_beta, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider-reported 5y beta",
        industry_value=industry.levered_beta,
        industry_label=f"{industry.industry} industry levered beta",
        floor=_BETA_BAND_FLOOR,
        ceiling=_BETA_BAND_CEILING,
        rejected_ticker_reason=_BETA_OUT_OF_BAND_REASON,
        reject_value_fmt="{:.2f}",
        # Banks only — see dcf_seed: a bank is never a true low-beta defensive, so a
        # sub-0.7×-industry bank beta is vendor noise; every other sector's low beta is
        # real and kept (dcf-recall red line). The DDM/RI is bank-only anyway, but gate
        # explicitly so the shared helper never误伤s a non-bank caller.
        relative_floor=(
            _BETA_RELATIVE_FLOOR
            if is_bank(industry=financials.market.industry, sector=financials.market.sector)
            else None
        ),
        relative_floor_industry_min=_BETA_RELATIVE_INDUSTRY_MIN,
        relative_reject_reason=_BETA_IMPLAUSIBLY_LOW_REASON,
    )
    # Blume asymmetric adjustment, IDENTICAL to dcf_seed — cost of equity is a
    # property of the equity, not the valuation method, so DDM must discount a
    # stock at the SAME beta the DCF uses (lead-adjudicated 2026-06-22; see
    # dcf-recall). adjust_beta_blume is a no-op for β ≤ 1.0, so structurally
    # low-beta defensive payers (utilities/staples — the DDM's bread and butter)
    # are untouched; only a noisy high-β (> 1.0) estimate mean-reverts toward 1.0.
    beta_blumed = adjust_beta_blume(raw_beta)
    # Pre-existing DDM clamp — load-bearing for crash safety: DDMInputs.beta is
    # Field(ge=0, le=3), tighter than DCF's le=5, so a Blume value that still
    # exceeds the cap (e.g. raw 4.8 → 3.53) MUST be capped here or construction
    # raises.
    beta_final = max(_BETA_FLOOR, min(_BETA_CAP, beta_blumed))
    # Provenance discloses the value that actually enters CAPM and which branch
    # produced it — never a false "Blume-adjusted" trail for a β ≤ 1.0 name kept
    # raw (core contract: every number traces to what produced it). Mirrors
    # dcf_seed; out-of-band → industry proxy is already a levered industry beta
    # (no Blume note), and beta_source carries the substitution + rejected raw.
    in_band_ticker = (
        financials.market.beta is not None
        and _BETA_BAND_FLOOR < financials.market.beta <= _BETA_BAND_CEILING
    )
    if not in_band_ticker:
        prov["beta"] = f"{beta_final:.2f} ({beta_source})"
    elif raw_beta > 1.0:
        prov["beta"] = (
            f"{beta_final:.2f} ({beta_source} {raw_beta:.2f}, "
            "Blume-adjusted 2/3·β+1/3·1.0 toward 1.0 — high-β estimate mean-reverts)"
        )
    else:
        prov["beta"] = (
            f"{beta_final:.2f} ({beta_source} {raw_beta:.2f}, "
            "raw regression β — structural low-β defensive, not inflated)"
        )

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
