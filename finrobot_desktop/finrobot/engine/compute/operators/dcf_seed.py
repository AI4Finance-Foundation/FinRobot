"""Single authoritative DCFInputs builder.

What this code does that raw LLM cannot:
- Deterministically derives every DCF assumption from real multi-year filings
  (historical medians over the most recent ``_MEDIAN_WINDOW_YEARS`` years) or
  Damodaran industry medians — never hardcoded per-company defaults.
- Records the *source* of each assumption in ``assumption_provenance`` so the
  UI can render "EBITDA 利润率 31.4%，过去 3 年财报中位数" instead of an
  opaque number. The "N 年" in that label is the *actual* sample count used,
  not a hardcoded window — a ticker with only 2 years of filings shows
  "过去 2 年" so the provenance never overstates the data behind a number.
- Falls back through a fixed precedence: ticker history → industry median →
  Total Market median. Never returns None / placeholder.

This module is the only sanctioned producer of DCFInputs in the codebase.
Routes / pipelines / SDK should call ``seed_dcf_inputs``; the legacy
``DEFAULT_COMPUTE_BODY`` and ``DEFAULT_INPUTS`` are being removed.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Final

from finrobot.engine.compute.operators.wacc import adjust_beta_blume
from finrobot.engine.primitives.industry import commodity_cyclical_basis, is_bank
from finrobot.engine.data.industry_defaults import (
    IndustryDefault,
    get_industry_default,
)
from finrobot.engine.models.financial import (
    DCFInputs,
    FinancialData,
    HistoricalMetrics,
)

# Defaults sourced from public macro data — refreshed at each Damodaran update.
# These are the *only* hardcoded constants in the seed pipeline and they apply
# market-wide (not per-company), so they don't violate the "no hardcoded
# per-company defaults" rule.
DEFAULT_RISK_FREE_RATE: Final[float] = 0.043  # 10Y Treasury, 2026-01
# Damodaran implied ERP, Jan 1 2026 (S&P 6845.5, implied return 8.41%, T-bond
# 4.18% → ERP 4.23%). The previous 5.5% was ~127bp above the actual implied
# premium and systematically inflated every WACC ~120bp, pushing fair value to
# 25–55% of market across the mega-caps. Source: pages.stern.nyu.edu Data 2026.
DEFAULT_EQUITY_RISK_PREMIUM: Final[float] = 0.0423
# Perpetuity growth — a defensible long-run rate BELOW the risk-free ceiling
# (Damodaran caps terminal growth at the risk-free rate). 3.0% ≈ long-run
# inflation plus a modest real sliver; the sell-side base case for mega-cap
# compounders (e.g. MSFT) uses 2.5–3.0%. The old 2.5% was labelled "nominal GDP"
# but is closer to REAL GDP, biasing the Gordon terminal value low.
DEFAULT_TERMINAL_GROWTH: Final[float] = 0.030
DEFAULT_TAX_RATE: Final[float] = 0.21  # US corporate statutory
# Two-stage 10y explicit window — the sell-side standard for growth compounders.
# A 5y window truncated the growth runway and jumped to the terminal rate too
# early, compounding the lowball for exactly the high-growth names.
DEFAULT_PROJECTION_YEARS: Final[int] = 10
DEFAULT_COST_OF_DEBT: Final[float] = 0.05  # Investment-grade corporate yield
# Explicit-window revenue-growth bounds, shared by the trailing-CAGR and the
# forward-consensus seed paths. Floor −20%/yr (severe-but-bounded decline); cap
# +40%/yr (no firm compounds revenue faster than this for a decade, so even a
# euphoric consensus FY1 is clamped before it inflates the explicit window).
_GROWTH_CAP: Final[float] = 0.40
_GROWTH_FLOOR: Final[float] = -0.20

# Effective cost-of-debt is clamped into this band: below it the rate is
# rounding noise (sub-1% interest on a large debt balance), above it the implied
# yield signals a one-off (default/restructuring) rather than the run-rate.
# Clamping is logged + flagged in provenance so it's never silent (BUG-023).
COST_OF_DEBT_FLOOR: Final[float] = 0.02
COST_OF_DEBT_CAP: Final[float] = 0.20

# Company effective tax rate is accepted only inside [floor, cap]. Outside the
# band the implied rate is a one-off item (a large credit/benefit pushing it
# below 0, or a settlement/valuation-allowance year pushing it above the cap)
# rather than the sustainable run-rate, so the DCF falls back to the industry
# median. The rejection + the rejected raw rate are disclosed in provenance so
# the substitution that shapes the tax shield is never silent — same honesty
# convention as the cost-of-debt clamp (BUG-023) and the comps tax rate (BUG-049).
TAX_RATE_OUTLIER_FLOOR: Final[float] = 0.0
TAX_RATE_OUTLIER_CAP: Final[float] = 0.45

# After the company-vs-industry choice, the rate fed to the DCF is clamped into
# this modelling band: below the floor the tax shield is implausibly generous for
# a going concern, above the cap it is a distressed/one-off level no sustainable
# operation pays. This is the rate the DCF ACTUALLY uses, so the provenance must
# be built from the post-clamp value and disclose the floor/cap when it binds —
# otherwise a 42% company rate prints as "42%" while the DCF discounts at 40%
# (the displayed≠used audit-trail corruption this module must never ship).
DCF_TAX_RATE_FLOOR: Final[float] = 0.05
DCF_TAX_RATE_CAP: Final[float] = 0.40

# Economically possible band for a provider-reported equity beta. Anything outside
# it is a vendor short-window glitch, not a real systematic-risk reading, so it is
# rejected in favour of the Damodaran industry levered beta proxy (with disclosed
# provenance). Lower bound is exclusive (a non-positive beta means a stock that
# rallies in recessions — impossible for any going concern, and SHEL/BP/EQNR's
# −0.25/−0.24/−0.75 are a whole sector compressed by a shared upstream feed). Upper
# bound 5.0 rejects feed spikes that would otherwise produce an absurd CAPM cost of
# equity. Genuine low-β defensives (KO 0.354, VZ 0.22) and high-β names (NVDA 2.20,
# MU 2.17) sit INSIDE the band and keep their raw provider value. Shared by the DCF
# and DDM WACC seeds so both judge beta identically.
_BETA_BAND_FLOOR: Final[float] = 0.0
_BETA_BAND_CEILING: Final[float] = 5.0
_BETA_OUT_OF_BAND_REASON: Final[str] = (
    "outside the economically possible beta band [0, 5] (vendor short-window glitch); "
    "using the industry levered-beta proxy"
)
# Industry-relative beta sanity (NOT an absolute floor — see _pick_with_provenance):
# a ticker beta below 70% of a normal-magnitude industry levered beta is a vendor
# short-window regression artifact. Gated on the industry beta itself being ≥ 0.8 so
# genuinely low-beta sectors (utilities/staples, industry β well below 0.8) are
# structurally exempt and never误伤ed. Catches MTB (β 0.59 versus a bank beta
# proxy floored to a normal-magnitude market comparator).
_BETA_RELATIVE_FLOOR: Final[float] = 0.7
_BETA_RELATIVE_INDUSTRY_MIN: Final[float] = 0.8
_BETA_IMPLAUSIBLY_LOW_REASON: Final[str] = (
    "is implausibly low versus the industry levered beta (a short-window vendor "
    "regression artifact for a non-defensive sector); using the industry proxy"
)

# Minimum historical samples required before we trust the ticker's own median.
# Fewer than this ⇒ fall back to industry median. This is purely a THRESHOLD;
# it does NOT bound how many years feed the median (that is _MEDIAN_WINDOW_YEARS).
_MIN_HISTORY_SAMPLES: Final[int] = 2

# How many of the most recent fiscal years feed each historical median. The
# extractor pulls 5 years, but equity-research convention seeds off the trailing
# ~3y so the number reflects the current regime rather than a stale half-decade.
# Separate from _MIN_HISTORY_SAMPLES: a ticker with only 2 years of data still
# passes the threshold and yields a 2-sample median sliced from this 3y window —
# the provenance then honestly reports the real count (2), never the window (3).
_MEDIAN_WINDOW_YEARS: Final[int] = 3

# THROUGH-CYCLE window for commodity-cyclicals (Damodaran cyclical normalization):
# the earnings base must be the median across a FULL peak→trough→recovery cycle,
# NOT the trailing-3y regime (which for memory is whichever phase the cycle is in
# now). The extractor pulls 10y for cyclicals (_CYCLICAL_HISTORY_YEARS); this
# window is ≥ that so the median takes EVERY available year. Larger than the fetch
# is intentional — a short-history cyclical (SNDK: 1y) just yields a small-N median
# whose real count provenance reports, never the nominal window.
_CYCLICAL_MEDIAN_WINDOW_YEARS: Final[int] = 12

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — each isolated so it can be tested independently
# ---------------------------------------------------------------------------


def _median_ratio(
    numerator: list[float],
    denominator: list[float],
    *,
    window: int = _MEDIAN_WINDOW_YEARS,
    min_samples: int = _MIN_HISTORY_SAMPLES,
) -> tuple[float, int] | None:
    """Median of numerator[i]/denominator[i] over the last *window* years.

    ``window`` bounds how many recent years are sliced for the median; it is
    *separate* from ``min_samples``, the minimum paired count below which we
    don't trust the ticker's own history and the caller falls back to the
    industry median. A short history (e.g. 2 years) sliced [-3:] still yields
    only 2 points — the returned count reflects that real number, never the
    window, so provenance never overstates the data behind the figure.

    Returns ``(median, count)`` where ``count`` is the number of usable paired
    samples that actually fed the median, or None when:
      - the paired history is shorter than ``min_samples``
      - denominator has zeros in the recent window (would div by 0)
      - all paired ratios are 0 (cashflow row was zero-filled by extractor)

    Takes the most recent window since trailing ratios drift; for a stable seed
    we use the last ``window`` years.
    """
    n = min(len(numerator), len(denominator))
    if n < min_samples:
        return None
    # Take the most recent window
    nums = numerator[-window:]
    dens = denominator[-window:]
    ratios: list[float] = []
    for num, den in zip(nums, dens):
        # Skip NaN in either operand — they come from partially-NaN cashflow rows
        # that survived the income-statement column filter.
        if math.isnan(num) or math.isnan(den):
            continue
        if den == 0:
            return None
        if num == 0 and den != 0:
            # Treat all-zero numerator as "row missing in cashflow stmt";
            # if even one sample is non-zero we'll include it.
            continue
        ratios.append(num / den)
    if not ratios:
        return None
    return statistics.median(ratios), len(ratios)


def _weighted_ratio(
    numerator: list[float],
    denominator: list[float],
    *,
    window: int,
    min_samples: int = _MIN_HISTORY_SAMPLES,
) -> tuple[float, int] | None:
    """Revenue-WEIGHTED ratio Σnum / Σden over the last *window* years.

    For a cyclical's D&A / revenue: D&A is a sticky stock that lags revenue, so
    D&A/revenue SPIKES at the trough (MU FY2023 49.9% only because revenue
    collapsed). A simple median of per-year ratios over-weights that trough
    artifact; the revenue-weighted ratio (Σ D&A / Σ revenue) instead reflects the
    steady-state reinvestment intensity across the cycle (MU → ~24%). Same NaN /
    zero-row hygiene as ``_median_ratio``.

    Returns ``(weighted_ratio, count)`` over the usable paired years, or None when
    fewer than ``min_samples`` usable pairs exist or the revenue sum is non-positive.
    """
    n = min(len(numerator), len(denominator))
    if n < min_samples:
        return None
    nums = numerator[-window:]
    dens = denominator[-window:]
    num_sum = 0.0
    den_sum = 0.0
    count = 0
    for num, den in zip(nums, dens):
        if math.isnan(num) or math.isnan(den):
            continue
        if den <= 0:
            continue
        if num == 0:
            # An all-zero row is a missing cash-flow line (extractor convention),
            # not a real 0 — skip so it doesn't dilute the weighted ratio.
            continue
        num_sum += num
        den_sum += den
        count += 1
    if count < min_samples or den_sum <= 0:
        return None
    return num_sum / den_sum, count


def _decay_growth_schedule(
    base_growth: float,
    terminal_growth: float,
    years: int,
) -> list[float]:
    """Linear decay from base_growth → terminal_growth over *years* steps.

    Year 1 starts at base_growth; year N lands exactly at terminal_growth.
    Captures the standard equity-research convention that high-growth firms
    converge to nominal-GDP growth over the explicit forecast window — without
    requiring the LLM to invent a curve.

    Mature-firm edge case: when base_growth ≤ terminal_growth (e.g. AAPL's
    recent 4y CAGR of ~2%), we *don't* artificially boost the schedule up to
    GDP. We hold base_growth flat for the explicit window; the Gordon-growth
    perpetuity (terminal_growth_rate field) handles the eventual catch-up.
    """
    if base_growth <= terminal_growth:
        return [base_growth] * years
    if years <= 1:
        return [base_growth]
    step = (base_growth - terminal_growth) / (years - 1)
    return [base_growth - step * i for i in range(years)]


def _cost_of_debt(
    interest_expense: float | None,
    total_debt: float | None,
    *,
    floor: float = COST_OF_DEBT_FLOOR,
    cap: float = COST_OF_DEBT_CAP,
) -> float | None:
    """Effective cost of debt = interest expense / total debt, clamped to [floor, cap].

    Returns None when interest_expense or total_debt is missing, or total_debt
    is too small to yield a meaningful rate (sub-1% of equity ⇒ rounding noise).
    When the raw rate is clamped, logs a warning so the substitution is never
    silent — the DCF caller additionally marks it in ``assumption_provenance``
    (BUG-023).
    """
    if interest_expense is None or total_debt is None or total_debt <= 0:
        return None
    rate = interest_expense / total_debt
    if rate < floor:
        logger.warning(
            "Cost of debt %.2f%% below floor — clamped to %.1f%% (interest=%.3g / debt=%.3g)",
            rate * 100,
            floor * 100,
            interest_expense,
            total_debt,
        )
        return floor
    if rate > cap:
        logger.warning(
            "Cost of debt %.1f%% above cap — clamped to %.1f%% (interest=%.3g / debt=%.3g)",
            rate * 100,
            cap * 100,
            interest_expense,
            total_debt,
        )
        return cap
    return rate


def _effective_tax_rate(income_tax_expense: float | None, net_income: float | None) -> float | None:
    """Company effective tax rate = tax_expense / pretax, pretax = NI + tax_expense.

    Returns None when the inputs can't yield a meaningful run-rate:
      - either line is missing,
      - pretax ≤ 0 (a loss year makes the ratio meaningless),
      - the implied rate is outside [0%, 45%] — a sign of a one-off tax item
        (large credit/benefit or settlement) rather than the sustainable rate.
    The caller falls back to the industry effective rate in those cases.
    """
    if income_tax_expense is None or net_income is None:
        return None
    pretax = net_income + income_tax_expense
    if pretax <= 0:
        return None
    rate = income_tax_expense / pretax
    if rate < TAX_RATE_OUTLIER_FLOOR or rate > TAX_RATE_OUTLIER_CAP:
        return None
    return rate


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def seed_dcf_inputs(
    financials: FinancialData,
    historical: HistoricalMetrics,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
    terminal_growth_rate: float = DEFAULT_TERMINAL_GROWTH,
    projection_years: int = DEFAULT_PROJECTION_YEARS,
    forward_growth: list[float] | None = None,
    cyclical: bool = False,
) -> DCFInputs:
    """Build a complete DCFInputs from one ticker's financials + historical data.

    Field-by-field precedence:
      ticker historical median (most recent _MEDIAN_WINDOW_YEARS, default 3y) →
      industry median (Damodaran) → market median

    Every field gets an entry in ``assumption_provenance`` so the UI can show
    a 散户-friendly Chinese sentence explaining where the number came from.

    Args:
        financials: Latest snapshot (LTM revenue, EBITDA, debt, cash, shares).
        historical: Multi-year history (extracted by historical_extractor).
        risk_free_rate: 10Y Treasury yield. Default static; caller can pass a
            live rate when available.
        equity_risk_premium: Market risk premium. Default Damodaran 2026 ERP.
        terminal_growth_rate: Perpetuity growth. Default US nominal GDP.
        projection_years: Length of explicit forecast schedule. Default 10
            (DEFAULT_PROJECTION_YEARS — the two-stage sell-side window).
        forward_growth: Analyst-consensus YoY revenue-growth path for the first
            few explicit years (from forward_estimates.get_forward_revenue_growth).
            When it carries any finite point it SEEDS the explicit window (non-
            finite points dropped, then clamped to the shared floor/cap and
            decayed to terminal) IN PLACE OF the trailing CAGR — a backward-
            looking CAGR otherwise ignores a consensus re-acceleration the rest
            of the pipeline already fetched (the AAPL 3.3%-vs-+14.9% gap).
            None / empty / all-non-finite → trailing-CAGR seeding, unchanged.
        cyclical: True for a commodity / deep-cyclical (memory, steel, shipping,
            oil&gas E&P…) — computed upstream by ``is_commodity_cyclical`` and
            threaded through by the coordinator/pipeline. Switches the EARNINGS
            BASE to a THROUGH-CYCLE normalization (Damodaran cyclical口径): the
            EBITDA margin, explicit-window CapEx% and D&A% are taken across the
            FULL cycle window (not the trailing 3y), so the DCF anchors on a
            normalized through-cycle earnings power rather than whatever phase the
            cycle is in now. ``revenue_base`` is DELIBERATELY left at the current
            TTM — Damodaran applies the normalized MARGIN to CURRENT revenue; re-
            basing revenue too would double-count the cycle phase. This is also why
            the base must stay TTM for a cyclical mid-ramp (MU: TTM run-rate ~$90B is
            far above the last completed FY ~$37B) — anchoring on the stale FY and
            applying the growth-capped consensus would project Year 1 BELOW the current
            run-rate. False is the unchanged trailing-3y path for every non-cyclical
            (KO逐位 identical).

    Returns:
        DCFInputs ready to pass to ``calculate_dcf``. The ``da_pct_revenue``
        field is *always* non-None — industry fallback guarantees it.
    """
    industry: IndustryDefault = get_industry_default(financials.market.industry)
    prov: dict[str, str] = {}

    # Through-cycle window for a cyclical (full peak→trough→recovery), trailing-3y
    # for everyone else. Drives the EBITDA-margin / CapEx% / D&A% medians below; the
    # WACC / tax / growth derivation is regime-current for both (the cycle position
    # doesn't change the discount rate). _CYCLICAL_MEDIAN_WINDOW_YEARS ≥ the 10y
    # cyclical fetch so the median sees every available year.
    earnings_window = _CYCLICAL_MEDIAN_WINDOW_YEARS if cyclical else _MEDIAN_WINDOW_YEARS
    # Provenance must state the REAL window, never a template "完整周期" claim. With
    # SEC deep history MU genuinely spans FY2017-25 (peak FY2018 / trough FY2023), but
    # a short-history cyclical (SEC unwired, or a recent IPO) does NOT — so the claim
    # is gated on the actual coverage the windowed margin series shows.
    _cycle_note: str | None = None
    if cyclical:
        _cyc_n, _cyc_full, _cyc_peak_fy, _cyc_trough_fy = _cycle_coverage(
            historical.years, historical.operating_margin, window=earnings_window
        )
        if _cyc_full:
            _cycle_note = (
                f"through-cycle median ({_cyc_n}yr covering a full cycle: "
                f"peak FY{_cyc_peak_fy} / trough FY{_cyc_trough_fy})"
            )
            _coverage_cn = f"{_cyc_n}yr window covers a full peak→trough→recovery cycle (peak FY{_cyc_peak_fy} / trough FY{_cyc_trough_fy})"
        elif _cyc_n > 0:
            # Honest about a truncated window — name what we actually have, don't
            # claim a full cycle the data can't support.
            _cycle_note = (
                f"through-cycle median (only {_cyc_n}yr; window may not cover a full cycle: "
                f"peak FY{_cyc_peak_fy} / trough FY{_cyc_trough_fy})"
            )
            _coverage_cn = (
                f"window only {_cyc_n}yr; may not cover a full cycle "
                f"(available: peak FY{_cyc_peak_fy} / trough FY{_cyc_trough_fy})"
            )
        else:
            _cycle_note = (
                "through-cycle median (insufficient history; fell back to industry benchmark)"
            )
            _coverage_cn = "insufficient history; cannot construct a through-cycle window"
        # Name the REAL arm that fired — an auto OEM (TSLA/F/GM) hits the industry
        # whitelist, NOT the memory/storage keyword; claiming "memory/storage 命中"
        # for it is fabricated provenance, and downstream the memory-supercycle
        # narrative (审校修正 1) gates on this exact substring.
        _arm_cn = (
            "industry whitelist hit: steel / shipping / chemicals / oil & gas / autos and other commodity cyclicals"
            if commodity_cyclical_basis(financials.market.industry) == "industry"
            else "memory/storage whitelist / keyword hit"
        )
        prov["cyclical_normalization"] = (
            f"Classified as a commodity-cyclical ({_arm_cn}) → earnings base uses "
            "through-cycle normalization: EBITDA margin = through-cycle median, D&A = revenue-weighted through-cycle, "
            f"explicit-window CapEx = through-cycle median; {_coverage_cn}; "
            "revenue base held at current TTM (Damodaran convention 3: normalized margin × current revenue; "
            "revenue is not re-based, to avoid double-counting the cycle phase)."
        )

    # ----- revenue_base ------------------------------------------------------
    # The base is the CURRENT run-rate (TTM by default) — Year 1 is projected off
    # it. Keeping the base at the current revenue is what anchors the DCF to today's
    # earnings power (and is the Damodaran cyclical convention: normalized margin ×
    # current revenue). It does NOT mean the FY-over-FY consensus rate rides TTM raw —
    # that would double-count the current fiscal year's realized stub; the consensus
    # branch below restates Year-1 growth to NTM caliber so Year 1 still lands on the
    # FY1 estimate. Label the basis HONESTLY: mislabeling TTM as "annual" is exactly
    # the口径 error the project forbids. Read the actual basis from provenance.
    revenue_base = financials.income.revenue
    _basis = financials.provenance.period_basis if financials.provenance else "ttm"
    _basis_cn = {
        "ttm": "latest TTM revenue (trailing 12 months)",
        "annual": "latest annual revenue",
        "quarterly": "latest quarterly revenue (annualized)",
    }.get(_basis, f"latest revenue ({_basis})")
    prov["revenue_base"] = _basis_cn

    # ----- revenue_growth_rates ---------------------------------------------
    # cagr_revenue is None when: fewer than 2 data points, start revenue ≤ 0,
    # or NaN pollution from yfinance. math.isfinite guards the NaN/Inf case.
    cagr = historical.cagr_revenue
    has_real_cagr = cagr is not None and math.isfinite(cagr)
    # Drop non-finite consensus points (NaN/Inf) before they can poison the
    # schedule: max()/min() pass NaN straight through (unlike _median_ratio,
    # which filters it), so a single NaN would survive the clamp into
    # revenue_growth_rates and make calculate_dcf return implied_price NaN.
    # seed_dcf_inputs is the single authoritative builder — it must not assume
    # the caller pre-cleaned the path. An all-non-finite list collapses to empty
    # and falls through to trailing-CAGR seeding.
    consensus = [g for g in forward_growth if math.isfinite(g)] if forward_growth else []
    if consensus:
        # Analyst consensus drives the explicit window. The consensus rates are
        # FY-over-FY (FY1/last-actual-FY − 1, FY2/FY1 − 1, …), but revenue_base is the
        # current TTM run-rate, which already contains this fiscal year's realized stub.
        # Applying the raw FY1 rate to TTM double-counts that stub: AAPL FY26 consensus
        # revenue $478B on a $416B last FY is +14.9%, yet 14.9% × TTM $451B = $519B
        # (+8.5% over consensus), printing the false FY25→Y1 +24.7% cliff in the
        # financial chapter. Restate ONLY Year 1 to NTM caliber — the growth from the
        # current TTM run-rate to the FY1 CONSENSUS LEVEL (last_FY × (1 + g[0])) — so
        # Year 1 lands on the FY1 estimate. Years 2+ stay native FY-over-FY: once Year 1
        # sits at the FY1 level, FY2/FY1 chains correctly. The NTM restatement is ALSO
        # what keeps a mid-ramp hyper-grower sane — when FY1/TTM exceeds the cap (MU
        # memory super-cycle, FY1 ~$129B on a ~$90B TTM run-rate), the capped NTM rate
        # holds Year 1 just above the current run-rate, NOT the last-FY × capped-rate
        # collapse BELOW it (last FY ~$37B × 1.40 = $52B ≪ the $90B run-rate). Needs the
        # last actual FY as the consensus anchor; without history the raw rate rides TTM.
        seed_rates = list(consensus[:projection_years])
        _last_annual = historical.revenue[-1] if historical.revenue else None
        _ntm_restated = (
            _last_annual is not None
            and math.isfinite(_last_annual)
            and _last_annual > 0
            and revenue_base > 0
        )
        if _ntm_restated:
            assert _last_annual is not None  # narrowing for mypy
            fy1_level = _last_annual * (1 + seed_rates[0])
            seed_rates[0] = fy1_level / revenue_base - 1
        # Clamp each explicit year to the shared floor/cap, then decay the tail from the
        # last consensus year down to terminal — don't extrapolate a finite-horizon
        # estimate forever, and don't fabricate a rise when the last consensus year is
        # already ≤ terminal (mature: hold flat, Gordon perpetuity does the rest).
        explicit = [max(min(g, _GROWTH_CAP), _GROWTH_FLOOR) for g in seed_rates]
        # Honest consensus count = what actually survived the slice, NOT the raw
        # input length. When consensus is longer than projection_years the tail
        # years are dropped here, so provenance must not claim them (e.g. a 12y
        # consensus into a 10y window is "FY1-10", never "FY1-12").
        n_consensus = len(explicit)
        remaining = projection_years - len(explicit)
        tail_start = explicit[-1]
        if remaining > 0 and tail_start > terminal_growth_rate:
            step = (tail_start - terminal_growth_rate) / remaining
            explicit += [tail_start - step * (i + 1) for i in range(remaining)]
        elif remaining > 0:
            explicit += [tail_start] * remaining
        growth_schedule = explicit
        # Provenance shows the ACTUAL consensus rates (FY-over-FY), then discloses the
        # Year-1 NTM restatement so the seeded schedule[0] never looks like a mystery
        # rate divorced from consensus.
        consensus_pct = "/".join(
            f"{max(min(g, _GROWTH_CAP), _GROWTH_FLOOR):.1%}" for g in consensus[:n_consensus]
        )
        ntm_note = (
            f"; Year 1 applied as {growth_schedule[0]:.1%} — growth from the TTM base to "
            "the FY1 consensus level, so it does not double-count the current fiscal "
            "year's growth already in TTM"
            if _ntm_restated
            else ""
        )
        prov["revenue_growth_rates"] = (
            f"analyst consensus FY1-{n_consensus} growth {consensus_pct}, "
            f"then linear fade to terminal {terminal_growth_rate:.1%}{ntm_note}"
        )
    elif has_real_cagr:
        assert cagr is not None  # narrowing for mypy
        # Floor at -20%/yr (severe-but-bounded decline), cap at +40%. The old
        # floor of 0.0 silently FORCED every structurally-declining firm to a
        # flat 0% explicit schedule — overstating fair value for exactly the
        # over-valued names the SELL/short path depends on. A negative base is
        # held flat across the explicit window by _decay_growth_schedule (it
        # only decays a base ABOVE terminal); the Gordon perpetuity handles the
        # eventual convergence to terminal_growth.
        base_growth = max(min(cagr, _GROWTH_CAP), _GROWTH_FLOOR)
        growth_schedule = _decay_growth_schedule(
            base_growth, terminal_growth_rate, projection_years
        )
        n_years = len(historical.years)
        if base_growth > terminal_growth_rate:
            prov["revenue_growth_rates"] = (
                f"trailing {n_years}yr revenue CAGR {base_growth:.1%}, "
                f"fading linearly to terminal {terminal_growth_rate:.1%} over the next {projection_years}yr"
            )
        else:
            # base ≤ terminal (mature or declining): held flat across the
            # explicit window — don't claim a decay that doesn't happen.
            prov["revenue_growth_rates"] = (
                f"trailing {n_years}yr revenue CAGR {base_growth:.1%}, "
                f"held flat over the next {projection_years}yr (terminal {terminal_growth_rate:.1%})"
            )
    else:
        # No reliable historical CAGR (data absent or NaN-polluted).
        # Start at industry-implied "median company growth" (2× terminal growth)
        # and decay to terminal; provenance is honest about the reason.
        base_growth = max(terminal_growth_rate * 2, 0.05)
        growth_schedule = _decay_growth_schedule(
            base_growth, terminal_growth_rate, projection_years
        )
        nan_note = (
            "historical data has NaN gaps, "
            if cagr is not None
            else "insufficient historical data, "
        )
        prov["revenue_growth_rates"] = (
            f"{nan_note}using a generic {base_growth:.1%} starting point fading to terminal {terminal_growth_rate:.1%}"
        )

    # ----- ebitda_margin ----------------------------------------------------
    # Cyclical: median EBITDA margin across the FULL cycle window (peak→trough→
    # recovery) — the normalized through-cycle earnings power, not the current
    # phase. Non-cyclical: unchanged trailing-3y median.
    _ebitda_suffix = "EBITDA margin, through-cycle median" if cyclical else "EBITDA margin median"
    ebitda_ticker, ebitda_value, ebitda_label = _ticker_median_with_label(
        _median_recent(historical.ebitda_margin, window=earnings_window), _ebitda_suffix
    )
    ebitda_margin, ebitda_source = _pick_with_provenance(
        ticker_value=ebitda_value,
        ticker_label=ebitda_label,
        industry_value=industry.ebitda_pct_revenue,
        industry_label=f"{industry.industry} industry median",
        rejected_ticker_reason="is non-positive; loss-making / missing-EBITDA years are not used as the going-concern normalized margin",
    )
    if cyclical and ebitda_ticker is not None:
        _through = _cycle_stats(historical.ebitda_margin, window=earnings_window)
        prov["ebitda_margin"] = (
            f"{ebitda_margin:.1%} ({ebitda_source}; {_cycle_note}"
            f"{_through}; commodity-cyclical Damodaran normalization convention, not the trailing-3yr median)"
        )
    else:
        prov["ebitda_margin"] = f"{ebitda_margin:.1%} ({ebitda_source})"

    # ----- capex_pct_revenue -----------------------------------------------
    # Cyclical: explicit-window CapEx% over the FULL cycle (avoid anchoring on a
    # single peak/trough year's capex/revenue). Non-cyclical: trailing-3y median.
    _capex_suffix = (
        "CapEx / revenue, through-cycle median" if cyclical else "CapEx / revenue median"
    )
    capex_ticker, capex_value, capex_label = _ticker_median_with_label(
        _median_ratio(historical.capital_expenditure, historical.revenue, window=earnings_window),
        _capex_suffix,
    )
    capex_pct, capex_source = _pick_with_provenance(
        ticker_value=capex_value,
        ticker_label=capex_label,
        industry_value=industry.capex_pct_revenue,
        industry_label=f"{industry.industry} industry median",
    )
    # Consistency guard (防地雷): when CapEx falls back to the industry aggregate
    # but EBITDA margin is the company's own, the pair can be mutually
    # inconsistent — e.g. Damodaran "Software (Internet)" CapEx 31.8% (an
    # aggregate skewed by cash-burning small-caps) layered onto a 50%-EBITDA-
    # margin mega-cap. CapEx can't sustainably exceed EBITDA (that is permanently
    # negative FCF), so cap an industry-fallback CapEx at the EBITDA margin. Only
    # fires on the fallback path (capex_ticker is None); a company's own
    # historical CapEx ratio is never touched.
    if capex_ticker is None and capex_pct > ebitda_margin:
        prov["capex_pct_revenue"] = (
            f"{ebitda_margin:.1%} ({capex_source} {capex_pct:.1%} converged to EBITDA margin "
            f"{ebitda_margin:.1%} — industry-aggregate CapEx exceeds the company's own EBITDA, which is unsustainable)"
        )
        capex_pct = ebitda_margin
    else:
        prov["capex_pct_revenue"] = f"{capex_pct:.1%} ({capex_source})"

    # ----- da_pct_revenue ---------------------------------------------------
    # Cyclical: revenue-WEIGHTED through-cycle D&A% (Σ D&A / Σ revenue). D&A is a
    # sticky stock, so D&A/revenue spikes at the trough when revenue collapses
    # (MU FY2023 49.9% is a trough artifact, not the run-rate ~24%); the weighted
    # ratio down-weights that. Non-cyclical: unchanged trailing-3y per-year median.
    if cyclical:
        _da_result = _weighted_ratio(
            historical.depreciation_amortization, historical.revenue, window=earnings_window
        )
        _da_suffix = "D&A / revenue, revenue-weighted through-cycle"
    else:
        _da_result = _median_ratio(historical.depreciation_amortization, historical.revenue)
        _da_suffix = "D&A / revenue median"
    _da_ticker, da_value, da_label = _ticker_median_with_label(_da_result, _da_suffix)
    da_pct, da_source = _pick_with_provenance(
        ticker_value=da_value,
        ticker_label=da_label,
        industry_value=industry.da_pct_revenue,
        industry_label=f"{industry.industry} industry median",
    )
    prov["da_pct_revenue"] = f"{da_pct:.1%} ({da_source})"

    # ----- cyclical explicit-window capex → maintenance anchor ---------------
    # A cyclical normalized to THROUGH-CYCLE earnings power must also normalize
    # reinvestment to MAINTENANCE level. Its through-cycle CapEx% bakes in the
    # current-regime GROWTH capex (MU FY2024-25 capacity build during the AI
    # super-cycle): CapEx 38.4% vs D&A 24.5% — a 14pt wedge that is pure expansion,
    # not maintenance. Holding 38% flat across the 10y explicit window assumes MU
    # expands at super-cycle pace forever, contradicting the through-cycle premise
    # and crushing FCF (implied $116 vs the validated ~$176 at maintenance). The
    # maintenance anchor is the SAME min(D&A, CapEx) Damodaran proxy the TERMINAL
    # value already uses (dcf._terminal_fcf): D&A is the steady-state reinvestment a
    # mature cyclical sustains. Only LOWERS capex (never raises a low-capex name like
    # WDC/STX, whose CapEx ≈ D&A already → no-op), and only for cyclicals — every
    # non-cyclical's trailing-3y capex is untouched. Skipped on the industry-fallback
    # path (the EBITDA-cap guard above already governs that).
    if cyclical and capex_ticker is not None and da_pct > 0 and capex_pct > da_pct:
        _full_capex = capex_pct
        capex_pct = da_pct
        prov["capex_pct_revenue"] = (
            f"{capex_pct:.1%} (through-cycle CapEx {_full_capex:.1%} converged to maintenance reinvestment "
            f"min(D&A, CapEx)={da_pct:.1%} — cyclical normalization: super-cycle expansion CapEx is excluded from the perpetuity base, "
            f"on the same basis as the terminal-value min(D&A, CapEx) anchor)"
        )

    # ----- nwc_pct_revenue --------------------------------------------------
    # FMP changeInWorkingCapital carries the cash-flow sign: negative = NWC grew
    # = cash consumed. Negate so nwc_pct_revenue means "NWC build as % of revenue,
    # positive = cash drag" — the same convention as capex (stored absolute) — so
    # the FCF formula `- ΔNWC` reduces FCF when working capital grows.
    #
    # The marginal NWC ratio (shared with the terminal value below) is derived
    # first because it is the degradation target when the trailing median blows
    # past the ±10% modelling band. A |median| > 10% is not real NWC economics —
    # a mature staple does not absorb a tenth of revenue into working capital
    # every year — but a trailing window polluted by non-core one-off swings
    # (KO's FY24/25 otherWorkingCapital, −6.2B/−7.2B, dragged the 3y median to
    # 13.2%). The ±10% clamp merely TRUNCATES that pollution and would then hold
    # 10% flat across the whole explicit window. Degrading instead to
    # marginal-ratio × growth — the SAME functional form the terminal value uses,
    # but with the explicit-window average growth rather than terminal growth —
    # re-derives the drag from clean per-year NWC-build economics (KO 13.2% →
    # ~1.4%, back near the ~1.9% TTM actual). A genuine high-NWC grower is
    # protected: its marginal ratio is stable and high, so marginal × its high
    # growth stays a correctly large drag rather than being reduced.
    terminal_nwc = _terminal_nwc_pct(
        historical.change_in_working_capital, historical.revenue, terminal_growth_rate
    )
    nwc_result = _median_ratio(historical.change_in_working_capital, historical.revenue)
    if nwc_result is not None:
        nwc_median, nwc_n = nwc_result
        raw_nwc = -nwc_median
        clamped_median = max(-0.10, min(0.10, raw_nwc))
        if clamped_median != raw_nwc and terminal_nwc is not None:
            # Clamp binds AND a marginal ratio is derivable → treat the clamp hit
            # as a pathology signal and degrade to the marginal-ratio route.
            # Explicit-window average growth (mean of the projected schedule)
            # takes the place of terminal growth in the same marginal × g form;
            # re-clamp to the ±10% band so a genuine high-NWC hyper-grower (high
            # marginal × high growth) is capped, not reduced. Scalar by design —
            # a per-year NWC sequence is deliberately out of scope here.
            marginal_ratio, _terminal_pct, raw_marginal = terminal_nwc
            avg_growth = statistics.mean(growth_schedule)
            degraded = marginal_ratio * avg_growth
            nwc_pct = max(-0.10, min(0.10, degraded))
            # Analyst-facing prose (BACKLOG A6⑤): every number below is the same
            # one the dev-jargon version carried (nwc_n / raw_nwc / marginal_ratio
            # / raw_marginal / avg_growth / degraded / nwc_pct) — only the wording
            # changed, from engineering vocabulary ("modelling band", "degraded
            # to", "re-clamped") to plain description of what the model did and
            # why, so a buy-side reader can follow the substitution without
            # knowing FinRobot's internals. The structured `nwc_clamped` flag
            # (below) is what actually drives the report's ⚠ — this string is
            # never parsed, only displayed verbatim as a tooltip.
            marginal_note = (
                f"{marginal_ratio:.1%} of each new revenue dollar (capped down from a raw "
                f"{raw_marginal:.1%}, most likely skewed by one-off items)"
                if marginal_ratio != raw_marginal
                else f"{marginal_ratio:.1%} of each new revenue dollar"
            )
            reclamp_note = (
                f", which came to {degraded:.1%} and was capped again into the model's ±10% range"
                if nwc_pct != degraded
                else ""
            )
            prov["nwc_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (re-derived: the trailing {nwc_n}-year average "
                f"change in working capital ran {raw_nwc:.1%} of revenue — too high to be a "
                f"sustainable, ongoing drag, so the model instead ties the assumption to the "
                f"marginal NWC ratio, {marginal_note}, applied to the {avg_growth:.1%} average "
                f"growth rate projected over the explicit forecast period{reclamp_note}; a "
                f"positive figure means working capital is absorbing cash)"
            )
        elif clamped_median != raw_nwc:
            # Clamp binds but no revenue-growth year to derive a marginal ratio
            # (declining / flat history) → honest fallback: keep the clamped
            # median and disclose the pre-clamp value, so provenance never implies
            # the band value IS the trailing median (batch-0 BUG-023 disclosure).
            nwc_pct = clamped_median
            prov["nwc_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (capped from a trailing {nwc_n}-year average of "
                f"{raw_nwc:.1%} of revenue — too high to be a sustainable, ongoing drag; a "
                f"positive figure means working capital is absorbing cash)"
            )
        else:
            nwc_pct = clamped_median
            prov["nwc_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (trailing {nwc_n}-year average change in working "
                f"capital as % of revenue; a positive figure means working capital is "
                f"absorbing cash)"
            )
    else:
        nwc_pct = 0.01
        prov["nwc_pct_revenue"] = (
            "1.0% of revenue (no working-capital history available; generic industry "
            "benchmark applied)"
        )

    # ----- terminal_nwc_pct_revenue ------------------------------------------
    # The explicit-window ΔNWC/revenue median embeds the HISTORICAL growth rate
    # (NWC build ≈ marginal NWC ratio × Δrevenue), so holding it into a 3%
    # perpetuity overstates the drag ~7x for a 20% grower (AMD: 8.1% → 1.4%) —
    # and, mirrored, props up cash burners on a perpetual NWC subsidy (RIVN:
    # −10% forever printed a 1.57x-market fair value). Steady state re-derives
    # it from the marginal ratio: median(ΔNWC_build / Δrevenue) over revenue-
    # GROWTH years × terminal growth (terminal_nwc computed above). No usable
    # growth years → None, and _terminal_fcf falls back to the explicit-window
    # value (honest: don't pretend to have computed a scaling the data can't
    # support).
    if terminal_nwc is not None:
        marginal_ratio, terminal_nwc_pct, raw_marginal = terminal_nwc
        if marginal_ratio != raw_marginal:
            # Marginal-ratio clamp bound: disclose the raw median so provenance
            # never implies the ±60% band value IS the median (BUG-023 — same
            # family as the explicit-window nwc clamp above). Wording is
            # analyst-facing (BACKLOG A6⑤) — numbers unchanged.
            prov["terminal_nwc_pct_revenue"] = (
                f"{terminal_nwc_pct:.2%} of revenue at steady state (marginal NWC ratio of "
                f"{marginal_ratio:.1%} of each new revenue dollar — capped down from a raw "
                f"{raw_marginal:.1%}, most likely skewed by one-off items — applied to the "
                f"{terminal_growth_rate:.1%} terminal growth rate)"
            )
        else:
            prov["terminal_nwc_pct_revenue"] = (
                f"{terminal_nwc_pct:.2%} of revenue at steady state (marginal NWC ratio of "
                f"{marginal_ratio:.1%} of each new revenue dollar applied to the "
                f"{terminal_growth_rate:.1%} terminal growth rate)"
            )
    else:
        terminal_nwc_pct = None
        prov["terminal_nwc_pct_revenue"] = (
            f"reuses the explicit-window figure of {nwc_pct:.1%} of revenue (no year of "
            f"revenue growth in the trailing history to derive a steady-state marginal NWC "
            f"ratio)"
        )

    # ----- tax_rate ---------------------------------------------------------
    # Company effective tax = income_tax_expense / pretax, where
    # pretax = net_income + income_tax_expense (textbook effective-rate口径).
    # Prefer it over the Damodaran industry aggregate, which for distorted
    # sectors badly misstates a profitable firm's real rate — "Software
    # (Internet)" reports 40% (skewed by loss-makers), ~2x META's actual ~21%,
    # and a 40% tax on top of an industry-fallback CapEx is what drove META's
    # implied price negative. Falls back to industry only when the snapshot lacks
    # a usable tax line or the implied rate is a non-run-rate outlier.
    company_tax = _effective_tax_rate(
        financials.income.income_tax_expense, financials.income.net_income
    )
    # Step 1 — pick the source rate and the reason it was chosen. ``tax_reason``
    # is the inner clause of the provenance; the displayed value is filled in
    # AFTER the modelling clamp so it always equals the rate the DCF uses.
    if company_tax is not None:
        chosen_tax = company_tax
        tax_reason = "latest-filing effective tax rate = income tax / pretax income"
    else:
        # Company rate was rejected. The DCF uses the industry fallback, and the
        # provenance must state the REAL reason — never imply "no tax line" when
        # the line existed but was an out-of-band one-off. When the raw rate is
        # computable and breached the cap/floor, disclose it so the substitution
        # is visible, mirroring the cost-of-debt clamp (BUG-023).
        chosen_tax = industry.effective_tax_rate
        tax_expense = financials.income.income_tax_expense
        net_income = financials.income.net_income
        raw_tax_rate: float | None = None
        if tax_expense is not None and net_income is not None:
            pretax = net_income + tax_expense
            if pretax > 0:
                raw_tax_rate = tax_expense / pretax
        if raw_tax_rate is not None and raw_tax_rate > TAX_RATE_OUTLIER_CAP:
            tax_reason = (
                f"{industry.industry} industry effective tax rate — filing effective rate "
                f"{raw_tax_rate:.1%} exceeds the {TAX_RATE_OUTLIER_CAP:.0%} cap and is a one-off tax item, discarded"
            )
        elif raw_tax_rate is not None and raw_tax_rate < TAX_RATE_OUTLIER_FLOOR:
            tax_reason = (
                f"{industry.industry} industry effective tax rate — filing effective rate "
                f"{raw_tax_rate:.1%} is below the {TAX_RATE_OUTLIER_FLOOR:.0%} floor and is a one-off tax credit, discarded"
            )
        else:
            tax_reason = f"{industry.industry} industry effective tax rate — no usable tax line in filing / pretax is negative"

    # Step 2 — apply the modelling band [DCF_TAX_RATE_FLOOR, DCF_TAX_RATE_CAP] that
    # the DCF actually uses, and build provenance from the CLAMPED value, disclosing
    # the floor/cap when it binds. This is the same point where DCFInputs is later
    # constructed (the Field validator clamps too); doing it here keeps the displayed
    # rate identical to the used rate even when the chosen source rate (e.g. a 42%
    # company rate) sits between the outlier cap and the modelling cap.
    tax_rate = max(DCF_TAX_RATE_FLOOR, min(DCF_TAX_RATE_CAP, chosen_tax))
    if chosen_tax > DCF_TAX_RATE_CAP:
        prov["tax_rate"] = (
            f"{tax_rate:.1%} ({tax_reason}: {chosen_tax:.1%}, clamped to the {DCF_TAX_RATE_CAP:.0%} cap)"
        )
    elif chosen_tax < DCF_TAX_RATE_FLOOR:
        prov["tax_rate"] = (
            f"{tax_rate:.1%} ({tax_reason}: {chosen_tax:.1%}, clamped to the {DCF_TAX_RATE_FLOOR:.0%} floor)"
        )
    else:
        prov["tax_rate"] = f"{tax_rate:.1%} ({tax_reason})"

    # ----- WACC components --------------------------------------------------
    # Beta: prefer provider-reported beta, fall back to industry levered beta,
    # then apply the Blume/Bloomberg adjustment ASYMMETRICALLY (see adjust_beta_blume).
    # A raw 5y regression beta is a noisy estimate of the FORWARD beta: for HIGH-beta
    # names (β > 1.0) the noise mean-reverts toward 1.0, so 2/3·β+1/3·1.0 applies —
    # using NVDA's raw 2.24 unadjusted put it at a 16.6% CAPM cost of equity, a
    # discount rate no analyst applies to a mega-cap. For structurally low-beta
    # defensive names (β ≤ 1.0) the low beta is real (cash flows don't co-move with
    # the cycle), not noise, so the raw beta is kept — never inflated toward 1.0.
    # The industry-relative beta sanity is gated to BANKS only: a bank is structurally
    # never a low-beta defensive (levered balance sheet, cyclical credit), so a bank beta
    # far below the bank-industry levered beta is a vendor short-window artifact (MTB β
    # 0.59). For every other sector the raw low beta is REAL and kept verbatim (KO 0.35,
    # utilities) — applying the relative check there would误伤 true low-beta defensives,
    # the dcf-recall red line.
    _bank = is_bank(industry=financials.market.industry, sector=financials.market.sector)
    beta_proxy, beta_proxy_label = _bank_beta_proxy(industry, is_bank_issuer=_bank)
    raw_beta, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider-reported 5y beta",
        industry_value=beta_proxy,
        industry_label=beta_proxy_label,
        floor=_BETA_BAND_FLOOR,
        ceiling=_BETA_BAND_CEILING,
        rejected_ticker_reason=_BETA_OUT_OF_BAND_REASON,
        reject_value_fmt="{:.2f}",
        relative_floor=_BETA_RELATIVE_FLOOR if _bank else None,
        relative_floor_industry_min=_BETA_RELATIVE_INDUSTRY_MIN,
        relative_reject_reason=_BETA_IMPLAUSIBLY_LOW_REASON,
    )
    used_provider_beta = beta_source == "provider-reported 5y beta"
    beta_chosen = adjust_beta_blume(raw_beta) if used_provider_beta else raw_beta
    # Provenance must match the branch actually taken (same 1.0 threshold as
    # adjust_beta_blume) — printing "Blume-adjusted" for a β ≤ 1.0 name that was
    # NOT adjusted would be a false provenance trail (CLAUDE.md core contract:
    # every number must be traceable to what really produced it). When the provider
    # beta was out-of-band, raw_beta IS the industry proxy (no Blume — the proxy is
    # already a levered industry beta, not a noisy regression); beta_source already
    # discloses the substitution + the rejected raw value, so emit just the chosen
    # value + that self-complete source rather than a false regression/Blume note.
    if not used_provider_beta:
        prov["beta"] = f"{beta_chosen:.2f} ({beta_source})"
    else:
        if raw_beta > 1.0:
            beta_note = "Blume-adjusted 2/3·β+1/3·1.0 toward 1.0 (high-β estimate mean-reverts)"
        else:
            beta_note = "raw regression β (structural low-β defensive — not inflated)"
        prov["beta"] = f"{beta_chosen:.2f} ({beta_source} {raw_beta:.2f}, {beta_note})"

    # Cost of debt: try interest_expense / total_debt; fall back to 5%.
    total_debt = financials.balance.total_debt
    interest_exp = financials.income.interest_expense
    cod = _cost_of_debt(interest_exp, total_debt)
    if cod is not None:
        cost_of_debt = cod
        # interest_exp is not None and total_debt > 0 here (else cod is None), so
        # the raw rate is well-defined. Be honest in provenance when it was
        # clamped instead of implying the displayed value is the raw ratio (BUG-023).
        raw_rate = interest_exp / total_debt  # type: ignore[operator]
        if raw_rate < COST_OF_DEBT_FLOOR:
            prov["cost_of_debt"] = (
                f"{cost_of_debt:.1%} (interest expense / total debt = {raw_rate:.2%}, clamped to the "
                f"{COST_OF_DEBT_FLOOR:.0%} floor)"
            )
        elif raw_rate > COST_OF_DEBT_CAP:
            prov["cost_of_debt"] = (
                f"{cost_of_debt:.1%} (interest expense / total debt = {raw_rate:.1%}, clamped to the "
                f"{COST_OF_DEBT_CAP:.0%} cap)"
            )
        else:
            prov["cost_of_debt"] = f"{cost_of_debt:.1%} (latest interest expense / total debt)"
    else:
        cost_of_debt = DEFAULT_COST_OF_DEBT
        prov["cost_of_debt"] = f"{cost_of_debt:.1%} (investment-grade corporate-bond benchmark)"

    # Debt ratio: from current market cap + total debt.
    market_cap = financials.market.market_cap if financials.market else 0
    if total_debt is not None and total_debt > 0 and market_cap > 0:
        debt_ratio = total_debt / (total_debt + market_cap)
        prov["debt_ratio"] = (
            f"{debt_ratio:.1%} (total debt ${total_debt / 1e9:.1f}B / "
            f"(debt + market cap ${market_cap / 1e9:.1f}B))"
        )
    else:
        debt_ratio = industry.debt_ratio
        prov["debt_ratio"] = f"{debt_ratio:.1%} ({industry.industry} industry D/(D+E))"

    prov["risk_free_rate"] = f"{risk_free_rate:.1%} (current 10Y US Treasury yield)"
    prov["equity_risk_premium"] = f"{equity_risk_premium:.1%} (Damodaran implied ERP)"
    prov["terminal_growth_rate"] = f"{terminal_growth_rate:.1%} (long-run US nominal GDP growth)"

    # ----- Balance items ----------------------------------------------------
    shares_outstanding = financials.market.shares_outstanding
    prov["shares_outstanding"] = (
        f"current shares outstanding {shares_outstanding / 1e9:.2f}B shares"
    )

    # None ≠ 0: a missing debt/cash component is "not reported", not zero. The DCF
    # equity bridge still needs a net-debt scalar, so coerce the missing side to 0
    # at the point of use — but disclose it in provenance so the substitution is
    # never silent (net debt may be understated). The resulting number is
    # identical to the old zero-filled model default; only the disclosure is new.
    raw_cash = financials.balance.total_cash
    nd_debt = total_debt if total_debt is not None else 0.0
    nd_cash = raw_cash if raw_cash is not None else 0.0
    net_debt = nd_debt - nd_cash
    if total_debt is None or raw_cash is None:
        missing = " and ".join(
            label
            for label, value in (("total debt", total_debt), ("cash", raw_cash))
            if value is None
        )
        prov["net_debt"] = (
            f"${net_debt / 1e9:+.1f}B ({missing} not disclosed; missing item treated as 0 — net debt may be understated)"
        )
    else:
        prov["net_debt"] = (
            f"${net_debt / 1e9:+.1f}B "
            f"(total debt − cash = {nd_debt / 1e9:.1f}B − {nd_cash / 1e9:.1f}B)"
        )

    # Disclose any construction-time modelling clamp that binds, so provenance
    # never leads with a value the DCF did not use (BUG-023). These bands are
    # TIGHTER than the DCFInputs Field validators (e.g. capex 45% vs le=1), so a
    # bind is a real caliber substitution, not just NaN protection. Pure
    # provenance side-effect — the field values constructed below are unchanged.
    _disclose_construction_clamp(prov, "ebitda_margin", ebitda_margin, 0.01, 0.95)
    _disclose_construction_clamp(prov, "capex_pct_revenue", capex_pct, 0.005, 0.45)
    _disclose_construction_clamp(prov, "da_pct_revenue", da_pct, 0.005, 0.40)
    _disclose_construction_clamp(prov, "debt_ratio", debt_ratio, 0.0, 0.80)

    # Structured signal for the report's model-vs-current reconciliation ⚠:
    # whether the explicit-window ΔNWC/revenue median sat outside the ±10%
    # modelling band (and was therefore clamped — or, post the marginal-ratio
    # degradation, re-derived from marginal × growth). Re-derived here (rather
    # than captured in the nwc_pct block above) so it stays INDEPENDENT of the
    # nwc_pct_revenue provenance STRING — the ⚠ never has to parse prose, and
    # this add-only field never collides with a clamp-disclosure edit there.
    _nwc_raw = _median_ratio(historical.change_in_working_capital, historical.revenue)
    nwc_clamped = _nwc_raw is not None and not (-0.10 <= -_nwc_raw[0] <= 0.10)

    # ----- Final clamp + construct -----------------------------------------
    # Pydantic Field validators enforce ranges; clamp first to avoid raising
    # when industry fallback edge-cases approach the bounds.
    return DCFInputs(
        revenue_base=revenue_base,
        revenue_growth_rates=growth_schedule,
        ebitda_margin=max(0.01, min(0.95, ebitda_margin)),
        capex_pct_revenue=max(0.005, min(0.45, capex_pct)),
        nwc_pct_revenue=nwc_pct,
        terminal_nwc_pct_revenue=terminal_nwc_pct,
        nwc_clamped=nwc_clamped,
        da_pct_revenue=max(0.005, min(0.40, da_pct)),
        # Already clamped to [DCF_TAX_RATE_FLOOR, DCF_TAX_RATE_CAP] above, where the
        # clamp is disclosed in provenance; this is an idempotent safety net.
        tax_rate=max(DCF_TAX_RATE_FLOOR, min(DCF_TAX_RATE_CAP, tax_rate)),
        risk_free_rate=risk_free_rate,
        # beta_chosen is already in (0, 5]: _pick_with_provenance returns an in-band
        # raw (0 < β ≤ 5) or the Damodaran industry proxy (levered, clamped [0.3, 2.5]),
        # and Blume only mean-reverts high betas downward — so the DCFInputs.beta
        # Field(ge=0, le=5) is the sole modeling bound and never binds. NO extra floor:
        # a genuine low-β defensive (VZ 0.22, JNJ 0.256) keeps its raw value untouched.
        beta=beta_chosen,
        equity_risk_premium=equity_risk_premium,
        cost_of_debt=cost_of_debt,
        # Cap market-leverage at 0.80 for WACC weighting. Above ~80% debt the
        # equity sliver is so thin that a low after-tax cost of debt drives WACC
        # below long-run GDP growth (terminal growth), making the Gordon perpetuity
        # undefined. 80% is the standard practitioner ceiling for a going concern.
        debt_ratio=max(0.0, min(0.80, debt_ratio)),
        terminal_growth_rate=terminal_growth_rate,
        shares_outstanding=shares_outstanding,
        net_debt=net_debt,
        # implied_price is a per-share market quote → quote_currency (TWD for
        # TSM, EUR for SAP), not reporting_currency. Carried so the artifact
        # tags its outputs and the diff formatter never assumes USD.
        currency=financials.quote_currency,
        assumption_provenance=prov,
        # 门四溯源半: when these inputs were fetched (canonical fetch time),
        # so every DCF/WACC surface can print "inputs as of X". Pure: copied
        # from the snapshot, never a wall-clock call.
        inputs_fetched_at=financials.timestamp,
    )


def dcf_current_actuals(
    financial_data: FinancialData, historical: HistoricalMetrics
) -> tuple[dict[str, float | None], bool]:
    """Current-reality actuals for the four DCF drivers, for the report's
    model-vs-current reconciliation. Calibers are MIXED and disclosed per cell by
    the report (the reconciliation is a driver-by-driver comparison, not a
    cross-row one). Returns ``(actuals, capex_is_ttm)``.

    * ``ebitda_margin`` — the **TTM** ratio ``income.ebitda / income.revenue`` from
      the canonical snapshot (the freshest 12-month margin). A ratio, so it is
      FX-invariant — the pipeline's USD normalization doesn't shift it.
    * ``capex_pct_revenue`` — the **TTM** ratio ``income.capital_expenditure /
      income.revenue`` from the canonical snapshot when that field resolved (FMP's
      cash-flow-summed TTM path, or yfinance's operatingCashflow−freeCashflow
      derivation — see ``IncomeStatement.capital_expenditure``). Falls back to the
      ticker's **latest fiscal year** from ``HistoricalMetrics`` when the canonical
      snapshot lacks a usable TTM capex figure (thin/unavailable cash-flow
      statement for that ticker — margin's TTM source is the income statement,
      capex's is the cash-flow statement, so the two can resolve independently).
      Never fabricated either way. The second return value, ``capex_is_ttm``, is
      True exactly when the TTM figure was used; the report reads it so the
      "Current" cell's caliber tag never claims TTM for a fallback FY value
      (BUG-023 displayed==actual family) — this is a *display*-caliber upgrade
      only, it does NOT touch the DCF's own seeded explicit-period assumptions
      (batch 4b, 2026-07-09: re-anchoring the model itself was explicitly rejected;
      the reconciliation table's full disclosure is the sanctioned alternative).
    * ``revenue_growth`` / ``nwc_pct_revenue`` — the ticker's **latest fiscal
      year** from ``HistoricalMetrics`` (no TTM source for ΔNWC exists in the
      canonical snapshot, and we do not fabricate one). ``nwc`` negates ΔNWC/
      revenue (positive = cash absorbed, the seed convention).

    Every value is the ticker's OWN figure — never the industry fallback the seed
    may have picked when history was thin — or ``None`` when the source lacks a
    usable point (never fabricated). The ΔNWC / fallback-capex ratios reuse
    ``_median_ratio`` at a one-year window so they inherit its NaN / zero-row /
    zero-denominator hygiene and the seed's own year-pairing.
    """

    def _latest_ratio(num: list[float], den: list[float]) -> float | None:
        r = _median_ratio(num, den, window=1, min_samples=1)
        return r[0] if r is not None else None

    def _latest_finite(series: list[float | None]) -> float | None:
        if not series:
            return None
        v = series[-1]
        return v if v is not None and math.isfinite(v) else None

    # TTM EBITDA margin from the canonical snapshot (income is TTM). income.revenue
    # is a required float; guard 0 / non-finite / missing EBITDA → None (never 0).
    inc = financial_data.income
    ttm_margin: float | None = None
    if (
        inc.ebitda is not None
        and math.isfinite(inc.ebitda)
        and inc.revenue
        and math.isfinite(inc.revenue)
    ):
        ttm_margin = inc.ebitda / inc.revenue

    # TTM capex ratio from the same canonical snapshot, same finiteness/zero-denom
    # guard as the margin above. None when the snapshot's cash-flow statement never
    # resolved a capex figure for this ticker (never fabricated) — fall back to the
    # latest-FY ratio, exactly the pre-existing behavior when TTM is unavailable.
    ttm_capex_pct: float | None = None
    if (
        inc.capital_expenditure is not None
        and math.isfinite(inc.capital_expenditure)
        and inc.revenue
        and math.isfinite(inc.revenue)
    ):
        ttm_capex_pct = inc.capital_expenditure / inc.revenue

    capex_is_ttm = ttm_capex_pct is not None
    capex_pct = (
        ttm_capex_pct
        if capex_is_ttm
        else _latest_ratio(historical.capital_expenditure, historical.revenue)
    )

    nwc_raw = _latest_ratio(historical.change_in_working_capital, historical.revenue)
    actuals: dict[str, float | None] = {
        "revenue_growth": _latest_finite(historical.revenue_growth_yoy),
        "ebitda_margin": ttm_margin,
        "capex_pct_revenue": capex_pct,
        "nwc_pct_revenue": None if nwc_raw is None else -nwc_raw,
    }
    return actuals, capex_is_ttm


# ---------------------------------------------------------------------------
# Small helpers — last so they stay near caller sites
# ---------------------------------------------------------------------------


def _pct_bound(bound: float) -> str:
    """Format a clamp bound as a percent without trailing zeros: 0.80→'80%',
    0.005→'0.5%'. Used only inside clamp-disclosure provenance."""
    return f"{bound * 100:.1f}".rstrip("0").rstrip(".") + "%"


def _disclose_construction_clamp(
    prov: dict[str, str], key: str, raw: float, lo: float, hi: float
) -> None:
    """Rewrite ``prov[key]`` to lead with the clamped model value when the
    construction-time clamp ``max(lo, min(hi, raw))`` binds, disclosing the
    pre-clamp raw value + the bound it hit (BUG-023 clamp-then-disclose:
    displayed == the value the model uses). No-op when the clamp does not bind,
    so provenance is byte-identical for the common in-band case.

    The existing string always leads with ``f'{raw:.1%}'`` and closes with ')'
    (asserted); the model value replaces that lead and the disclosure is
    inserted just inside the closing paren, so the original source clause is
    preserved verbatim.
    """
    clamped = max(lo, min(hi, raw))
    if clamped == raw:
        return
    lead = f"{raw:.1%}"
    existing = prov[key]
    assert existing.startswith(lead) and existing.endswith(")"), (
        f"clamp-disclose expects provenance[{key!r}] to lead with {lead!r} and end "
        f"with ')'; got {existing!r}"
    )
    which, bound = ("cap", hi) if raw > hi else ("floor", lo)
    source_clause = existing[len(lead) : -1]  # " (…original source…"
    prov[key] = (
        f"{clamped:.1%}{source_clause}, raw {raw:.1%} clamped to the "
        f"{_pct_bound(bound)} model {which})"
    )


def _median_recent(
    values: list[float | None],
    *,
    window: int = _MEDIAN_WINDOW_YEARS,
    min_samples: int = _MIN_HISTORY_SAMPLES,
) -> tuple[float, int] | None:
    """Median of the most recent *window* non-zero, non-None, non-NaN entries.

    ``window`` bounds the slice; ``min_samples`` is the minimum raw history
    length below which we don't trust the ticker's own median (caller falls
    back to industry). Returns ``(median, count)`` where ``count`` is how many
    usable entries actually fed the median — a 2-year history sliced [-3:]
    returns count=2, so provenance reports the real sample size, not the window.

    None entries (a year whose numerator the provider omitted) are skipped, not
    treated as 0 — a missing margin must not drag the historical median down.
    """
    if len(values) < min_samples:
        return None
    recent = [v for v in values[-window:] if v is not None and v != 0 and not math.isnan(v)]
    if not recent:
        return None
    return statistics.median(recent), len(recent)


def _cycle_stats(values: list[float | None], *, window: int) -> str:
    """Provenance fragment exposing the cycle shape behind a normalized median.

    Returns "（峰 X% / 谷 Y% / 中位 Z% / 均值 W%，N 年）" over the usable entries in
    the window, so a UI下钻 can see the trough and peak the normalized base
    straddles (the analyst-facing传感器 for "is this a real cycle or a fluke?").
    Empty fragment when no usable entry exists.
    """
    usable = [v for v in values[-window:] if v is not None and not math.isnan(v)]
    if not usable:
        return ""
    return (
        f"(peak {max(usable):.1%} / trough {min(usable):.1%} / median "
        f"{statistics.median(usable):.1%} / mean {statistics.mean(usable):.1%}, "
        f"{len(usable)}yr)"
    )


# A normalized base only "spans a full peak→trough→recovery cycle" when the window
# is deep enough AND actually contains a real swing. <6 usable years can't straddle
# a full memory cycle (~9y), and a <15pt op-margin spread is a flat regime, not a
# cycle — claiming "完整周期" on either would be the overclaim the project forbids.
_FULL_CYCLE_MIN_YEARS: Final[int] = 6
_FULL_CYCLE_MIN_SPREAD: Final[float] = 0.15


def _cycle_coverage(
    years: list[int], operating_margin: list[float | None], *, window: int
) -> tuple[int, bool, int | None, int | None]:
    """Describe the ACTUAL cycle the window covers, so provenance never overclaims.

    Returns ``(n_years, spans_full_cycle, peak_fy, trough_fy)`` over the windowed
    operating-margin series (the most complete margin the extractor fields):
      - ``n_years``: usable (non-None) margin years in the window.
      - ``spans_full_cycle``: True only when the window is both deep enough
        (≥ _FULL_CYCLE_MIN_YEARS) and carries a real peak→trough swing
        (spread ≥ _FULL_CYCLE_MIN_SPREAD) — the gate for the "罩完整周期" claim.
      - ``peak_fy`` / ``trough_fy``: the fiscal years of the max / min margin, so
        the prose can name the REAL peak (MU FY2018) and trough (FY2023) instead of
        an unconditional template phrase. None when no usable year exists.

    Pairs years with margins positionally (both lists are time-aligned oldest-first
    by the extractor) and windows the last ``window`` entries — the same slice the
    medians use — so the disclosed shape is the shape that actually fed the number.
    """
    paired = [
        (y, m) for y, m in zip(years, operating_margin) if m is not None and not math.isnan(m)
    ]
    paired = paired[-window:]
    if not paired:
        return 0, False, None, None
    margins = [m for _, m in paired]
    peak_fy = max(paired, key=lambda p: p[1])[0]
    trough_fy = min(paired, key=lambda p: p[1])[0]
    spread = max(margins) - min(margins)
    spans = len(paired) >= _FULL_CYCLE_MIN_YEARS and spread >= _FULL_CYCLE_MIN_SPREAD
    return len(paired), spans, peak_fy, trough_fy


def _ticker_median_with_label(
    result: tuple[float, int] | None, suffix: str
) -> tuple[tuple[float, int] | None, float | None, str]:
    """Adapt a ``(median, count)`` helper result for ``_pick_with_provenance``.

    Returns ``(raw_result, value, label)`` where:
      - ``raw_result`` is the original tuple-or-None (so callers can still test
        ``is None`` for the industry-fallback consistency guards),
      - ``value`` is the median float (or None when the helper returned None),
      - ``label`` is the ticker provenance string with the *actual* sample count
        baked in — "过去 {n} 年 {suffix}" — so the UI never claims more years of
        history than actually fed the median (BUG-026). When the helper returned
        None the label falls back to the nominal window; it is never shown
        because ``_pick_with_provenance`` takes the industry branch.
    """
    if result is None:
        return None, None, f"trailing {_MEDIAN_WINDOW_YEARS}yr {suffix}"
    value, count = result
    return result, value, f"trailing {count}yr {suffix}"


def _pick_with_provenance(
    *,
    ticker_value: float | None,
    ticker_label: str,
    industry_value: float,
    industry_label: str,
    floor: float = 0.0,
    ceiling: float | None = None,
    rejected_ticker_reason: str | None = None,
    reject_value_fmt: str = "{:.1%}",
    relative_floor: float | None = None,
    relative_floor_industry_min: float = 0.0,
    relative_reject_reason: str | None = None,
) -> tuple[float, str]:
    """Pick ticker_value when in band, else industry_value. Return (value, source_label).

    The ticker value is accepted only when ``floor < ticker_value`` AND (when a
    ``ceiling`` is given) ``ticker_value <= ceiling``. Anything outside the band —
    a non-positive margin, or a vendor beta glitch below 0 / above 5 — routes to the
    industry proxy. When ``rejected_ticker_reason`` is set the rejected raw value is
    disclosed in the provenance so the substitution is traceable.

    ``reject_value_fmt`` formats that disclosed raw value: ratios (margins, capex%)
    are percentages (default "{:.1%}"); beta is a plain coefficient, so the beta
    callers pass "{:.2f}" — printing a beta with "%" would assert a false number
    (e.g. SHEL's −0.248 beta shown as "−24.8%").

    ``relative_floor`` (beta only) adds an industry-relative sanity check: a ticker
    value implausibly far BELOW a normal-magnitude industry proxy is a short-window
    vendor regression artifact, not a real low reading, and routes to the proxy. It is
    gated on ``industry_value > relative_floor_industry_min`` — a genuinely low-magnitude
    sector (utilities, β≈0.5) has a low industry value, so a low ticker reading there
    MATCHES its industry and is kept. This is NOT an absolute floor (which would误伤 true
    low-beta defensives — see dcf-recall): it fires only when a name sits far below a
    NORMAL-beta industry (MTB β 0.59 in Banks-Regional β 0.91 = vendor noise → proxy).
    """
    in_band = ticker_value is not None and ticker_value > floor
    if in_band and ceiling is not None and ticker_value > ceiling:  # type: ignore[operator]
        in_band = False
    relative_reject = (
        in_band
        and relative_floor is not None
        and ticker_value is not None
        and industry_value > relative_floor_industry_min
        and ticker_value < relative_floor * industry_value
    )
    if relative_reject:
        in_band = False
    if in_band:
        return ticker_value, ticker_label  # type: ignore[return-value]
    reason = relative_reject_reason if relative_reject else rejected_ticker_reason
    if ticker_value is not None and reason is not None:
        return (
            industry_value,
            f"{industry_label}; {ticker_label} {reject_value_fmt.format(ticker_value)} {reason}",
        )
    return industry_value, industry_label


def _bank_beta_proxy(industry: IndustryDefault, *, is_bank_issuer: bool) -> tuple[float, str]:
    """Beta proxy used by bank WACC seeds.

    Damodaran's bank sub-industry rows can occasionally carry low-beta readings
    (2026-01 regional banks: 0.3985). That is useful as a raw source fact, but it
    defeats the project-level rule that banks are not low-beta defensives. For
    beta only, floor a low bank sub-industry proxy to Total Market so the
    industry-relative vendor-glitch check has a normal-magnitude comparator.
    Other industry fields (tax, D/E, margins) still use the matched bank row.
    """
    label = f"{industry.industry} industry levered beta"
    if not is_bank_issuer or industry.levered_beta >= _BETA_RELATIVE_INDUSTRY_MIN:
        return industry.levered_beta, label

    market = get_industry_default(None)
    if market.levered_beta <= industry.levered_beta:
        return industry.levered_beta, label
    return (
        market.levered_beta,
        (
            f"Total Market industry levered beta used as bank beta proxy floor "
            f"({industry.industry} Damodaran beta {industry.levered_beta:.2f} is "
            "below the non-defensive bank floor)"
        ),
    )


# Marginal NWC ratio (ΔNWC/Δrevenue) clamp band. Real NWC-to-revenue LEVELS sit
# well inside ±60%; a marginal-ratio median outside the band is data noise
# (one-off settlements, derivative collateral swings), not working-capital
# economics. The resulting terminal drag/subsidy is further clamped to the same
# ±10% band as nwc_pct_revenue so the field validators never reject the seed.
_MARGINAL_NWC_RATIO_CLAMP = 0.60
_TERMINAL_NWC_CLAMP = 0.10


def _terminal_nwc_pct(
    change_in_working_capital: list[float],
    revenue: list[float],
    terminal_growth: float,
) -> tuple[float, float, float] | None:
    """Steady-state ΔNWC as % of revenue: median(ΔNWC_build/Δrevenue) × tg.

    The marginal ratio is taken over revenue-GROWTH years only — ΔNWC/Δrev is
    meaningless when revenue shrank (negative denominator flips the sign of an
    economically identical build). FMP changeInWorkingCapital carries the
    cash-flow sign (negative = NWC grew = cash consumed), so build = −value,
    matching the nwc_pct_revenue convention above.

    Returns ``(marginal_ratio, terminal_pct, raw_marginal_median)`` for
    provenance — ``marginal_ratio`` is clamped to ±_MARGINAL_NWC_RATIO_CLAMP,
    ``raw_marginal_median`` is the un-clamped median so the caller can disclose
    when the clamp bound (BUG-023) — or None when no usable growth year exists
    (declining/flat revenue history, NaN-polluted rows), in which case the
    caller leaves terminal_nwc_pct_revenue unset and the perpetuity falls back
    to the explicit-window ΔNWC ratio.
    """
    ratios: list[float] = []
    for i in range(1, min(len(change_in_working_capital), len(revenue))):
        cwc, rev_now, rev_prev = change_in_working_capital[i], revenue[i], revenue[i - 1]
        if any(math.isnan(v) for v in (cwc, rev_now, rev_prev)):
            continue
        d_rev = rev_now - rev_prev
        if d_rev <= 0 or cwc == 0:
            continue
        ratios.append(-cwc / d_rev)
    if not ratios:
        return None
    raw_marginal = statistics.median(ratios)
    marginal = max(-_MARGINAL_NWC_RATIO_CLAMP, min(_MARGINAL_NWC_RATIO_CLAMP, raw_marginal))
    terminal = max(-_TERMINAL_NWC_CLAMP, min(_TERMINAL_NWC_CLAMP, marginal * terminal_growth))
    return marginal, terminal, raw_marginal
