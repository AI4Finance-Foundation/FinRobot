"""normalize_financials: raw provider financials DataResult → NormalizedFinancials.

Takes the provider's IS/BS reporting-currency tag at face value (see
``normalize.currency`` for why no country heuristic may second-guess it),
exposes the TTM ``period_end`` so a stale denominator is visible instead of
silent, and stamps provenance with degraded markers (period basis, TTM lag).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_PERIOD_BASIS_UNKNOWN,
    DEGRADED_TTM_LAG,
    NormalizedFinancials,
    Provenance,
)
from finrobot.engine.data.normalize.price import _date_to_dt, _f

# A TTM denominator this many full quarters behind the fetch date is flagged as
# stale. 1 quarter is the normal reporting lag; ≥2 means it predates a quarter
# that should already be reported.
_TTM_LAG_DEGRADE_THRESHOLD = 2


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _ttm_lag_quarters(period_end: date | None, fetched_at: datetime) -> int | None:
    """Full quarters between the TTM period end and the fetch date.

    A heuristic freshness hint, not a reported figure: the UI primarily shows
    the ``period_end`` date itself.
    """
    if period_end is None:
        return None
    days = (fetched_at.date() - period_end).days
    if days < 0:
        return 0
    return days // 91


def normalize_financials(result: DataResult) -> NormalizedFinancials:
    data = result.data if isinstance(result.data, dict) else {}
    ticker = result.ticker

    reporting_currency = (data.get("financial_currency") or "USD").upper()
    quote_currency = (data.get("quote_currency") or "USD").upper()
    # country flows into the snapshot untouched — the family-1 verifier
    # (audit_foreign_issuer_usd_tags) needs it to flag double-USD foreign
    # issuers for review; it never alters the currency tags here. is_adr rides
    # alongside (FMP /profile isAdr; None on yfinance) so the same verifier can
    # suppress the banner for a confirmed ADR.
    country = data.get("country")
    is_adr = data.get("is_adr")

    period_end = _parse_date(data.get("fiscal_year") or data.get("date"))
    _raw_basis: str = data.get("period_basis") or ""
    _basis_unknown = _raw_basis not in ("ttm", "annual", "quarterly")
    period_basis = "ttm" if _basis_unknown else _raw_basis
    as_of = _date_to_dt(period_end) if period_end else result.timestamp
    lag = _ttm_lag_quarters(period_end, result.timestamp)

    degraded: list[str] = []
    if _basis_unknown:
        degraded.append(DEGRADED_PERIOD_BASIS_UNKNOWN)
    if lag is not None and lag >= _TTM_LAG_DEGRADE_THRESHOLD:
        degraded.append(DEGRADED_TTM_LAG)

    provenance = Provenance(
        provider=result.provider,
        as_of=as_of,
        fetched_at=result.timestamp,
        degraded=degraded,
    )
    return NormalizedFinancials(
        ticker=ticker,
        company_name=data.get("company_name"),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
        period_end=period_end,
        period_basis=period_basis,  # type: ignore[arg-type]
        as_of=as_of,
        revenue=_f(data.get("revenue")),
        ebitda=_f(data.get("ebitda")),
        net_income=_f(data.get("net_income")),
        gross_margin=_f(data.get("gross_margin")),
        operating_margin=_f(data.get("operating_margin")),
        operating_income=_f(data.get("operating_income")),
        income_tax_expense=_f(data.get("income_tax_expense")),
        market_cap=_f(data.get("market_cap")),
        shares_outstanding=_f(data.get("shares_outstanding")),
        current_price=_f(data.get("current_price")),
        pe_ratio=_f(data.get("pe_ratio")),
        pe_ttm_lag_quarters=lag,
        total_debt=_f(data.get("total_debt")),
        total_cash=_f(data.get("total_cash")),
        preferred_stock=_f(data.get("preferred_stock")),
        noncontrolling_interest=_f(data.get("noncontrolling_interest")),
        depreciation_amortization=_f(data.get("depreciation_amortization")),
        rd_expense=_f(data.get("rd_expense")),
        sga_expense=_f(data.get("sga_expense")),
        interest_expense=_f(data.get("interest_expense")),
        operating_cash_flow=_f(data.get("operating_cash_flow")),
        capital_expenditure=_f(data.get("capital_expenditure")),
        dividend_per_share=_f(data.get("dividend_per_share")),
        dividend_yield=_f(data.get("dividend_yield")),
        payout_ratio=_f(data.get("payout_ratio")),
        book_value_per_share=_f(data.get("book_value_per_share")),
        return_on_equity=_f(data.get("return_on_equity")),
        forward_eps=_f(data.get("forward_eps")),
        forward_pe=_f(data.get("forward_pe")),
        trailing_eps=_f(data.get("trailing_eps")),
        industry=data.get("industry"),
        sector=data.get("sector"),
        country=country,
        is_adr=is_adr,
        beta=_f(data.get("beta")),
        ttm_quarter_ends=[
            d for d in (_parse_date(x) for x in (data.get("ttm_quarter_ends") or [])) if d
        ],
        provenance=provenance,
    )
