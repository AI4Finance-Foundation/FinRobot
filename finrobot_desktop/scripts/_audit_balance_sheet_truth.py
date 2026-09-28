"""External-truth balance-sheet probe: SEC XBRL vs FMP-served vs yfinance.

Anchors two suspected numeric-accuracy issues surfaced by the basket probe:
  1. total_cash = FMP cashAndCashEquivalents only (excludes short-term
     investments) -> EV = mc + debt - cash overstated for cash-rich names.
  2. total_debt caliber (MSFT FMP 56.9B vs yfinance 125.4B = 2.2x).

Pulls the actual filed line items from SEC company facts and prints a
field | SEC | FMP-served | yfinance table per ticker.
"""

from __future__ import annotations

import asyncio
from typing import Any

from edgar import Company, set_identity

from finrobot.config import get_settings
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.types import DataType
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

TICKERS = ("AAPL", "MSFT", "NVDA", "MU", "TSLA")

# us-gaap concept candidates per economic line (first non-empty wins).
CASH_EQ = ("CashAndCashEquivalentsAtCarryingValue",)
ST_INV = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "OtherShortTermInvestments",
)
LT_DEBT = ("LongTermDebtNoncurrent", "LongTermDebt")
CUR_DEBT = ("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper")
LEASE = ("OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiabilityCurrent")


def _latest_concept_value(facts: Any, concepts: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Most recent instantaneous value among candidate concepts (balance sheet).

    Uses ``facts.get_fact('us-gaap:<concept>')`` which returns the latest reported
    fact for the concept; first concept with a value wins.
    """
    for concept in concepts:
        try:
            fact = facts.get_fact(f"us-gaap:{concept}")
        except Exception:
            fact = None
        if fact is None:
            continue
        value = getattr(fact, "numeric_value", None)
        if value is None:
            value = getattr(fact, "value", None)
        if value is None:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        end = getattr(fact, "period_end", None) or getattr(fact, "end", None)
        return num, (str(end) if end is not None else None)
    return None, None


def _b(x: float | None) -> str:
    if x is None:
        return "       —"
    return f"{x / 1e9:8.2f}B"


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    identity = settings.sec_user_agent or "FinRobot Audit audit@example.com"
    set_identity(identity)

    data_layer = build_data_layer(settings)
    fmp = next((p for p in data_layer._providers if p.name == "fmp"), None)
    yf = next((p for p in data_layer._providers if p.name == "yfinance"), None)

    try:
        for ticker in TICKERS:
            print(f"\n{'=' * 72}\n{ticker}\n{'=' * 72}")
            # SEC truth
            facts = Company(ticker).get_facts()
            sec_cash, cash_end = _latest_concept_value(facts, CASH_EQ)
            sec_stinv, stinv_end = _latest_concept_value(facts, ST_INV)
            sec_ltd, ltd_end = _latest_concept_value(facts, LT_DEBT)
            sec_curd, curd_end = _latest_concept_value(facts, CUR_DEBT)
            sec_lease, _ = _latest_concept_value(facts, LEASE)

            # FMP served
            fmp_res = await fmp.fetch(ticker, DataType.FINANCIALS) if fmp else None
            yf_res = await yf.fetch(ticker, DataType.FINANCIALS) if yf else None
            fmp_d = fmp_res.data if fmp_res else {}
            yf_d = yf_res.data if yf_res else {}

            sec_total_liquid = (sec_cash or 0) + (sec_stinv or 0)
            sec_total_debt = (sec_ltd or 0) + (sec_curd or 0)

            print(f"  SEC cash&equiv          {_b(sec_cash)}  (end {cash_end})")
            print(f"  SEC short-term invest   {_b(sec_stinv)}  (end {stinv_end})")
            print(f"  SEC cash+ST (EV cash)   {_b(sec_total_liquid)}")
            print(f"  FMP total_cash (served) {_b(fmp_d.get('total_cash'))}  <- system serves this")
            print(f"  yfinance total_cash     {_b(yf_d.get('total_cash'))}")
            print("  ---")
            print(f"  SEC long-term debt      {_b(sec_ltd)}  (end {ltd_end})")
            print(f"  SEC current debt        {_b(sec_curd)}  (end {curd_end})")
            print(f"  SEC op-lease liab       {_b(sec_lease)}")
            print(f"  SEC LT+current debt     {_b(sec_total_debt)}")
            print(f"  FMP total_debt (served) {_b(fmp_d.get('total_debt'))}  <- system serves this")
            print(f"  yfinance total_debt     {_b(yf_d.get('total_debt'))}")
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(data_layer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
