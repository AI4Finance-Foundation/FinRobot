"""Single authoritative DDMInputs builder — banks and dividend-paying stocks.

What this code does that raw LLM cannot:
- Deterministically derives every DDM assumption from the provider's reported
  dividend / payout / ROE / beta — never lets the LLM "pick" a growth rate from
  a typically-3-8% prompt. Dividend growth is the textbook sustainable growth
  ``g = ROE × (1 − payout)`` decayed to perpetuity — except for buyback-distorted
  franchises (high P/B), where reported ROE is a depleted-book artifact and the
  issuer's own declared-DPS CAGR is the honest growth base instead.
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
    _bank_beta_proxy,
    DEFAULT_EQUITY_RISK_PREMIUM,
    DEFAULT_PROJECTION_YEARS,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH,
    _decay_growth_schedule,
    _pick_with_provenance,
)
from finrobot.engine.compute.operators.wacc import adjust_beta_blume
from finrobot.engine.data.industry_defaults import IndustryDefault, get_industry_default
from finrobot.engine.primitives.dividend import reconcile_per_share_dividend_to_quote_unit
from finrobot.engine.primitives.industry import is_balance_sheet_financial, is_bank
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

# The ADR per-ordinary vs per-ADR DPS reconciliation now lives in
# ``primitives.dividend.reconcile_per_share_dividend_to_quote_unit`` — one authority
# shared with the canonical FX normalize (which applies it to the DISPLAYED DPS too).

# Sustainable dividend growth is clamped to this ceiling before decay — beyond
# it the Gordon multi-stage convergence stops being meaningful.
_MAX_SUSTAINABLE_GROWTH: Final[float] = 0.40

# Above this price-to-book, ROE = earnings / book is a depleted-denominator
# artifact (buyback franchises trade at 6-500× book — KO ~10x, CL ~500x), so the
# textbook sustainable growth g = ROE × (1 − payout) overstates dividend growth
# (KO 15% vs its actual ~4.5% DPS CAGR). Past this band we grow the dividend at
# the company's own declared-DPS CAGR instead. 4.0× cleanly separates the
# distorted staples (live 2026-07-02: KO 10.5 / PG 6.5 / JNJ 7.6 / PEP 9.2 / CL
# 519, all > 4) from names whose book is a real capital base (banks 1.5-2.6,
# utilities 1.7-2.9, energy 2.2 — all < 4, kept on ROE×(1−payout) unchanged).
_PB_DISTORTION_THRESHOLD: Final[float] = 4.0

# CAPM beta clamp — same band dcf_seed uses, tighter than the DDMInputs Field
# ceiling (≤ 3) so an outlier provider beta can't blow up cost of equity.
_BETA_FLOOR: Final[float] = 0.3
_BETA_CAP: Final[float] = 2.5


def _dps_cagr(annual_dps: dict[str, float] | None, *, max_window: int = 5) -> float | None:
    """Compound annual dividend growth from a declared-DPS-per-year map.

    ``annual_dps`` is the FMP DIVIDENDS payload (``{"YYYY": total_dps}``, string
    keys from JSON). Robust to the current incomplete calendar year — its partial
    total falls below the prior full year (dividends are sticky for a going
    concern, never materially cut), so a trailing year below 99% of its
    predecessor is dropped. Uses up to ``max_window`` year-over-year steps (a 5y
    look-back, the sell-side standard for a dividend-growth rate). Returns None
    when there isn't enough positive history (< 2 full years) to compute a rate.
    """
    if not annual_dps:
        return None
    try:
        by_year = {int(y): float(v) for y, v in annual_dps.items() if v is not None}
    except (TypeError, ValueError):
        return None
    series = [(y, by_year[y]) for y in sorted(by_year) if by_year[y] > 0]
    if len(series) < 2:
        return None
    if series[-1][1] < 0.99 * series[-2][1]:
        series = series[:-1]  # trailing partial (mid-year) total — drop it
    if len(series) < 2:
        return None
    window = series[-(max_window + 1) :]
    # Span the actual calendar years, not the point count — robust to a missing
    # year in the record (a gap must not be compounded as a single step).
    n = window[-1][0] - window[0][0]
    start, end = window[0][1], window[-1][1]
    if n <= 0 or start <= 0 or end <= 0:
        return None
    return float((end / start) ** (1.0 / n) - 1.0)


def seed_ddm_inputs(
    financials: FinancialData,
    normalized: NormalizedFinancials,
    *,
    dividend_history: dict[str, float] | None = None,
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

    ``dividend_history`` (optional) is the DIVIDENDS payload's ``annual_dps`` map
    ({"YYYY": total_dps}); it supplies the declared-DPS CAGR used as the growth
    base for buyback-distorted franchises (high P/B). None ⇒ the growth stays on
    the book-based ``g = ROE × (1 − payout)`` (banks, utilities — reasonable P/B).

    Field derivation:
      - dividend_per_share: provider DPS → payout × net_income / shares.
      - payout_ratio: provider → DPS / EPS → generic 50%.
      - dividend_growth_rates: for a reasonable-P/B name, sustainable
        ``g = ROE × (1 − payout)`` clamped to [0, 40%]; for a buyback-distorted
        name (P/B > threshold or non-positive book) the declared-DPS CAGR (book
        value no longer reflects reinvested capital). Linearly decayed to
        ``terminal_growth_rate``. ROE missing and no DPS history ⇒ generic start.
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
    # Foreign-ADR guard (single authority = primitives.dividend): the provider's
    # per-share DPS is per-ORDINARY-share while current_price is per-ADR — reconcile to
    # the per-ADR quote unit via the dimensionless yield × price. Idempotent: by DDM
    # time the canonical snapshot is usually already reconciled (currency normalize),
    # so this typically no-ops; it stays as the compute-side guard for any snapshot
    # that reached here unreconciled.
    div_yield = normalized.dividend_yield
    reconciled_dps, adr_note = reconcile_per_share_dividend_to_quote_unit(
        normalized.dividend_per_share, div_yield, current_price
    )
    dps: float
    if adr_note is not None and reconciled_dps is not None and div_yield is not None:
        dps = reconciled_dps
        prov["dividend_per_share"] = (
            f"${dps:.2f} (per-ADR DPS = provider dividend_yield {div_yield:.2%} × price "
            f"${current_price:.2f}; the per-share DPS was on the per-ordinary caliber)"
        )
    elif reconciled_dps is not None and reconciled_dps > 0:
        dps = reconciled_dps
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
    #
    # BUT g = ROE × (1 − payout) is only meaningful when book value ≈ invested
    # capital. A buyback-distorted franchise (KO/CL: decades of repurchases shrink
    # book to a sliver, so reported ROE = earnings / tiny-book runs 40%+ and P/B
    # 6-500×; the retained earnings fund MORE buybacks, not book growth) makes the
    # formula overstate dividend growth badly (KO 15% vs its actual ~4.5% DPS
    # CAGR — the +60% DDM garbage-in). When book is distorted (P/B above the
    # threshold, or non-positive), grow the dividend at the company's OWN declared
    # -DPS CAGR (board-managed, the honest and traceable measure); ROE×(1−payout)
    # is kept only inside a reasonable P/B band (banks / utilities / energy, where
    # book is a real capital base). Live 2026-07-02: gate flips only distorted
    # staples (KO/PG/CL/JNJ/PEP/MO); banks & utilities stay byte-identical.
    roe = normalized.return_on_equity
    book_value_per_share = normalized.book_value_per_share
    dps_cagr = _dps_cagr(dividend_history)
    book_distorted = (
        book_value_per_share is None
        or book_value_per_share <= 0
        or (current_price > 0 and current_price / book_value_per_share > _PB_DISTORTION_THRESHOLD)
    )
    if book_distorted and dps_cagr is not None:
        g = max(0.0, min(_MAX_SUSTAINABLE_GROWTH, dps_cagr))
        distortion = (
            f"P/B {current_price / book_value_per_share:.1f}x"
            if (book_value_per_share is not None and book_value_per_share > 0)
            else "non-positive book value"
        )
        growth_source = (
            f"dividend growth g = {g:.1%} (declared-DPS CAGR from the issuer's own "
            f"dividend record; ROE×(1−payout) not used — {distortion} means book value "
            f"is buyback-depleted and overstates reinvestment growth)"
        )
    elif book_distorted:
        # Distorted book but no usable dividend history: ROE×(1−payout) is
        # unreliable and the DPS record is unavailable → degrade to long-run
        # nominal growth (disclosed), never the overstated book-based rate.
        g = terminal_growth_rate
        growth_source = (
            f"dividend growth held at long-run nominal {g:.1%} (book value distorted, so "
            f"ROE×(1−payout) is unreliable, and the dividend-growth history is unavailable)"
        )
    elif roe is not None and roe > 0:
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
    #
    # GATED to balance-sheet financials. The terminal-payout step-up (calculate_ddm
    # step 4) was built to correct the naive DDM that "values a 28%-payout, 16% ROE
    # bank like JPM at a third of price": a bank (Basel capital) / insurer (reserves)
    # genuinely retains earnings on a LOW trailing payout to build its balance sheet,
    # then pays out (1 − g/ROE) as DIVIDENDS at maturity — the step-up models that
    # transition. A NON-financial's low payout is NOT retained-for-future-dividends:
    # it is reinvestment OR buyback-based capital return (AAPL pays 12.7% in dividends
    # and returns ~90% via buyback), so stepping its terminal DIVIDEND payout up to
    # ~98% recaptures buyback cash as future dividends and values AAPL's dividend
    # stream at $443 > its price. A dividend-discount model must not do that — hold
    # payout constant (naive Gordon) so the honest read survives: "the dividend stream
    # alone is worth far less than the price" ($80, not $443). High-payout non-financials
    # (KO/PG) are barely affected — their step-up was already ≈1. The step-up leaking to
    # all tickers (not just balance-sheet financials, its design domain) was the bug.
    # (2026-06-26 basket probe: gating restores JPM/BAC/WFC/C byte-for-byte and fixes
    # AAPL/MSFT/GOOGL; see calculate_ddm step 4.)
    balance_sheet_financial = is_balance_sheet_financial(
        industry=financials.market.industry, sector=financials.market.sector
    )
    if balance_sheet_financial and roe is not None and roe > terminal_growth_rate:
        terminal_payout: float | None = max(payout, min(1.0, 1 - terminal_growth_rate / roe))
        prov["terminal_payout_ratio"] = (
            f"{terminal_payout:.1%} (terminal payout ratio = 1 − terminal growth {terminal_growth_rate:.1%} / "
            f"ROE {roe:.1%}; balance-sheet financial — payout matures toward sustainable level)"
        )
    elif balance_sheet_financial:
        terminal_payout = None
        prov["terminal_payout_ratio"] = (
            "payout ratio held constant in perpetuity (ROE unavailable; cannot normalize terminal payout)"
        )
    else:
        terminal_payout = None
        prov["terminal_payout_ratio"] = (
            "payout ratio held constant in perpetuity (non-financial — capital returned via "
            "reinvestment/buyback is not future dividends; the terminal-payout step-up "
            "applies only to balance-sheet financials)"
        )

    # ----- beta (CAPM) -------------------------------------------------------
    bank_issuer = is_bank(industry=financials.market.industry, sector=financials.market.sector)
    beta_proxy, beta_proxy_label = _bank_beta_proxy(industry, is_bank_issuer=bank_issuer)
    raw_beta, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider-reported 5y beta",
        industry_value=beta_proxy,
        industry_label=beta_proxy_label,
        floor=_BETA_BAND_FLOOR,
        ceiling=_BETA_BAND_CEILING,
        rejected_ticker_reason=_BETA_OUT_OF_BAND_REASON,
        reject_value_fmt="{:.2f}",
        # Banks only — see dcf_seed: a bank is never a true low-beta defensive, so a
        # sub-0.7×-industry bank beta is vendor noise; every other sector's low beta is
        # real and kept (dcf-recall red line). The DDM/RI is bank-only anyway, but gate
        # explicitly so the shared helper never误伤s a non-bank caller.
        relative_floor=_BETA_RELATIVE_FLOOR if bank_issuer else None,
        relative_floor_industry_min=_BETA_RELATIVE_INDUSTRY_MIN,
        relative_reject_reason=_BETA_IMPLAUSIBLY_LOW_REASON,
    )
    # Blume asymmetric adjustment, IDENTICAL to dcf_seed — cost of equity is a
    # property of the equity, not the valuation method, so DDM must discount a
    # stock at the SAME beta the DCF uses (lead-adjudicated 2026-06-22; see
    # dcf-recall). adjust_beta_blume is a no-op for β ≤ 1.0, so structurally
    # low-beta defensive payers (utilities/staples — the DDM's bread and butter)
    # are untouched; only a noisy high-β (> 1.0) estimate mean-reverts toward 1.0.
    used_provider_beta = beta_source == "provider-reported 5y beta"
    beta_blumed = adjust_beta_blume(raw_beta) if used_provider_beta else raw_beta
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
    if not used_provider_beta:
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
