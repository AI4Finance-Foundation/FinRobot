from statistics import median, mean
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


# Below this floor, EV/EBITDA is almost certainly a unit-mismatch artifact
# rather than a real cyclical extreme. Common cause: yfinance returning a
# foreign-listed ADR's EBITDA in local currency (TWD for TSM, EUR for ASML,
# JPY for Toyota) while market_cap comes through in USD — the ratio
# collapses to fractions far below any plausible economic value. By
# returning None we let calculate_peer_statistics exclude the row from
# median / mean rather than poison the synthesis.
#
# The live NVDA smoke (artifact ``art_2026-05-27T09:29:31_NVDA_equity_research``)
# surfaced TSM at 0.158x in the peer set — exactly the failure mode this
# guards against. The validator's lower bound (0.5x in validate_peer_comps)
# would still catch it loudly downstream; this compute-layer N/M just keeps
# the median untainted in the meantime.
_EV_EBITDA_NOT_MEANINGFUL_FLOOR = 1.0


def calculate_ev(market_cap: float, total_debt: float, cash: float) -> float:
    """Enterprise Value = Market Cap + Total Debt - Cash"""
    return market_cap + total_debt - cash


def calculate_multiples(company: CompanyFinancials) -> CompanyFinancials:
    """Compute EV/EBITDA, EV/Revenue, P/E for a single company.

    Uses company.total_debt and company.total_cash for EV calculation.
    Returns a new copy with computed fields set (input is not mutated).

    EV/EBITDA below ``_EV_EBITDA_NOT_MEANINGFUL_FLOOR`` is treated as not
    meaningful (returns None) — see the constant's docstring for why.
    """
    result = company.model_copy(deep=True)
    ev = calculate_ev(result.market_cap, result.total_debt, result.total_cash)
    result.enterprise_value = ev

    raw_ev_ebitda = ev / result.ebitda if result.ebitda > 0 else None
    result.ev_ebitda = (
        raw_ev_ebitda
        if raw_ev_ebitda is not None and raw_ev_ebitda >= _EV_EBITDA_NOT_MEANINGFUL_FLOOR
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
