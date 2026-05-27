from statistics import median, mean
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


# Sanity bounds for peer EV/EBITDA — a garbage filter, not a "meaningfulness"
# filter. The lower bound catches currency-unit-mismatch artifacts (yfinance
# returning a foreign-listed ADR's EBITDA in local currency — TWD for TSM,
# EUR for ASML, JPY for Toyota — while market_cap comes through in USD,
# collapsing the ratio to sub-1x fractions). The upper bound catches
# divide-by-near-zero garbage where EBITDA has already collapsed to a sliver.
#
# Range rationale (0.5x – 300x): Damodaran (Investment Valuation, 3e, Ch.7;
# data.stern.nyu.edu industry trailing EV/EBITDA, updated annually) shows
# cyclical-trough sectors (shipping, steel, autos, oil services) reach 3-5x
# in genuine downturns; CFA Institute Equity Asset Valuation 4e Ch.7
# documents true sub-3x prints during 2008-09 and 2020 COVID-trough quarters
# but no credible sustained sub-1x outside of unit-conversion errors. We
# extend the floor to 0.5x as a conservative buffer for one-off distressed
# quarters; sub-0.5x is taken as evidence of FX / unit mismatch and dropped.
#
# Live evidence: artifact ``art_2026-05-27T09:29:31_NVDA_equity_research``
# surfaced TSM at 0.158x — exactly the failure mode this guards against.
#
# Both the compute layer (this module) and the pipeline validator
# (``validate_peer_comps``) reference the same constants so the two layers
# can never drift out of alignment. Compute returns None below the floor so
# ``calculate_peer_statistics`` excludes the row from median/mean; validator
# raises loudly downstream so operators see the underlying data quality
# issue rather than silently get a thinner peer set.
PEER_EV_EBITDA_SANITY_MIN: float = 0.5
PEER_EV_EBITDA_SANITY_MAX: float = 300.0


def calculate_ev(market_cap: float, total_debt: float, cash: float) -> float:
    """Enterprise Value = Market Cap + Total Debt - Cash"""
    return market_cap + total_debt - cash


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Returns a new copy with computed fields set (input is not mutated).

    EV/EBITDA outside ``[PEER_EV_EBITDA_SANITY_MIN, PEER_EV_EBITDA_SANITY_MAX]``
    is treated as not meaningful (returns None) — see the constant's docstring
    for the cyclical-trough rationale and the unit-mismatch failure mode.
    """
    result = company.model_copy(deep=True)
    ev = calculate_ev(result.market_cap, result.total_debt, result.total_cash)
    result.enterprise_value = ev

    raw_ev_ebitda = ev / result.ebitda if result.ebitda > 0 else None
    result.ev_ebitda = (
        raw_ev_ebitda
        if raw_ev_ebitda is not None
        and PEER_EV_EBITDA_SANITY_MIN <= raw_ev_ebitda <= PEER_EV_EBITDA_SANITY_MAX
        else None
    )
    result.ev_revenue = ev / result.revenue if result.revenue > 0 else None
    result.pe_ratio = result.market_cap / result.net_income if result.net_income > 0 else None
    return result


def calculate_peer_statistics(comps: PeerComps) -> PeerComps:
    """Compute median and mean multiples across the peer set.

    Returns a new copy with statistics set (input is not mutated).
    Ignores None values. Guard against empty list before calling statistics.median/mean.
    """
    result = comps.model_copy(deep=True)
    ev_ebitda_vals = [p.ev_ebitda for p in result.peers if p.ev_ebitda is not None]
    pe_vals = [p.pe_ratio for p in result.peers if p.pe_ratio is not None]
    ev_revenue_vals = [p.ev_revenue for p in result.peers if p.ev_revenue is not None]

    result.median_ev_ebitda = median(ev_ebitda_vals) if ev_ebitda_vals else None
    result.mean_ev_ebitda = mean(ev_ebitda_vals) if ev_ebitda_vals else None
    result.median_pe = median(pe_vals) if pe_vals else None
    result.mean_pe = mean(pe_vals) if pe_vals else None
    result.median_ev_revenue = median(ev_revenue_vals) if ev_revenue_vals else None
    return result
