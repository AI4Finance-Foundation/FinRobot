from statistics import median, mean
from finagent.engine.models.financial import CompanyFinancials, PeerComps


def calculate_ev(market_cap: float, total_debt: float, cash: float) -> float:
    """Enterprise Value = Market Cap + Total Debt - Cash"""
    return market_cap + total_debt - cash


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Fills derived fields on the model (frozen=False allows this).
    Returns the same object with computed fields set.
    """
    ev = calculate_ev(company.market_cap, company.total_debt, company.total_cash)
    company.enterprise_value = ev

    company.ev_ebitda = ev / company.ebitda if company.ebitda > 0 else None
    company.ev_revenue = ev / company.revenue if company.revenue > 0 else None
    company.pe_ratio = (company.market_cap / company.net_income
                        if company.net_income > 0 else None)
    return company


def calculate_peer_statistics(comps: PeerComps) -> PeerComps:
    """Compute median and mean multiples across the peer set.

    Fills statistics fields on the model (frozen=False allows this).
    Ignores None values. Guard against empty list before calling statistics.median/mean.
    Returns the same object with statistics set.
    """
    ev_ebitda_vals = [p.ev_ebitda for p in comps.peers if p.ev_ebitda is not None]
    pe_vals = [p.pe_ratio for p in comps.peers if p.pe_ratio is not None]
    ev_revenue_vals = [p.ev_revenue for p in comps.peers if p.ev_revenue is not None]

    comps.median_ev_ebitda = median(ev_ebitda_vals) if ev_ebitda_vals else None
    comps.mean_ev_ebitda = mean(ev_ebitda_vals) if ev_ebitda_vals else None
    comps.median_pe = median(pe_vals) if pe_vals else None
    comps.mean_pe = mean(pe_vals) if pe_vals else None
    comps.median_ev_revenue = median(ev_revenue_vals) if ev_revenue_vals else None
    return comps
