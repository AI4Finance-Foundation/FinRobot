"""Single authoritative LBOInputs builder.

What this code does that raw LLM cannot:
- Deterministically derives every LBO assumption from real multi-year filings
  (historical 3y medians) or Damodaran industry medians — never hardcoded
  per-company defaults shipped from the frontend.
- Records the *source* of each assumption in ``assumption_provenance`` so the
  UI can render "EBITDA 利润率 31.4%，过去 3 年财报中位数" instead of an opaque
  number, identical to the DCF seed UX.
- Falls back through a fixed precedence: ticker history → industry median →
  Total Market median / standard PE convention. Never returns None.

Mirror of ``dcf_seed.seed_dcf_inputs`` for the LBO path. Routes / pipelines /
SDK / UI must call ``seed_lbo_inputs``; direct construction of ``LBOInputs``
with hardcoded numerics is a red-line violation enforced by
``tests/audit/test_lbo_red_lines.py``.

Deal-structure constants (entry/exit multiples, leverage, holding period,
interest rate, mandatory amort) follow standard PE convention because they
are not financial-statement quantities. They are recorded in provenance so
the user can see they came from convention rather than a coin flip.
"""

from __future__ import annotations

from typing import Final

from finrobot.engine.compute.dcf_seed import (
    _cost_of_debt,
    _median_ratio,
    _median_recent,
    _pick_with_provenance,
)
from finrobot.engine.data.industry_defaults import (
    IndustryDefault,
    get_industry_default,
)
from finrobot.engine.models.financial import (
    FinancialData,
    HistoricalMetrics,
    LBOInputs,
)

# Standard PE-convention defaults — refreshed against Rosenbaum & Pearl,
# "Investment Banking" 3rd Ed., Chapter 8 (LBO benchmarks).
DEFAULT_ENTRY_EV_EBITDA: Final[float] = 8.0  # Mid-market median 2023-2025
DEFAULT_EXIT_EV_EBITDA: Final[float] = 8.0  # Conservative — no multiple expansion
DEFAULT_LEVERAGE_MULTIPLE: Final[float] = 5.0  # Net Debt / EBITDA at entry
DEFAULT_HOLDING_PERIOD: Final[int] = 5
DEFAULT_INTEREST_RATE: Final[float] = 0.07  # Blended LBO-loan + HY bond rate
DEFAULT_MANDATORY_AMORT: Final[float] = 0.05  # 5% / yr typical Term Loan B
DEFAULT_NWC_PCT_REVENUE: Final[float] = 0.01  # Conservative working-capital drag


def seed_lbo_inputs(
    financials: FinancialData,
    historical: HistoricalMetrics,
    *,
    holding_period_years: int = DEFAULT_HOLDING_PERIOD,
    entry_ev_ebitda: float = DEFAULT_ENTRY_EV_EBITDA,
    exit_ev_ebitda: float = DEFAULT_EXIT_EV_EBITDA,
    leverage_multiple: float = DEFAULT_LEVERAGE_MULTIPLE,
) -> LBOInputs:
    """Build a complete LBOInputs from one ticker's financials + historical data.

    Field-by-field precedence:
      ticker historical median (3y) → industry median (Damodaran) → convention

    Every operational field (margins, capex, growth, tax) gets an entry in
    ``assumption_provenance``. Deal-structure fields (multiples, leverage,
    holding period) also get entries marked as "PE 行业惯例" so the UI shows
    the user where each number came from.

    Args:
        financials: Latest snapshot (LTM revenue, EBITDA, debt, cash).
        historical: Multi-year history (extracted by historical_extractor).
        holding_period_years: Investment horizon. Default 5y per PE convention.
        entry_ev_ebitda: Override entry multiple (e.g. when user knows a
            specific deal multiple). Default 8.0x.
        exit_ev_ebitda: Override exit multiple. Default 8.0x (no expansion).
        leverage_multiple: Total Debt / EBITDA at entry. Default 5.0x.

    Returns:
        LBOInputs ready to pass to ``calculate_lbo``.
    """
    industry: IndustryDefault = get_industry_default(financials.market.industry)
    prov: dict[str, str] = {}

    # ----- revenue_base ------------------------------------------------------
    revenue_base = financials.income.revenue
    prov["revenue_base"] = f"最新年报营收 ${revenue_base / 1e9:.1f}B"

    # ----- ltm_ebitda --------------------------------------------------------
    ltm_ebitda = financials.income.ebitda
    if ltm_ebitda <= 0:
        # LBO model requires positive EBITDA — fall back to industry-implied
        # value via revenue × industry EBITDA margin. Prov flag this clearly.
        ltm_ebitda = max(revenue_base * industry.ebitda_pct_revenue, 1.0)
        prov["ltm_ebitda"] = (
            f"${ltm_ebitda / 1e9:.1f}B（最新 EBITDA 不可得，按"
            f" {industry.industry} 行业 EBITDA 利润率 {industry.ebitda_pct_revenue:.1%} 估算）"
        )
    else:
        prov["ltm_ebitda"] = f"最新年报 EBITDA ${ltm_ebitda / 1e9:.1f}B"

    # ----- revenue_growth_rate (constant for LBO model) ---------------------
    # LBO assumes a single steady-state growth rate. Take historical 3y CAGR
    # clamped to a realistic PE underwriting band [0%, 15%].
    if historical.cagr_revenue is not None:
        raw_growth = historical.cagr_revenue
        revenue_growth_rate = max(0.0, min(0.15, raw_growth))
        n_years = len(historical.years)
        prov["revenue_growth_rate"] = (
            f"{revenue_growth_rate:.1%}（过去 {n_years} 年营收 CAGR {raw_growth:.1%}，"
            f"夹紧到 PE 承销区间 0%-15%）"
        )
    else:
        revenue_growth_rate = 0.05
        prov["revenue_growth_rate"] = "5.0%（历史增长率不可得，按 PE 行业承销基准）"

    # ----- ebitda_margin ----------------------------------------------------
    ebitda_margin, ebitda_source = _pick_with_provenance(
        ticker_value=_median_recent(historical.ebitda_margin),
        ticker_label="过去 3 年 EBITDA 利润率中位数",
        industry_value=industry.ebitda_pct_revenue,
        industry_label=f"{industry.industry} 行业中位数",
    )
    prov["ebitda_margin"] = f"{ebitda_margin:.1%}（{ebitda_source}）"

    # ----- capex_pct_revenue ------------------------------------------------
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

    # ----- nwc_change_pct_revenue -------------------------------------------
    nwc_median = _median_ratio(historical.change_in_working_capital, historical.revenue)
    if nwc_median is not None:
        nwc_pct = max(-0.10, min(0.10, nwc_median))
        prov["nwc_change_pct_revenue"] = (
            f"{nwc_pct:.1%}（过去 3 年 ΔNWC / 营收 中位数）"
        )
    else:
        nwc_pct = DEFAULT_NWC_PCT_REVENUE
        prov["nwc_change_pct_revenue"] = (
            f"{nwc_pct:.1%}（历史不可得，按 PE 承销基准）"
        )

    # ----- tax_rate ---------------------------------------------------------
    tax_rate = max(0.10, min(0.40, industry.effective_tax_rate))
    prov["tax_rate"] = (
        f"{tax_rate:.1%}（{industry.industry} 行业实际有效税率）"
    )

    # ----- interest_rate ---------------------------------------------------
    # LBO debt is typically TLB + HY-bond mix. Prefer the company's effective
    # rate if visible (interest expense / total debt), else PE-loan convention.
    cod = _cost_of_debt(
        financials.income.interest_expense,
        financials.balance.total_debt,
        floor=0.04,
        cap=0.15,
    )
    if cod is not None:
        # Pad slightly — LBO debt is typically more expensive than the
        # company's current investment-grade or hybrid mix.
        interest_rate = min(0.15, cod + 0.02)
        prov["interest_rate"] = (
            f"{interest_rate:.1%}（公司当前实际成本 {cod:.1%} + LBO 风险溢价 2%）"
        )
    else:
        interest_rate = DEFAULT_INTEREST_RATE
        prov["interest_rate"] = (
            f"{interest_rate:.1%}（PE LBO 杠杆贷款 + 高收益债综合基准）"
        )

    # ----- Deal structure (PE convention; recorded for transparency) -------
    prov["entry_ev_ebitda"] = (
        f"{entry_ev_ebitda:.1f}× EBITDA（PE 中端市场 LBO 入场倍数惯例）"
    )
    prov["exit_ev_ebitda"] = (
        f"{exit_ev_ebitda:.1f}× EBITDA（保守假设，无倍数扩张）"
    )
    prov["leverage_multiple"] = (
        f"{leverage_multiple:.1f}× EBITDA（PE LBO 总债务 / EBITDA 行业基准）"
    )
    prov["holding_period_years"] = (
        f"{holding_period_years} 年（PE 持有期惯例）"
    )
    prov["mandatory_amort_pct"] = (
        f"{DEFAULT_MANDATORY_AMORT:.1%}（Term Loan B 强制摊销率惯例）"
    )

    return LBOInputs(
        ticker=financials.ticker,
        ltm_ebitda=ltm_ebitda,
        entry_ev_ebitda=entry_ev_ebitda,
        exit_ev_ebitda=exit_ev_ebitda,
        holding_period_years=holding_period_years,
        revenue_base=revenue_base,
        revenue_growth_rate=revenue_growth_rate,
        ebitda_margin=max(0.01, min(0.95, ebitda_margin)),
        da_pct_revenue=max(0.0, min(0.3, da_pct)),
        capex_pct_revenue=max(0.0, min(0.5, capex_pct)),
        nwc_change_pct_revenue=max(-0.2, min(0.3, nwc_pct)),
        leverage_multiple=max(0.0, min(20.0, leverage_multiple)),
        interest_rate=max(0.0, min(0.5, interest_rate)),
        mandatory_amort_pct=DEFAULT_MANDATORY_AMORT,
        cash_sweep=True,
        tax_rate=tax_rate,
        assumption_provenance=prov,
    )


__all__ = ["seed_lbo_inputs"]
