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
    ev = calculate_ev(result.market_cap, result.total_debt, result.total_cash)
    result.enterprise_value = ev

    raw_ev_ebitda = ev / result.ebitda if result.ebitda > 0 else None
    result.ev_ebitda = _sanity(raw_ev_ebitda, PEER_EV_EBITDA_SANITY_MIN, PEER_EV_EBITDA_SANITY_MAX)

    raw_ev_revenue = ev / result.revenue if result.revenue > 0 else None
    result.ev_revenue = _sanity(raw_ev_revenue, PEER_EV_REVENUE_SANITY_MIN, PEER_EV_REVENUE_SANITY_MAX)

    raw_pe = result.market_cap / result.net_income if result.net_income > 0 else None
    result.pe_ratio = _sanity(raw_pe, PEER_PE_SANITY_MIN, PEER_PE_SANITY_MAX)

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
