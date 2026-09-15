"""EBITDA scalar primitives — pure ``EBITDA = Σ components`` arithmetic.

Lives in ``primitives/`` (not ``compute/multiples``) because ``data/`` providers
need ``calculate_ebitda_operating`` to enrich a fetched payload, and a provider
importing ``compute/`` would re-create the ``data → compute → data`` cycle
(ADR-0005 §2.2). Pure: no I/O, depends on nothing but the stdlib.
"""

from __future__ import annotations


def calculate_ebitda_operating(
    operating_income: float | None,
    depreciation_amortization: float | None,
) -> float | None:
    """Operating EBITDA = EBIT + D&A (Damodaran, Investment Valuation 3e Ch.7).

    The canonical numerator for EV/EBITDA: EV already nets out cash, so the
    earnings measure must likewise EXCLUDE the income that cash throws off
    (interest income, other non-operating income). Starting from operating
    income does exactly that. For cash-rich issuers (TSLA carries tens of $B
    earning interest) this runs materially below the bottom-up figure below.

    Returns None if either component is missing — never fabricates a number.
    """
    if operating_income is None or depreciation_amortization is None:
        return None
    return operating_income + depreciation_amortization


def calculate_ebitda_reported(
    net_income: float | None,
    income_tax_expense: float | None,
    interest_expense: float | None,
    depreciation_amortization: float | None,
) -> float | None:
    """Bottom-up EBITDA = Net Income + Tax + Interest Expense + D&A.

    The "reported EBITDA" convention most retail aggregators (Robinhood,
    MacroTrends) and FMP's own ``ebitda`` field use. Because it builds back up
    from net income, it INCLUDES non-operating income (interest income, gains)
    — so it overstates operating cash generation for cash-rich issuers and is
    NOT consistent with an EV that already removed the cash. Surfaced only as a
    secondary "street caliber" cross-check, not the primary EV/EBITDA.

    Returns None if any component is missing — never fabricates a number.
    """
    # Explicit per-name None guard (not any(...)) so the type checker narrows each
    # component to float — the sum is then unconditional, with no misleading
    # "filter out None" step suggesting None could still be present here (BUG-041).
    if (
        net_income is None
        or income_tax_expense is None
        or interest_expense is None
        or depreciation_amortization is None
    ):
        return None
    return float(net_income + income_tax_expense + interest_expense + depreciation_amortization)
