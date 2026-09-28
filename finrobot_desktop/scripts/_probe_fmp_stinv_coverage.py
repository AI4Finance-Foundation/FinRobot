"""[EMPIRICAL VALIDATION] FMP short-term-investments coverage probe (read-only).

Gates the proposed EV-cash caliber fix: change EV's cash leg from
``cashAndCashEquivalents`` (cash only) to cash + short-term investments so the
EV net-debt bridge stops overstating EV for cash-rich names (MSFT +$46B, TSLA
+$28B vs SEC-filed cash+ST).

The strongest objection is field-coverage asymmetry: if FMP omits short-term
investments for some tickers, the fix would subtract cash+ST for some names and
cash-only for others -- MORE inconsistent than today's uniform cash-only. So we
must first measure FMP coverage of the relevant raw balance-sheet fields across
a multi-sector basket, then cross-check FMP's own cash+ST against SEC truth.

Pulls the RAW FMP /balance-sheet-statement row (quarter, limit 1) via the live
FMP provider's rate-limited client, then for a SEC-coverable subset compares
FMP ``cashAndShortTermInvestments`` against SEC
``CashAndCashEquivalentsAtCarryingValue`` + ``ShortTermInvestments``.

Run:
    uv run python scripts/_probe_fmp_stinv_coverage.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from edgar import Company, set_identity

from finrobot.config import get_settings
from finrobot.engine.data.factory import build_data_layer, shutdown_data_layer
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

# ~35-name multi-sector basket: big tech, semis, consumer staples/discretionary,
# industrials, energy, pharma/health, financials/banks, telecom.
BASKET: tuple[str, ...] = (
    # big tech
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "META",
    "AMZN",
    "TSLA",
    "AVGO",
    "ORCL",
    "CRM",
    # semiconductors
    "AMD",
    "MU",
    "INTC",
    "QCOM",
    "TXN",
    # consumer
    "KO",
    "PEP",
    "PG",
    "WMT",
    "MCD",
    "NKE",
    # industrials
    "CAT",
    "GE",
    "HON",
    # energy
    "XOM",
    "CVX",
    # pharma / health
    "JNJ",
    "UNH",
    "PFE",
    "LLY",
    "ABBV",
    # financials / banks
    "JPM",
    "BAC",
    # telecom
    "VZ",
    "T",
)

# SEC cross-check subset (US filers with us-gaap XBRL; multi-sector).
SEC_SUBSET: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "TSLA",
    "PEP",
    "JNJ",
    "MU",
)

# us-gaap concept candidates per economic line (first non-empty wins).
SEC_CASH_EQ = ("CashAndCashEquivalentsAtCarryingValue",)
SEC_ST_INV = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "OtherShortTermInvestments",
)

# The three raw FMP balance-sheet fields under audit.
FMP_CASH_EQ = "cashAndCashEquivalents"
FMP_ST_INV = "shortTermInvestments"
FMP_CASH_AND_ST = "cashAndShortTermInvestments"


def _b(x: float | None) -> str:
    if x is None:
        return "        -"
    return f"{x / 1e9:8.2f}B"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _latest_sec_value(facts: Any, concepts: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Most recent instantaneous value among candidate concepts (balance sheet)."""
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
        num = _num(value)
        if num is None:
            continue
        end = getattr(fact, "period_end", None) or getattr(fact, "end", None)
        return num, (str(end) if end is not None else None)
    return None, None


async def _raw_fmp_balance(fmp: Any, ticker: str) -> dict[str, Any] | None:
    """Pull the freshest quarterly raw balance-sheet row straight from FMP.

    Mirrors the provider's own latest-snapshot call
    (/balance-sheet-statement?period=quarter&limit=1) so the fields we audit are
    exactly the ones the provider reads in ``_build_ttm_data``.
    """
    resp = await fmp._get(
        f"/balance-sheet-statement/{ticker}",
        params={"period": "quarter", "limit": 1},
    )
    rows = resp.json()
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    set_identity(settings.sec_user_agent or "FinRobot Audit audit@example.com")

    data_layer = build_data_layer(settings)
    fmp = next((p for p in data_layer._providers if p.name == "fmp"), None)
    if fmp is None:
        print("FATAL: no FMP provider built (key not hydrated?)")
        await shutdown_data_layer(data_layer)
        return 1

    rows: list[dict[str, Any]] = []
    try:
        # --- 1. RAW FMP field coverage across the basket ---
        print("=" * 96)
        print("RAW FMP /balance-sheet-statement (period=quarter, limit=1) field coverage")
        print("=" * 96)
        header = (
            f"{'ticker':7s} {'date':11s} "
            f"{'cashAndCashEq':>14s} {'shortTermInv':>14s} {'cashAndST':>14s} "
            f"{'ST/(cash+ST)':>13s}"
        )
        print(header)
        print("-" * len(header))

        for ticker in BASKET:
            try:
                bal = await _raw_fmp_balance(fmp, ticker)
            except Exception as exc:  # noqa: BLE001 - probe must keep going
                print(f"{ticker:7s} FETCH ERROR: {type(exc).__name__}: {exc}")
                rows.append({"ticker": ticker, "error": str(exc)})
                continue
            if bal is None:
                print(f"{ticker:7s} NO ROW RETURNED")
                rows.append({"ticker": ticker, "error": "no row"})
                continue

            date = str(bal.get("date") or "?")
            cash = _num(bal.get(FMP_CASH_EQ))
            stinv = _num(bal.get(FMP_ST_INV))
            cash_st = _num(bal.get(FMP_CASH_AND_ST))
            # Treat the *presence* of the key, not just truthiness: 0 is a valid
            # filed figure (e.g. a name that genuinely holds no ST investments).
            has_stinv = FMP_ST_INV in bal and bal.get(FMP_ST_INV) is not None
            has_cash_st = FMP_CASH_AND_ST in bal and bal.get(FMP_CASH_AND_ST) is not None
            ratio = ""
            if cash_st and cash_st > 0 and stinv is not None:
                ratio = f"{stinv / cash_st:12.1%}"
            print(
                f"{ticker:7s} {date:11s} "
                f"{_b(cash):>14s} {_b(stinv):>14s} {_b(cash_st):>14s} "
                f"{ratio:>13s}"
            )
            rows.append(
                {
                    "ticker": ticker,
                    "date": date,
                    "cash": cash,
                    "stinv": stinv,
                    "cash_st": cash_st,
                    "has_stinv": has_stinv,
                    "has_cash_st": has_cash_st,
                }
            )

        # --- 2. Coverage statistics ---
        ok_rows = [r for r in rows if "error" not in r]
        n = len(ok_rows)
        n_stinv = sum(1 for r in ok_rows if r["has_stinv"])
        n_cash_st = sum(1 for r in ok_rows if r["has_cash_st"])
        # Consistency: cashAndShortTermInvestments ~= cash + shortTermInvestments?
        recompute_ok = 0
        recompute_n = 0
        for r in ok_rows:
            if r["cash"] is not None and r["stinv"] is not None and r["cash_st"] is not None:
                recompute_n += 1
                expected = r["cash"] + r["stinv"]
                denom = max(abs(expected), abs(r["cash_st"]), 1.0)
                if abs(expected - r["cash_st"]) / denom <= 0.01:
                    recompute_ok += 1

        print("\n" + "=" * 96)
        print("COVERAGE SUMMARY")
        print("=" * 96)
        print(f"basket size (fetched OK)      : {n}/{len(rows)}")
        if n:
            print(f"shortTermInvestments present  : {n_stinv}/{n} ({n_stinv / n:.1%})")
            print(f"cashAndShortTermInvestments   : {n_cash_st}/{n} ({n_cash_st / n:.1%})")
        missing_stinv = [r["ticker"] for r in ok_rows if not r["has_stinv"]]
        missing_cash_st = [r["ticker"] for r in ok_rows if not r["has_cash_st"]]
        print(f"missing shortTermInvestments  : {missing_stinv or 'NONE'}")
        print(f"missing cashAndShortTermInv   : {missing_cash_st or 'NONE'}")
        if recompute_n:
            print(
                f"cashAndST == cash+ST (<=1%)   : {recompute_ok}/{recompute_n} "
                f"({recompute_ok / recompute_n:.1%})"
            )

        # --- 3. SEC cross-reliability ---
        print("\n" + "=" * 96)
        print("SEC CROSS-CHECK: FMP cashAndShortTermInvestments vs SEC cash+ST")
        print("=" * 96)
        sec_header = (
            f"{'ticker':7s} "
            f"{'SEC cash':>11s} {'SEC ST':>11s} {'SEC cash+ST':>12s} "
            f"{'FMP cash+ST':>12s} {'rel diff':>9s}"
        )
        print(sec_header)
        print("-" * len(sec_header))
        sec_match = 0
        sec_n = 0
        for ticker in SEC_SUBSET:
            fmp_row = next(
                (r for r in ok_rows if r["ticker"] == ticker and "error" not in r),
                None,
            )
            fmp_cash_st = fmp_row["cash_st"] if fmp_row else None
            try:
                facts = Company(ticker).get_facts()
                sec_cash, _ = _latest_sec_value(facts, SEC_CASH_EQ)
                sec_st, _ = _latest_sec_value(facts, SEC_ST_INV)
            except Exception as exc:  # noqa: BLE001 - probe resilience
                print(f"{ticker:7s} SEC ERROR: {type(exc).__name__}: {exc}")
                continue
            sec_cash_st = None
            if sec_cash is not None:
                sec_cash_st = sec_cash + (sec_st or 0.0)
            rel = ""
            if sec_cash_st and fmp_cash_st:
                sec_n += 1
                denom = max(abs(sec_cash_st), abs(fmp_cash_st), 1.0)
                rd = abs(sec_cash_st - fmp_cash_st) / denom
                rel = f"{rd:8.2%}"
                if rd <= 0.03:
                    sec_match += 1
            print(
                f"{ticker:7s} "
                f"{_b(sec_cash):>11s} {_b(sec_st):>11s} {_b(sec_cash_st):>12s} "
                f"{_b(fmp_cash_st):>12s} {rel:>9s}"
            )
        if sec_n:
            print(
                f"\nSEC agreement (<=3% rel)      : {sec_match}/{sec_n} ({sec_match / sec_n:.1%})"
            )
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        await shutdown_data_layer(data_layer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
