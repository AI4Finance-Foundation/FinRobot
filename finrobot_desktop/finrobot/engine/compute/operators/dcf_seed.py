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
from finrobot.engine.primitives.industry import commodity_cyclical_basis
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
    if rate < 0.0 or rate > 0.45:
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
            TTM — Damodaran applies the normalized MARGIN to CURRENT revenue;
            re-basing revenue too would double-count the cycle phase. False is the
            unchanged trailing-3y path for every non-cyclical (KO逐位 identical).

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
                f"through-cycle 中位（{_cyc_n} 年 罩完整周期:"
                f"峰 FY{_cyc_peak_fy} / 谷 FY{_cyc_trough_fy}）"
            )
            _coverage_cn = f"窗口 {_cyc_n} 年罩完整 峰→谷→恢复 周期(峰 FY{_cyc_peak_fy} / 谷 FY{_cyc_trough_fy})"
        elif _cyc_n > 0:
            # Honest about a truncated window — name what we actually have, don't
            # claim a full cycle the data can't support.
            _cycle_note = (
                f"through-cycle 中位（仅 {_cyc_n} 年,窗口未必罩完整周期:"
                f"峰 FY{_cyc_peak_fy} / 谷 FY{_cyc_trough_fy}）"
            )
            _coverage_cn = (
                f"窗口仅 {_cyc_n} 年,可能未罩完整周期"
                f"(现有 峰 FY{_cyc_peak_fy} / 谷 FY{_cyc_trough_fy})"
            )
        else:
            _cycle_note = "through-cycle 中位（历史不足,退行业基准）"
            _coverage_cn = "历史不足,无法构造 through-cycle 窗口"
        # Name the REAL arm that fired — an auto OEM (TSLA/F/GM) hits the industry
        # whitelist, NOT the memory/storage keyword; claiming "memory/storage 命中"
        # for it is fabricated provenance, and downstream the memory-supercycle
        # narrative (审校修正 1) gates on this exact substring.
        _arm_cn = (
            "行业白名单命中:钢铁/航运/化工/油气/汽车等大宗周期"
            if commodity_cyclical_basis(financials.market.industry) == "industry"
            else "memory/storage 白名单/关键词命中"
        )
        prov["cyclical_normalization"] = (
            f"判定为大宗周期股({_arm_cn}) → 盈利基底走 "
            "through-cycle 正常化:EBITDA 利润率取周期中位、D&A 营收加权 through-cycle、"
            f"显式期 CapEx 取 through-cycle 中位;{_coverage_cn};"
            "营收基保持当前 TTM(Damodaran 口径 3:正常化 margin × 当前营收,"
            "不重基营收以免数两遍周期相位)。"
        )

    # ----- revenue_base ------------------------------------------------------
    # Label the basis HONESTLY: revenue_base is the canonical financials' revenue,
    # which is TTM by default (not annual). Mislabeling TTM as "年报" is exactly
    # the口径 error the project forbids. Read the actual basis from provenance.
    revenue_base = financials.income.revenue
    _basis = financials.provenance.period_basis if financials.provenance else "ttm"
    _basis_cn = {
        "ttm": "最新 TTM 营收(滚动 12 个月)",
        "annual": "最新年报营收",
        "quarterly": "最新季度营收(年化)",
    }.get(_basis, f"最新营收({_basis})")
    prov["revenue_base"] = f"{_basis_cn} ${revenue_base / 1e9:.1f}B"

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
        # Analyst consensus drives the explicit window. Clamp each consensus year
        # to the shared floor/cap, then decay the tail from the last consensus
        # year down to terminal — don't extrapolate a finite-horizon estimate
        # forever, and don't fabricate a rise when the last consensus year is
        # already ≤ terminal (mature: hold flat, Gordon perpetuity does the rest).
        explicit = [max(min(g, _GROWTH_CAP), _GROWTH_FLOOR) for g in consensus][:projection_years]
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
        pct = "/".join(f"{g:.1%}" for g in growth_schedule[:n_consensus])
        prov["revenue_growth_rates"] = (
            f"分析师一致预期 FY1-{n_consensus} 增长 {pct}，"
            f"之后线性衰减到永续 {terminal_growth_rate:.1%}"
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
                f"过去 {n_years} 年营收 CAGR {base_growth:.1%}，"
                f"未来 {projection_years} 年线性衰减到永续 {terminal_growth_rate:.1%}"
            )
        else:
            # base ≤ terminal (mature or declining): held flat across the
            # explicit window — don't claim a decay that doesn't happen.
            prov["revenue_growth_rates"] = (
                f"过去 {n_years} 年营收 CAGR {base_growth:.1%}，"
                f"未来 {projection_years} 年按此持平（永续 {terminal_growth_rate:.1%}）"
            )
    else:
        # No reliable historical CAGR (data absent or NaN-polluted).
        # Start at industry-implied "median company growth" (2× terminal growth)
        # and decay to terminal; provenance is honest about the reason.
        base_growth = max(terminal_growth_rate * 2, 0.05)
        growth_schedule = _decay_growth_schedule(
            base_growth, terminal_growth_rate, projection_years
        )
        nan_note = "历史数据含 NaN 缺口，" if cagr is not None else "历史数据不足，"
        prov["revenue_growth_rates"] = (
            f"{nan_note}使用通用 {base_growth:.1%} 起点衰减到永续 {terminal_growth_rate:.1%}"
        )

    # ----- ebitda_margin ----------------------------------------------------
    # Cyclical: median EBITDA margin across the FULL cycle window (peak→trough→
    # recovery) — the normalized through-cycle earnings power, not the current
    # phase. Non-cyclical: unchanged trailing-3y median.
    _ebitda_suffix = "EBITDA 利润率 through-cycle 中位" if cyclical else "EBITDA 利润率中位数"
    ebitda_ticker, ebitda_value, ebitda_label = _ticker_median_with_label(
        _median_recent(historical.ebitda_margin, window=earnings_window), _ebitda_suffix
    )
    ebitda_margin, ebitda_source = _pick_with_provenance(
        ticker_value=ebitda_value,
        ticker_label=ebitda_label,
        industry_value=industry.ebitda_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    if cyclical and ebitda_ticker is not None:
        _through = _cycle_stats(historical.ebitda_margin, window=earnings_window)
        prov["ebitda_margin"] = (
            f"{ebitda_margin:.1%}（{ebitda_source}；{_cycle_note}"
            f"{_through}；大宗周期股 Damodaran 正常化口径,非近 3 年中位）"
        )
    else:
        prov["ebitda_margin"] = f"{ebitda_margin:.1%}（{ebitda_source}）"

    # ----- capex_pct_revenue -----------------------------------------------
    # Cyclical: explicit-window CapEx% over the FULL cycle (avoid anchoring on a
    # single peak/trough year's capex/revenue). Non-cyclical: trailing-3y median.
    _capex_suffix = "CapEx / 营收 through-cycle 中位" if cyclical else "CapEx / 营收 中位数"
    capex_ticker, capex_value, capex_label = _ticker_median_with_label(
        _median_ratio(historical.capital_expenditure, historical.revenue, window=earnings_window),
        _capex_suffix,
    )
    capex_pct, capex_source = _pick_with_provenance(
        ticker_value=capex_value,
        ticker_label=capex_label,
        industry_value=industry.capex_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
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
            f"{ebitda_margin:.1%}（{capex_source} {capex_pct:.1%} 收敛到 EBITDA 利润率 "
            f"{ebitda_margin:.1%}——行业聚合 CapEx 高于本公司 EBITDA，不可持续）"
        )
        capex_pct = ebitda_margin
    else:
        prov["capex_pct_revenue"] = f"{capex_pct:.1%}（{capex_source}）"

    # ----- da_pct_revenue ---------------------------------------------------
    # Cyclical: revenue-WEIGHTED through-cycle D&A% (Σ D&A / Σ revenue). D&A is a
    # sticky stock, so D&A/revenue spikes at the trough when revenue collapses
    # (MU FY2023 49.9% is a trough artifact, not the run-rate ~24%); the weighted
    # ratio down-weights that. Non-cyclical: unchanged trailing-3y per-year median.
    if cyclical:
        _da_result = _weighted_ratio(
            historical.depreciation_amortization, historical.revenue, window=earnings_window
        )
        _da_suffix = "D&A / 营收 营收加权 through-cycle"
    else:
        _da_result = _median_ratio(historical.depreciation_amortization, historical.revenue)
        _da_suffix = "D&A / 营收 中位数"
    _da_ticker, da_value, da_label = _ticker_median_with_label(_da_result, _da_suffix)
    da_pct, da_source = _pick_with_provenance(
        ticker_value=da_value,
        ticker_label=da_label,
        industry_value=industry.da_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    prov["da_pct_revenue"] = f"{da_pct:.1%}（{da_source}）"

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
            f"{capex_pct:.1%}（through-cycle CapEx {_full_capex:.1%} 收敛到维护性再投资 "
            f"min(D&A, CapEx)={da_pct:.1%}——周期股正常化:超级周期的扩张 CapEx 不进永续基底,"
            f"与终值 min(D&A,CapEx) 锚同口径）"
        )

    # ----- nwc_pct_revenue --------------------------------------------------
    # FMP changeInWorkingCapital carries the cash-flow sign: negative = NWC grew
    # = cash consumed. Negate so nwc_pct_revenue means "NWC build as % of revenue,
    # positive = cash drag" — the same convention as capex (stored absolute) — so
    # the FCF formula `- ΔNWC` reduces FCF when working capital grows.
    nwc_result = _median_ratio(historical.change_in_working_capital, historical.revenue)
    if nwc_result is not None:
        nwc_median, nwc_n = nwc_result
        nwc_pct = max(-0.10, min(0.10, -nwc_median))
        prov["nwc_pct_revenue"] = (
            f"{nwc_pct:.1%}（过去 {nwc_n} 年 ΔNWC / 营收 中位数，正=占用现金）"
        )
    else:
        nwc_pct = 0.01
        prov["nwc_pct_revenue"] = "1.0%（历史不可得，按通用基准）"

    # ----- terminal_nwc_pct_revenue ------------------------------------------
    # The explicit-window ΔNWC/revenue median embeds the HISTORICAL growth rate
    # (NWC build ≈ marginal NWC ratio × Δrevenue), so holding it into a 3%
    # perpetuity overstates the drag ~7x for a 20% grower (AMD: 8.1% → 1.4%) —
    # and, mirrored, props up cash burners on a perpetual NWC subsidy (RIVN:
    # −10% forever printed a 1.57x-market fair value). Steady state re-derives
    # it from the marginal ratio: median(ΔNWC_build / Δrevenue) over revenue-
    # GROWTH years × terminal growth. No usable growth years → None, and
    # _terminal_fcf falls back to the explicit-window value (honest: don't
    # pretend to have computed a scaling the data can't support).
    terminal_nwc = _terminal_nwc_pct(
        historical.change_in_working_capital, historical.revenue, terminal_growth_rate
    )
    if terminal_nwc is not None:
        marginal_ratio, terminal_nwc_pct = terminal_nwc
        prov["terminal_nwc_pct_revenue"] = (
            f"{terminal_nwc_pct:.2%}（边际 NWC 比率 median(ΔNWC/Δ营收) "
            f"{marginal_ratio:.1%} × 永续增长 {terminal_growth_rate:.1%}）"
        )
    else:
        terminal_nwc_pct = None
        prov["terminal_nwc_pct_revenue"] = f"沿用 {nwc_pct:.1%}（无营收增长年可推边际 NWC 比率）"

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
    if company_tax is not None:
        tax_rate = company_tax
        prov["tax_rate"] = f"{tax_rate:.1%}（最新财报有效税率 = 所得税 / 税前利润）"
    else:
        tax_rate = industry.effective_tax_rate
        prov["tax_rate"] = (
            f"{tax_rate:.1%}（{industry.industry} 行业实际有效税率——财报无可用税项/税前为负）"
        )

    # ----- WACC components --------------------------------------------------
    # Beta: prefer provider-reported beta, fall back to industry levered beta,
    # then apply the Blume/Bloomberg adjustment (2/3·β + 1/3·1.0). A raw 5y
    # regression beta is a noisy estimate of the FORWARD beta and empirically
    # mean-reverts toward 1.0; using it unadjusted put NVDA's 2.24 into a 16.6%
    # CAPM cost of equity — a discount rate no analyst applies to a mega-cap.
    raw_beta, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider 报告 5y beta",
        industry_value=industry.levered_beta,
        industry_label=f"{industry.industry} 行业 levered beta",
    )
    beta_chosen = adjust_beta_blume(raw_beta)
    prov["beta"] = (
        f"{beta_chosen:.2f}（{beta_source} {raw_beta:.2f} 经 Blume 调整 2/3·β+1/3·1.0 向 1.0 收敛）"
    )

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
                f"{cost_of_debt:.1%}（利息支出 / 总债务 = {raw_rate:.2%}，已夹至下限 "
                f"{COST_OF_DEBT_FLOOR:.0%}）"
            )
        elif raw_rate > COST_OF_DEBT_CAP:
            prov["cost_of_debt"] = (
                f"{cost_of_debt:.1%}（利息支出 / 总债务 = {raw_rate:.1%}，已夹至上限 "
                f"{COST_OF_DEBT_CAP:.0%}）"
            )
        else:
            prov["cost_of_debt"] = f"{cost_of_debt:.1%}（最新利息支出 / 总债务）"
    else:
        cost_of_debt = DEFAULT_COST_OF_DEBT
        prov["cost_of_debt"] = f"{cost_of_debt:.1%}（投资级公司债基准）"

    # Debt ratio: from current market cap + total debt.
    market_cap = financials.market.market_cap if financials.market else 0
    if total_debt is not None and total_debt > 0 and market_cap > 0:
        debt_ratio = total_debt / (total_debt + market_cap)
        prov["debt_ratio"] = (
            f"{debt_ratio:.1%}（总债务 ${total_debt / 1e9:.1f}B / "
            f"(债务+市值 ${market_cap / 1e9:.1f}B)）"
        )
    else:
        debt_ratio = industry.debt_ratio
        prov["debt_ratio"] = f"{debt_ratio:.1%}（{industry.industry} 行业 D/(D+E)）"

    prov["risk_free_rate"] = f"{risk_free_rate:.1%}（当前 10 年期美债收益率）"
    prov["equity_risk_premium"] = f"{equity_risk_premium:.1%}（Damodaran 隐含 ERP）"
    prov["terminal_growth_rate"] = f"{terminal_growth_rate:.1%}（长期美国名义 GDP 增速）"

    # ----- Balance items ----------------------------------------------------
    shares_outstanding = financials.market.shares_outstanding
    prov["shares_outstanding"] = f"当前流通股本 {shares_outstanding / 1e9:.2f}B 股"

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
        missing = " 和 ".join(
            label for label, value in (("总债务", total_debt), ("现金", raw_cash)) if value is None
        )
        prov["net_debt"] = (
            f"${net_debt / 1e9:+.1f}B（{missing}未披露，缺失项按 0 处理 — 净债务可能被低估）"
        )
    else:
        prov["net_debt"] = (
            f"${net_debt / 1e9:+.1f}B "
            f"（总债务 - 现金 = {nd_debt / 1e9:.1f}B - {nd_cash / 1e9:.1f}B）"
        )

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
        da_pct_revenue=max(0.005, min(0.40, da_pct)),
        tax_rate=max(0.05, min(0.40, tax_rate)),
        risk_free_rate=risk_free_rate,
        beta=max(0.3, min(2.5, beta_chosen)),
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


# ---------------------------------------------------------------------------
# Small helpers — last so they stay near caller sites
# ---------------------------------------------------------------------------


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
        f"（峰 {max(usable):.1%} / 谷 {min(usable):.1%} / 中位 "
        f"{statistics.median(usable):.1%} / 均值 {statistics.mean(usable):.1%}，"
        f"{len(usable)} 年）"
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
        return None, None, f"过去 {_MEDIAN_WINDOW_YEARS} 年 {suffix}"
    value, count = result
    return result, value, f"过去 {count} 年 {suffix}"


def _pick_with_provenance(
    *,
    ticker_value: float | None,
    ticker_label: str,
    industry_value: float,
    industry_label: str,
    floor: float = 0.0,
) -> tuple[float, str]:
    """Pick ticker_value when reasonable, else industry_value. Return (value, source_label)."""
    if ticker_value is not None and ticker_value > floor:
        return ticker_value, ticker_label
    return industry_value, industry_label


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
) -> tuple[float, float] | None:
    """Steady-state ΔNWC as % of revenue: median(ΔNWC_build/Δrevenue) × tg.

    The marginal ratio is taken over revenue-GROWTH years only — ΔNWC/Δrev is
    meaningless when revenue shrank (negative denominator flips the sign of an
    economically identical build). FMP changeInWorkingCapital carries the
    cash-flow sign (negative = NWC grew = cash consumed), so build = −value,
    matching the nwc_pct_revenue convention above.

    Returns ``(marginal_ratio, terminal_pct)`` for provenance, or None when no
    usable growth year exists (declining/flat revenue history, NaN-polluted
    rows) — the caller then leaves terminal_nwc_pct_revenue unset and the
    perpetuity falls back to the explicit-window ΔNWC ratio.
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
    marginal = max(
        -_MARGINAL_NWC_RATIO_CLAMP, min(_MARGINAL_NWC_RATIO_CLAMP, statistics.median(ratios))
    )
    terminal = max(-_TERMINAL_NWC_CLAMP, min(_TERMINAL_NWC_CLAMP, marginal * terminal_growth))
    return marginal, terminal
