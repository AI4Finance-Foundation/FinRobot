from statistics import median, mean
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


def calculate_ev(market_cap: float, total_debt: float, cash: float) -> float:
    """Enterprise Value = Market Cap + Total Debt - Cash"""
    return market_cap + total_debt - cash


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Returns a new copy with computed fields set (input is not mutated).
    """
    result = company.model_copy(deep=True)
    ev = calculate_ev(result.market_cap, result.total_debt, result.total_cash)
    result.enterprise_value = ev

    result.ev_ebitda = ev / result.ebitda if result.ebitda > 0 else None
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
