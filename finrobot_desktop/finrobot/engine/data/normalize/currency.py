"""Reporting-currency resolution for the normalization layer (ADR-0004).

yfinance ``financialCurrency`` is unreliable for ADRs — it often returns "USD"
for TSM/ASML/SAP when the IS/BS are actually in the home currency. FMP frequently
omits the field entirely. We use the country field as a reliable override signal.

We only override when the provider says "USD" but country implies a different
home currency — never override a non-USD provider tag, which would mask
legitimate multi-currency structures (e.g. a Bermuda-domiciled holding co that
genuinely reports in USD).
"""

from __future__ import annotations

COUNTRY_TO_REPORTING_CURRENCY: dict[str, str] = {
    "Taiwan": "TWD",
    "Japan": "JPY",
    "South Korea": "KRW",
    "China": "CNY",
    "Hong Kong": "HKD",
    "Germany": "EUR",
    "Netherlands": "EUR",
    "France": "EUR",
    "Italy": "EUR",
    "Spain": "EUR",
    "Switzerland": "CHF",
    "Sweden": "SEK",
    "Denmark": "DKK",
    "Norway": "NOK",
    "United Kingdom": "GBP",
    "Australia": "AUD",
    "Canada": "CAD",
    "India": "INR",
    "Brazil": "BRL",
    "Mexico": "MXN",
    "Singapore": "SGD",
    "Israel": "ILS",
}


def resolve_reporting_currency(
    provider_tag: str | None,
    ticker: str,
    country: str | None,
) -> str:
    """Reliable IS/BS reporting currency (ISO 4217, uppercase).

    Overrides a "USD" provider tag with the country's home currency only for
    ADRs (no '.' suffix). Local listings (e.g. 2330.TW) already carry the
    correct non-USD tag and are never overridden.
    """
    normalised = (provider_tag or "USD").upper()
    if normalised != "USD" or country is None:
        return normalised
    home_ccy = COUNTRY_TO_REPORTING_CURRENCY.get(country)
    if home_ccy is None:
        return normalised  # US or unknown country — trust USD
    if "." not in ticker:
        return home_ccy  # ADR on a US exchange — IS/BS in home currency
    return normalised  # local listing — provider tag already correct
