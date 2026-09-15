"""Single authoritative LBOInputs builder.

What this code does that raw LLM cannot:
- Deterministically derives every LBO assumption from real multi-year filings
  (historical medians over the most recent ``_MEDIAN_WINDOW_YEARS`` years) or
  Damodaran industry medians — never hardcoded per-company defaults shipped
  from the frontend. Provenance reports the actual sample count, not the window.
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

from finrobot.engine.compute.operators.dcf_seed import (
    _cost_of_debt,
    _disclose_construction_clamp,
    _median_ratio,
    _median_recent,
    _pick_with_provenance,
    _terminal_nwc_pct,
    _ticker_median_with_label,
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
from finrobot.engine.primitives.industry import (
    commodity_cyclical_basis,
    is_commodity_cyclical,
)

# Standard PE-convention defaults — refreshed against Rosenbaum & Pearl,
# "Investment Banking" 3rd Ed., Chapter 8 (LBO benchmarks).
DEFAULT_ENTRY_EV_EBITDA: Final[float] = 8.0  # Mid-market median 2023-2025
DEFAULT_EXIT_EV_EBITDA: Final[float] = 8.0  # Conservative — no multiple expansion
DEFAULT_LEVERAGE_MULTIPLE: Final[float] = 5.0  # Total (gross) Debt / EBITDA at entry
DEFAULT_HOLDING_PERIOD: Final[int] = 5
DEFAULT_INTEREST_RATE: Final[float] = 0.07  # Blended LBO-loan + HY bond rate
DEFAULT_MANDATORY_AMORT: Final[float] = 0.05  # 5% / yr typical Term Loan B
DEFAULT_NWC_PCT_REVENUE: Final[float] = 0.01  # Conservative working-capital drag
# LBO tax rate is clamped into this band: below it a near-zero industry aggregate
# overstates the debt tax shield; above it an outlier rate understates levered FCF.
# When the clamp binds it is disclosed in provenance so the displayed rate is never
# implied to be the raw industry figure (same honesty convention as BUG-023).
LBO_TAX_RATE_FLOOR: Final[float] = 0.10
LBO_TAX_RATE_CAP: Final[float] = 0.40


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
      ticker historical median (most recent _MEDIAN_WINDOW_YEARS, default 3y) →
      industry median (Damodaran) → convention

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
    # Label the basis HONESTLY: revenue/ebitda are the canonical financials'
    # figures, which are TTM by default (not annual). Mislabeling TTM as "annual"
    # is exactly the口径 error the project forbids — dcf_seed already reads
    # ``provenance.period_basis`` here; mirror it instead of hardcoding "annual".
    _basis = financials.provenance.period_basis if financials.provenance else "ttm"
    _basis_word = {
        "ttm": "TTM",
        "annual": "annual",
        "quarterly": "quarterly (annualized)",
    }.get(_basis, _basis)
    revenue_base = financials.income.revenue
    prov["revenue_base"] = f"latest {_basis_word} revenue ${revenue_base / 1e9:.1f}B"

    # ----- ltm_ebitda --------------------------------------------------------
    ltm_ebitda = financials.income.ebitda
    if ltm_ebitda is None or ltm_ebitda <= 0:
        # LBO model requires positive EBITDA — when missing (None) or
        # non-positive, fall back to industry-implied value via
        # revenue × industry EBITDA margin. Prov flag this clearly.
        ltm_ebitda_note = (
            "latest EBITDA unavailable"
            if ltm_ebitda is None
            else f"latest EBITDA ${ltm_ebitda / 1e9:.1f}B is non-positive"
        )
        ltm_ebitda = max(revenue_base * industry.ebitda_pct_revenue, 1.0)
        prov["ltm_ebitda"] = (
            f"${ltm_ebitda / 1e9:.1f}B ({ltm_ebitda_note};"
            f" estimated at the {industry.industry} industry EBITDA margin {industry.ebitda_pct_revenue:.1%})"
        )
    else:
        prov["ltm_ebitda"] = f"latest {_basis_word} EBITDA ${ltm_ebitda / 1e9:.1f}B"

    # ----- revenue_growth_rate (constant for LBO model) ---------------------
    # LBO assumes a single steady-state growth rate. Take historical 3y CAGR
    # clamped to a realistic PE underwriting band [0%, 15%].
    if historical.cagr_revenue is not None:
        raw_growth = historical.cagr_revenue
        revenue_growth_rate = max(0.0, min(0.15, raw_growth))
        n_years = len(historical.years)
        prov["revenue_growth_rate"] = (
            f"{revenue_growth_rate:.1%} (trailing {n_years}yr revenue CAGR {raw_growth:.1%}, "
            f"clamped to the PE underwriting band 0%-15%)"
        )
    else:
        revenue_growth_rate = 0.05
        prov["revenue_growth_rate"] = (
            "5.0% (historical growth rate unavailable; PE industry underwriting benchmark)"
        )

    # ----- ebitda_margin ----------------------------------------------------
    _ebitda_ticker, ebitda_value, ebitda_label = _ticker_median_with_label(
        _median_recent(historical.ebitda_margin), "median EBITDA margin"
    )
    ebitda_margin, ebitda_source = _pick_with_provenance(
        ticker_value=ebitda_value,
        ticker_label=ebitda_label,
        industry_value=industry.ebitda_pct_revenue,
        industry_label=f"{industry.industry} industry median",
        rejected_ticker_reason="non-positive; loss-making / missing-EBITDA years are not used as the LBO normalized margin",
    )
    prov["ebitda_margin"] = f"{ebitda_margin:.1%} ({ebitda_source})"

    # ----- capex_pct_revenue ------------------------------------------------
    _capex_ticker, capex_value, capex_label = _ticker_median_with_label(
        _median_ratio(historical.capital_expenditure, historical.revenue), "median CapEx / revenue"
    )
    capex_pct, capex_source = _pick_with_provenance(
        ticker_value=capex_value,
        ticker_label=capex_label,
        industry_value=industry.capex_pct_revenue,
        industry_label=f"{industry.industry} industry median",
    )
    prov["capex_pct_revenue"] = f"{capex_pct:.1%} ({capex_source})"

    # ----- da_pct_revenue ---------------------------------------------------
    _da_ticker, da_value, da_label = _ticker_median_with_label(
        _median_ratio(historical.depreciation_amortization, historical.revenue),
        "median D&A / revenue",
    )
    da_pct, da_source = _pick_with_provenance(
        ticker_value=da_value,
        ticker_label=da_label,
        industry_value=industry.da_pct_revenue,
        industry_label=f"{industry.industry} industry median",
    )
    prov["da_pct_revenue"] = f"{da_pct:.1%} ({da_source})"

    # ----- nwc_change_pct_revenue -------------------------------------------
    # FMP changeInWorkingCapital carries the cash-flow sign (negative = NWC grew =
    # cash consumed). Negate so nwc_change_pct_revenue is positive when working
    # capital grows with revenue, matching the LBO FCF formula `- ΔNWC`.
    #
    # Mirror of the dcf_seed fix: a trailing |median| > 10% is a pollution signal
    # (KO's non-core otherWorkingCapital swings), not real NWC economics. When the
    # ±10% clamp binds and a marginal ratio is derivable, degrade to marginal
    # ratio × the LBO's single steady-state revenue growth — the same marginal × g
    # form dcf_seed uses, with the LBO's constant growth rate in place of the DCF
    # explicit-window schedule (the model's holding period is level-growth). No
    # revenue-growth year → honest fallback to the clamped median.
    nwc_marginal = _terminal_nwc_pct(
        historical.change_in_working_capital, historical.revenue, revenue_growth_rate
    )
    nwc_result = _median_ratio(historical.change_in_working_capital, historical.revenue)
    if nwc_result is not None:
        nwc_median, nwc_n = nwc_result
        raw_nwc = -nwc_median
        clamped_median = max(-0.10, min(0.10, raw_nwc))
        if clamped_median != raw_nwc and nwc_marginal is not None:
            marginal_ratio, _terminal_pct, raw_marginal = nwc_marginal
            degraded = marginal_ratio * revenue_growth_rate
            nwc_pct = max(-0.10, min(0.10, degraded))
            # Analyst-facing prose (BACKLOG A6⑤, mirrors dcf_seed) — every
            # number is unchanged, only the wording. The structured
            # `nwc_clamped` flag drives the report's ⚠; this string is only
            # ever displayed verbatim, never parsed.
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
            prov["nwc_change_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (re-derived: the trailing {nwc_n}-year average "
                f"change in working capital ran {raw_nwc:.1%} of revenue — too high to be a "
                f"sustainable, ongoing drag, so the model instead ties the assumption to the "
                f"marginal NWC ratio, {marginal_note}, applied to the "
                f"{revenue_growth_rate:.1%} steady-state revenue growth rate{reclamp_note}; a "
                f"positive figure means working capital is absorbing cash)"
            )
        elif clamped_median != raw_nwc:
            # Clamp binds but no revenue-growth year to derive a marginal ratio →
            # honest fallback: keep the clamped median and disclose the pre-clamp
            # value (batch-0 BUG-023 disclosure; never imply the band value IS the
            # median).
            nwc_pct = clamped_median
            prov["nwc_change_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (capped from a trailing {nwc_n}-year average of "
                f"{raw_nwc:.1%} of revenue — too high to be a sustainable, ongoing drag; a "
                f"positive figure means working capital is absorbing cash)"
            )
        else:
            nwc_pct = clamped_median
            prov["nwc_change_pct_revenue"] = (
                f"{nwc_pct:.1%} of revenue (trailing {nwc_n}-year average change in working "
                f"capital as % of revenue; a positive figure means working capital is "
                f"absorbing cash)"
            )
    else:
        nwc_pct = DEFAULT_NWC_PCT_REVENUE
        prov["nwc_change_pct_revenue"] = (
            f"{nwc_pct:.1%} of revenue (no working-capital history available; PE "
            f"underwriting benchmark applied)"
        )

    # ----- tax_rate ---------------------------------------------------------
    # Clamp the industry rate into [floor, cap], then disclose the floor/cap when
    # it binds so the displayed rate is never implied to be the raw industry value
    # (BUG-023 honesty convention — displayed == used, with the raw figure surfaced).
    raw_industry_tax = industry.effective_tax_rate
    tax_rate = max(LBO_TAX_RATE_FLOOR, min(LBO_TAX_RATE_CAP, raw_industry_tax))
    if raw_industry_tax < LBO_TAX_RATE_FLOOR:
        prov["tax_rate"] = (
            f"{tax_rate:.1%} ({industry.industry} industry effective tax rate {raw_industry_tax:.1%}, "
            f"clamped to the {LBO_TAX_RATE_FLOOR:.0%} floor)"
        )
    elif raw_industry_tax > LBO_TAX_RATE_CAP:
        prov["tax_rate"] = (
            f"{tax_rate:.1%} ({industry.industry} industry effective tax rate {raw_industry_tax:.1%}, "
            f"clamped to the {LBO_TAX_RATE_CAP:.0%} cap)"
        )
    else:
        prov["tax_rate"] = f"{tax_rate:.1%} ({industry.industry} industry effective tax rate)"

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
        raw_interest = cod + 0.02
        interest_rate = min(0.15, raw_interest)
        if interest_rate != raw_interest:
            # Cap bound: disclose so the "cost + 2%" arithmetic in provenance
            # cannot imply a rate above the 15% ceiling the model uses (BUG-023).
            prov["interest_rate"] = (
                f"{interest_rate:.1%} (company's current actual cost {cod:.1%} + LBO risk "
                f"premium 2% = {raw_interest:.1%}, capped at the 15% LBO-debt ceiling)"
            )
        else:
            prov["interest_rate"] = (
                f"{interest_rate:.1%} (company's current actual cost {cod:.1%} + LBO risk premium 2%)"
            )
    else:
        interest_rate = DEFAULT_INTEREST_RATE
        prov["interest_rate"] = (
            f"{interest_rate:.1%} (PE LBO leveraged-loan + high-yield-bond blended benchmark)"
        )

    # ----- Deal structure (PE convention; recorded for transparency) -------
    prov["entry_ev_ebitda"] = (
        f"{entry_ev_ebitda:.1f}× EBITDA (PE mid-market LBO entry-multiple convention)"
    )
    prov["exit_ev_ebitda"] = (
        f"{exit_ev_ebitda:.1f}× EBITDA (conservative assumption, no multiple expansion)"
    )
    prov["leverage_multiple"] = (
        f"{leverage_multiple:.1f}× EBITDA (PE LBO total Debt / EBITDA industry benchmark)"
    )
    prov["holding_period_years"] = f"{holding_period_years}yr (PE holding-period convention)"
    prov["mandatory_amort_pct"] = (
        f"{DEFAULT_MANDATORY_AMORT:.1%} (Term Loan B mandatory-amortization convention)"
    )

    # ----- entry EBITDA (cyclical normalization) ----------------------------
    # A commodity/deep-cyclical's entry EV and acquisition debt must be priced on
    # NORMALIZED through-cycle EBITDA (revenue_base × the normalized margin the
    # projection already uses), NOT the current LTM. Pricing entry on a cycle-PEAK
    # LTM while the projection reverts to the normalized margin sets debt at a
    # multiple of peak EBITDA the projected normalized EBITDA cannot service — the
    # schedule blows up and exit equity goes negative purely as a caliber artifact
    # (MU: leverage 5× peak EBITDA = 10.6× normalized). Mirrors the Damodaran
    # convention seed_dcf_inputs uses: normalized MARGIN × current revenue (revenue
    # is NOT re-based). entry_ebitda stays None for every non-cyclical, so the
    # operator prices entry on ltm_ebitda exactly as before (byte-identical). The
    # normalization is symmetric: a trough-phase cyclical (normalized > LTM) is
    # priced UP to its through-cycle earnings power, not the depressed current LTM.
    final_ebitda_margin = max(0.01, min(0.95, ebitda_margin))
    entry_ebitda: float | None = None
    cyclical = is_commodity_cyclical(
        industry=financials.market.industry,
        sector=financials.market.sector,
        ticker=financials.ticker,
    )
    if cyclical:
        entry_ebitda = revenue_base * final_ebitda_margin
        basis = commodity_cyclical_basis(financials.market.industry)
        basis_note = (
            "steel / shipping / chemicals / oil & gas / autos and other commodity-cyclical industries"
            if basis == "industry"
            else "memory / storage whitelist / keyword"
        )
        phase = "peak" if ltm_ebitda > entry_ebitda else "trough"
        entry_ev_ability = entry_ev_ebitda * entry_ebitda
        market_clause = ""
        market_cap = financials.market.market_cap if financials.market else None
        if market_cap and market_cap > 0:
            net_debt = (financials.balance.total_debt or 0.0) - (
                financials.balance.total_cash or 0.0
            )
            market_ev = market_cap + net_debt
            if market_ev > 0:
                ratio = entry_ev_ability / market_ev
                market_clause = (
                    f", ~{ratio:.0%} of the current market enterprise value ${market_ev / 1e9:.0f}B"
                )
                if ratio < 0.85:
                    market_clause += " — an LBO at today's market price is not feasible"
        prov["cyclical_normalization"] = (
            f"Classified as a commodity-cyclical ({basis_note}) → entry EV and acquisition "
            f"debt are priced on NORMALIZED through-cycle EBITDA ${entry_ebitda / 1e9:.1f}B "
            f"(revenue base ${revenue_base / 1e9:.1f}B × normalized EBITDA margin "
            f"{final_ebitda_margin:.1%}), not the current {phase} LTM EBITDA "
            f"${ltm_ebitda / 1e9:.1f}B — a sponsor underwrites leverage against sustainable "
            f"through-cycle earnings, not the current cycle phase. Ability-to-pay entry EV = "
            f"{entry_ev_ebitda:.1f}× × ${entry_ebitda / 1e9:.1f}B = ${entry_ev_ability / 1e9:.0f}B"
            f"{market_clause}."
        )

    # Disclose any construction-time clamp that binds (BUG-023 — mirror of the
    # dcf_seed post-pass). Pure provenance side-effect; the field values
    # constructed below are unchanged. nwc_change/interest/leverage are omitted:
    # nwc_pct + interest_rate are already clamped tighter upstream (their [-0.2,
    # 0.3] / [0, 0.5] construction bands never bind), and leverage_multiple is a
    # deal-structure convention arg (default 5.0×), not a computed caliber.
    _disclose_construction_clamp(prov, "ebitda_margin", ebitda_margin, 0.01, 0.95)
    _disclose_construction_clamp(prov, "da_pct_revenue", da_pct, 0.0, 0.3)
    _disclose_construction_clamp(prov, "capex_pct_revenue", capex_pct, 0.0, 0.5)

    return LBOInputs(
        ticker=financials.ticker,
        ltm_ebitda=ltm_ebitda,
        entry_ebitda=entry_ebitda,
        entry_ev_ebitda=entry_ev_ebitda,
        exit_ev_ebitda=exit_ev_ebitda,
        holding_period_years=holding_period_years,
        revenue_base=revenue_base,
        revenue_growth_rate=revenue_growth_rate,
        ebitda_margin=final_ebitda_margin,
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
