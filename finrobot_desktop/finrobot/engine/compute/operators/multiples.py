from statistics import median, mean
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


# Sanity bounds for peer multiples — a garbage filter, not a "meaningfulness"
# filter. The lower bounds catch currency-unit-mismatch artifacts (yfinance
# returning a foreign-listed ADR's EBITDA in local currency — TWD for TSM,
# EUR for ASML, JPY for Toyota — while market_cap comes through in USD,
# collapsing the ratio to sub-1x fractions). The upper bounds catch
# divide-by-near-zero garbage where EBITDA has already collapsed to a sliver.
#
# EV/EBITDA range rationale (0.5x – 300x): Damodaran (Investment Valuation,
# 3e, Ch.7; data.stern.nyu.edu industry trailing EV/EBITDA, updated annually)
# shows cyclical-trough sectors (shipping, steel, autos, oil services) reach
# 3-5x in genuine downturns; CFA Institute Equity Asset Valuation 4e Ch.7
# documents true sub-3x prints during 2008-09 and 2020 COVID-trough quarters
# but no credible sustained sub-1x outside of unit-conversion errors. We
# extend the floor to 0.5x as a conservative buffer for one-off distressed
# quarters; sub-0.5x is taken as evidence of FX / unit mismatch and dropped.
#
# EV/Revenue range rationale (0.1x – 100x): sub-0.1x is implausible for any
# publicly listed company — it implies market cap barely covers one month of
# revenue and is a reliable FX-mismatch signal. Upper 100x accommodates
# high-growth SaaS/biotech with near-zero revenue.
#
# P/E range rationale (1.0x – 300x): sub-1x P/E means the market prices the
# company at less than one year of earnings — never observed for a healthy
# going-concern (value traps typically trade 3-5x). Upper 300x covers extreme
# growth premiums (AMZN 2020 ~80x TTM; speculative prints can briefly exceed).
#
# Live evidence: artifact ``art_2026-05-27T09:29:31_NVDA_equity_research``
# surfaced TSM at EV/EBITDA=0.158x, PE=1.85 — exactly the failure mode this
# guards against.
#
# Both the compute layer (this module) and the pipeline validator
# (``validate_peer_comps``) reference the same constants so the two layers
# can never drift out of alignment. Compute returns None below the floor so
# ``calculate_peer_statistics`` excludes the row from median/mean.
PEER_EV_EBITDA_SANITY_MIN: float = 0.5
PEER_EV_EBITDA_SANITY_MAX: float = 300.0
PEER_EV_REVENUE_SANITY_MIN: float = 0.1
PEER_EV_REVENUE_SANITY_MAX: float = 100.0
PEER_PE_SANITY_MIN: float = 1.0
PEER_PE_SANITY_MAX: float = 300.0

# NOPAT core-earnings effective-tax band. Own rates outside this are degenerate
# (tax holidays, credit/DTA releases — observed live: AMD 0.2%, AVGO 1.8% in the
# NVDA peer set) and would distort NOPAT comparability, so such rows fall back to
# the peer-set median in-band rate. If the whole set is degenerate, the US
# federal statutory 21% is the last resort.
CORE_TAX_RATE_MIN: float = 0.05
CORE_TAX_RATE_MAX: float = 0.35
CORE_TAX_RATE_FALLBACK: float = 0.21


def _sanity(value: float | None, lo: float, hi: float) -> float | None:
    """Return ``value`` if it falls within ``[lo, hi]``, else None.

    None input propagates as None (not-meaningful rather than range-violation).
    Used by ``calculate_multiples`` to gate each ratio independently.
    """
    if value is None or value < lo or value > hi:
        return None
    return value


def calculate_ev(market_cap: float, total_debt: float, cash: float) -> float:
    """Enterprise Value = Market Cap + Total Debt - Cash"""
    return market_cap + total_debt - cash


def compute_ttm_fcf(
    operating_cash_flow: float | None,
    capital_expenditure: float | None,
) -> float | None:
    """Trailing-12M free cash flow = OCF − CapEx (levered FCF).

    The analyst-standard *actual* cash figure (not a DCF projection): OCF already
    embeds working-capital swings, stock-comp add-backs and deferred taxes, so
    OCF − CapEx is more accurate than the textbook EBIT(1−t)+D&A−CapEx−ΔNWC
    approximation and exactly reproduces FMP's own reported freeCashFlow
    (verified live on AAPL TTM: OCF 140.2B − CapEx 11.0B = 129.2B).

    ``capital_expenditure`` is a positive magnitude (the provider sign-flip is
    normalised upstream). Returns None when either component is unavailable so
    the cashflow analysis cites a real number or explicitly says N/A — never an
    LLM-fabricated estimate (CLAUDE.md red-line 3).
    """
    if operating_cash_flow is None or capital_expenditure is None:
        return None
    return operating_cash_flow - capital_expenditure


def fcf_yield(fcf: float | None, market_cap: float | None) -> float | None:
    """FCF yield = TTM FCF / market cap. None when either input is missing/≤0."""
    if fcf is None or not market_cap or market_cap <= 0:
        return None
    return fcf / market_cap


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Returns a new copy with computed fields set (input is not mutated).

    All three ratios are gated through ``_sanity`` with the published bounds:
    - EV/EBITDA: [0.5x, 300x]
    - EV/Revenue: [0.1x, 100x]
    - P/E: [1.0x, 300x]

    Values outside these bounds are returned as None so that
    ``calculate_peer_statistics`` excludes them from median/mean, and the
    pipeline validator surfaces the underlying data quality issue rather
    than silently producing a thinner peer set.
    """
    result = company.model_copy(deep=True)

    # EV (and the EV-based multiples) only when BOTH net-debt components are
    # reported. A missing total_debt/total_cash leaves EV undefined rather than
    # assuming zero — mirrors extract_financial_data's target path and keeps a
    # debt/cash-less peer out of the EV/EBITDA and EV/Revenue medians instead of
    # contributing an EV=market_cap artifact.
    if result.total_debt is not None and result.total_cash is not None:
        ev = calculate_ev(result.market_cap, result.total_debt, result.total_cash)
        result.enterprise_value = ev

        raw_ev_ebitda = (
            ev / result.ebitda if result.ebitda is not None and result.ebitda > 0 else None
        )
        result.ev_ebitda = _sanity(
            raw_ev_ebitda, PEER_EV_EBITDA_SANITY_MIN, PEER_EV_EBITDA_SANITY_MAX
        )

        raw_ev_revenue = ev / result.revenue if result.revenue > 0 else None
        result.ev_revenue = _sanity(
            raw_ev_revenue, PEER_EV_REVENUE_SANITY_MIN, PEER_EV_REVENUE_SANITY_MAX
        )
    else:
        result.enterprise_value = None
        result.ev_ebitda = None
        result.ev_revenue = None

    # P/E is equity-only and independent of net debt, so it survives a missing
    # balance sheet.
    raw_pe = (
        result.market_cap / result.net_income
        if result.net_income is not None and result.net_income > 0
        else None
    )
    result.pe_ratio = _sanity(raw_pe, PEER_PE_SANITY_MIN, PEER_PE_SANITY_MAX)

    return result


def _effective_tax_rate(net_income: float | None, income_tax_expense: float | None) -> float | None:
    """Own effective tax rate = tax / pretax, where pretax = net_income + tax.

    Returns None when net income or tax is unreported, or pretax ≤ 0 (loss-maker
    or degenerate), so the caller falls back to the peer-set median rate.
    """
    if net_income is None or income_tax_expense is None:
        return None
    pretax = net_income + income_tax_expense
    if pretax <= 0:
        return None
    return income_tax_expense / pretax


def calculate_core_pe(comps: PeerComps) -> PeerComps:
    """Compute the NOPAT core P/E for target + every peer, plus the peer median.

    P/E comparability requires one earnings caliber across the set. As-reported
    net income mixes in non-operating items that differ company-to-company —
    NVDA's TTM investment gains (~$27B), AMD/AVGO near-zero effective tax — so
    raw P/E compares apples to oranges. Core earnings normalise to after-tax
    operating profit:

        NOPAT = EBIT × (1 − t),   EBIT = operating_income (period-consistent;
                                  falls back to operating_margin × revenue)

    where ``t`` is each company's own effective rate when it falls in
    ``[CORE_TAX_RATE_MIN, CORE_TAX_RATE_MAX]``, else the peer-set median in-band
    rate (so one company's tax holiday can't distort the comp), else 21%
    statutory. ``core_pe = market_cap / NOPAT`` is gated by the same P/E sanity
    bounds as the as-reported ratio. Returns a new copy; input is not mutated.

    When the *target's* own rate is substituted (out of band or unreported), a
    warning is appended to ``warnings`` so the substitution that shapes the
    target's NOPAT — and thus the comps_pe price — is visible (BUG-049).
    """
    result = comps.model_copy(deep=True)

    # Pass 1 — peer-set median in-band rate, the fallback for degenerate rows.
    peer_rates = [
        r
        for p in result.peers
        if (r := _effective_tax_rate(p.net_income, p.income_tax_expense)) is not None
        and CORE_TAX_RATE_MIN <= r <= CORE_TAX_RATE_MAX
    ]
    fallback_rate = median(peer_rates) if peer_rates else CORE_TAX_RATE_FALLBACK

    # Pass 2 — assign each row its rate, NOPAT, and core P/E.
    def _apply(c: CompanyFinancials, *, is_target: bool = False) -> None:
        own = _effective_tax_rate(c.net_income, c.income_tax_expense)
        in_band = own is not None and CORE_TAX_RATE_MIN <= own <= CORE_TAX_RATE_MAX
        rate = own if (own is not None and in_band) else fallback_rate
        c.effective_tax_rate = rate
        # EBIT prefers the absolute operating_income (period-consistent with the
        # FMP base) over operating_margin × revenue: once revenue may be
        # XBRL-TTM-reconciled (override_company_with_xbrl), margin(FMP) ×
        # revenue(XBRL) mixes periods and lifts EBIT by the override divergence
        # (BUG-017). Fall back to margin × revenue only when operating_income is
        # absent; withhold (None) when neither is available rather than fabricate.
        if c.operating_income is not None:
            ebit = c.operating_income
        elif c.operating_margin is not None:
            ebit = c.operating_margin * c.revenue
        else:
            c.core_net_income = None
            c.core_pe_ratio = None
            return
        # When the target's own tax is out of band, its NOPAT (hence the comps_pe
        # target price) is built on a substitute rate, not the reported tax. The
        # substitution is a defensible normalisation, but it must be visible —
        # surface it so the user can judge whether the substitute caliber is fair
        # for this company (e.g. a real DTA-driven low-tax period; BUG-049).
        if is_target and not in_band:
            if own is not None:
                result.warnings.append(
                    f"Target effective tax rate {own:.1%} outside the core band "
                    f"[{CORE_TAX_RATE_MIN:.0%}, {CORE_TAX_RATE_MAX:.0%}]; "
                    f"core P/E uses substitute rate {rate:.1%}"
                )
            else:
                result.warnings.append(
                    f"Target effective tax rate unavailable; "
                    f"core P/E uses substitute rate {rate:.1%}"
                )
        nopat = ebit * (1 - rate)
        c.core_net_income = nopat
        c.core_pe_ratio = _sanity(
            c.market_cap / nopat if nopat > 0 else None,
            PEER_PE_SANITY_MIN,
            PEER_PE_SANITY_MAX,
        )

    _apply(result.target, is_target=True)
    for peer in result.peers:
        _apply(peer)

    core_vals = [p.core_pe_ratio for p in result.peers if p.core_pe_ratio is not None]
    result.median_core_pe = median(core_vals) if core_vals else None
    return result


def calculate_peer_statistics(comps: PeerComps) -> PeerComps:
    """Compute median and mean multiples across the peer set.

    Returns a new copy with statistics set (input is not mutated).
    Ignores None values. Guards against empty list before calling statistics.median/mean.

    Appends a sample-size warning to ``result.warnings`` for each multiple
    where one or more peers were excluded due to None (data-quality drop).
    Callers and the pipeline validator surface these so operators see the
    effective sample size rather than assuming all peers contributed.
    """
    result = comps.model_copy(deep=True)
    total = len(result.peers)

    ev_ebitda_vals = [p.ev_ebitda for p in result.peers if p.ev_ebitda is not None]
    pe_vals = [p.pe_ratio for p in result.peers if p.pe_ratio is not None]
    ev_revenue_vals = [p.ev_revenue for p in result.peers if p.ev_revenue is not None]

    result.median_ev_ebitda = median(ev_ebitda_vals) if ev_ebitda_vals else None
    result.mean_ev_ebitda = mean(ev_ebitda_vals) if ev_ebitda_vals else None
    result.median_pe = median(pe_vals) if pe_vals else None
    result.mean_pe = mean(pe_vals) if pe_vals else None
    result.median_ev_revenue = median(ev_revenue_vals) if ev_revenue_vals else None

    ev_ebitda_n = len(ev_ebitda_vals)
    if ev_ebitda_n < total:
        result.warnings.append(
            f"EV/EBITDA computed on n={ev_ebitda_n} of {total} peers"
            f" — {total - ev_ebitda_n} dropped due to data quality"
        )
    pe_n = len(pe_vals)
    if pe_n < total:
        result.warnings.append(
            f"P/E computed on n={pe_n} of {total} peers"
            f" — {total - pe_n} dropped due to data quality"
        )
    ev_revenue_n = len(ev_revenue_vals)
    if ev_revenue_n < total:
        result.warnings.append(
            f"EV/Revenue computed on n={ev_revenue_n} of {total} peers"
            f" — {total - ev_revenue_n} dropped due to data quality"
        )

    return result
