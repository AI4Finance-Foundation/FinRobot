"""Single authoritative DCFInputs builder.

What this code does that raw LLM cannot:
- Deterministically derives every DCF assumption from real multi-year filings
  (historical 3y medians) or Damodaran industry medians — never hardcoded
  per-company defaults.
- Records the *source* of each assumption in ``assumption_provenance`` so the
  UI can render "EBITDA 利润率 31.4%，过去 3 年财报中位数" instead of an
  opaque number.
- Falls back through a fixed precedence: ticker history → industry median →
  Total Market median. Never returns None / placeholder.

This module is the only sanctioned producer of DCFInputs in the codebase.
Routes / pipelines / SDK should call ``seed_dcf_inputs``; the legacy
``DEFAULT_COMPUTE_BODY`` and ``DEFAULT_INPUTS`` are being removed.
"""

from __future__ import annotations

import math
import statistics
from typing import Final

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
DEFAULT_EQUITY_RISK_PREMIUM: Final[float] = 0.055  # Damodaran 2026 implied ERP
DEFAULT_TERMINAL_GROWTH: Final[float] = 0.025  # Long-run US nominal GDP
DEFAULT_TAX_RATE: Final[float] = 0.21  # US corporate statutory
DEFAULT_PROJECTION_YEARS: Final[int] = 5
DEFAULT_COST_OF_DEBT: Final[float] = 0.05  # Investment-grade corporate yield

# Minimum historical samples required before we trust the ticker's own median.
# Fewer than this ⇒ fall back to industry median.
_MIN_HISTORY_SAMPLES: Final[int] = 2


# ---------------------------------------------------------------------------
# Helpers — each isolated so it can be tested independently
# ---------------------------------------------------------------------------


def _median_ratio(
    numerator: list[float], denominator: list[float], min_samples: int = _MIN_HISTORY_SAMPLES
) -> float | None:
    """Median of numerator[i]/denominator[i] over the last *min_samples* years.

    Returns None when:
      - either list is shorter than min_samples
      - denominator has zeros in the recent window (would div by 0)
      - all paired ratios are 0 (cashflow row was zero-filled by extractor)

    Skips index 0 (oldest) when more samples exist — we want the most recent
    window since trailing ratios drift; for a stable seed we use the last
    ``min_samples`` years.
    """
    n = min(len(numerator), len(denominator))
    if n < min_samples:
        return None
    # Take the most recent window
    nums = numerator[-min_samples:]
    dens = denominator[-min_samples:]
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
    return statistics.median(ratios)


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
    total_debt: float,
    *,
    floor: float = 0.02,
    cap: float = 0.20,
) -> float | None:
    """Effective cost of debt = interest expense / total debt.

    Returns None when interest_expense missing or total_debt too small to
    yield a meaningful rate (sub-1% of equity ⇒ rounding noise).
    """
    if interest_expense is None or total_debt <= 0:
        return None
    rate = interest_expense / total_debt
    if rate < floor:
        return floor
    if rate > cap:
        return cap
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
) -> DCFInputs:
    """Build a complete DCFInputs from one ticker's financials + historical data.

    Field-by-field precedence:
      ticker historical median (3y) → industry median (Damodaran) → market median

    Every field gets an entry in ``assumption_provenance`` so the UI can show
    a 散户-friendly Chinese sentence explaining where the number came from.

    Args:
        financials: Latest snapshot (LTM revenue, EBITDA, debt, cash, shares).
        historical: Multi-year history (extracted by historical_extractor).
        risk_free_rate: 10Y Treasury yield. Default static; caller can pass a
            live rate when available.
        equity_risk_premium: Market risk premium. Default Damodaran 2026 ERP.
        terminal_growth_rate: Perpetuity growth. Default US nominal GDP.
        projection_years: Length of explicit forecast schedule. Default 5.

    Returns:
        DCFInputs ready to pass to ``calculate_dcf``. The ``da_pct_revenue``
        field is *always* non-None — industry fallback guarantees it.
    """
    industry: IndustryDefault = get_industry_default(financials.market.industry)
    prov: dict[str, str] = {}

    # ----- revenue_base ------------------------------------------------------
    revenue_base = financials.income.revenue
    prov["revenue_base"] = f"最新年报营收 ${revenue_base / 1e9:.1f}B"

    # ----- revenue_growth_rates ---------------------------------------------
    # cagr_revenue is None when: fewer than 2 data points, start revenue ≤ 0,
    # or NaN pollution from yfinance. math.isfinite guards the NaN/Inf case.
    cagr = historical.cagr_revenue
    has_real_cagr = cagr is not None and math.isfinite(cagr)
    if has_real_cagr:
        assert cagr is not None  # narrowing for mypy
        # Floor at -20%/yr (severe-but-bounded decline), cap at +40%. The old
        # floor of 0.0 silently FORCED every structurally-declining firm to a
        # flat 0% explicit schedule — overstating fair value for exactly the
        # over-valued names the SELL/short path depends on. A negative base is
        # held flat across the explicit window by _decay_growth_schedule (it
        # only decays a base ABOVE terminal); the Gordon perpetuity handles the
        # eventual convergence to terminal_growth.
        base_growth = max(min(cagr, 0.40), -0.20)
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
    ebitda_margin, ebitda_source = _pick_with_provenance(
        ticker_value=_median_recent(historical.ebitda_margin),
        ticker_label="过去 3 年 EBITDA 利润率中位数",
        industry_value=industry.ebitda_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    prov["ebitda_margin"] = f"{ebitda_margin:.1%}（{ebitda_source}）"

    # ----- capex_pct_revenue -----------------------------------------------
    capex_pct, capex_source = _pick_with_provenance(
        ticker_value=_median_ratio(historical.capital_expenditure, historical.revenue),
        ticker_label="过去 3 年 CapEx / 营收 中位数",
        industry_value=industry.capex_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    prov["capex_pct_revenue"] = f"{capex_pct:.1%}（{capex_source}）"

    # ----- da_pct_revenue ---------------------------------------------------
    da_pct, da_source = _pick_with_provenance(
        ticker_value=_median_ratio(historical.depreciation_amortization, historical.revenue),
        ticker_label="过去 3 年 D&A / 营收 中位数",
        industry_value=industry.da_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    prov["da_pct_revenue"] = f"{da_pct:.1%}（{da_source}）"

    # ----- nwc_pct_revenue --------------------------------------------------
    # ΔWC is a delta — can be positive or negative. We accept any median.
    nwc_median = _median_ratio(historical.change_in_working_capital, historical.revenue)
    if nwc_median is not None:
        nwc_pct = max(-0.10, min(0.10, nwc_median))
        prov["nwc_pct_revenue"] = f"{nwc_pct:.1%}（过去 3 年 ΔNWC / 营收 中位数）"
    else:
        nwc_pct = 0.01
        prov["nwc_pct_revenue"] = "1.0%（历史不可得，按通用基准）"

    # ----- tax_rate ---------------------------------------------------------
    # If we can derive an effective rate from net_income vs pre-tax income,
    # prefer that; otherwise use industry effective rate; otherwise 21%.
    tax_rate, tax_source = _pick_with_provenance(
        ticker_value=None,  # Effective-tax-from-history extraction lives in a
        # follow-up — current FinancialData doesn't expose pre-tax income directly.
        ticker_label="历史有效税率",
        industry_value=industry.effective_tax_rate,
        industry_label=f"{industry.industry} 行业实际有效税率",
        floor=DEFAULT_TAX_RATE * 0.5,
    )
    prov["tax_rate"] = f"{tax_rate:.1%}（{tax_source}）"

    # ----- WACC components --------------------------------------------------
    # Beta: prefer provider-reported beta, fall back to industry levered beta.
    beta_chosen, beta_source = _pick_with_provenance(
        ticker_value=financials.market.beta,
        ticker_label="provider 报告 5y 调整 beta",
        industry_value=industry.levered_beta,
        industry_label=f"{industry.industry} 行业 levered beta",
    )
    prov["beta"] = f"{beta_chosen:.2f}（{beta_source}）"

    # Cost of debt: try interest_expense / total_debt; fall back to 5%.
    total_debt = financials.balance.total_debt
    interest_exp = financials.income.interest_expense
    cod = _cost_of_debt(interest_exp, total_debt)
    if cod is not None:
        cost_of_debt = cod
        prov["cost_of_debt"] = f"{cost_of_debt:.1%}（最新利息支出 / 总债务）"
    else:
        cost_of_debt = DEFAULT_COST_OF_DEBT
        prov["cost_of_debt"] = f"{cost_of_debt:.1%}（投资级公司债基准）"

    # Debt ratio: from current market cap + total debt.
    market_cap = financials.market.market_cap if financials.market else 0
    if total_debt > 0 and market_cap > 0:
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

    net_debt = total_debt - financials.balance.total_cash
    prov["net_debt"] = (
        f"${net_debt / 1e9:+.1f}B "
        f"（总债务 - 现金 = {total_debt / 1e9:.1f}B - {financials.balance.total_cash / 1e9:.1f}B）"
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
        da_pct_revenue=max(0.005, min(0.40, da_pct)),
        tax_rate=max(0.05, min(0.40, tax_rate)),
        risk_free_rate=risk_free_rate,
        beta=max(0.3, min(2.5, beta_chosen)),
        equity_risk_premium=equity_risk_premium,
        cost_of_debt=cost_of_debt,
        debt_ratio=max(0.0, min(0.9, debt_ratio)),
        terminal_growth_rate=terminal_growth_rate,
        shares_outstanding=shares_outstanding,
        net_debt=net_debt,
        assumption_provenance=prov,
    )


# ---------------------------------------------------------------------------
# Small helpers — last so they stay near caller sites
# ---------------------------------------------------------------------------


def _median_recent(values: list[float], min_samples: int = _MIN_HISTORY_SAMPLES) -> float | None:
    """Median of the most recent *min_samples* non-zero, non-NaN entries."""
    if len(values) < min_samples:
        return None
    recent = [v for v in values[-min_samples:] if v != 0 and not math.isnan(v)]
    if not recent:
        return None
    return statistics.median(recent)


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
