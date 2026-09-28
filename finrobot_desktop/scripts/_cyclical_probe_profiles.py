"""T2 probe: REAL FMP /profile + multi-year financials for storage cyclicals.

Rate-limit-aware (3s between calls, well under FMP burst). Pulls:
- /profile for MU, WDC, SNDK, STX → real industry/sector tag + data availability
  (the project's repeated trap is INFERRING peers' industry; this实拉s it).
- 8 annual income+cashflow years for MU/WDC/STX → the through-cycle window the
  mid-cycle normalization needs (storage cycle ≈ 4-6y; 5y default may miss a peak).

Run: `python scripts/_cyclical_probe_profiles.py`
"""

from __future__ import annotations

import asyncio

from finrobot.config import get_settings
from finrobot.engine.data.providers.fmp_provider import (
    _STABLE_BASE,
    FMPProvider,
)
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

TICKERS = ["MU", "WDC", "SNDK", "STX"]
HIST_TICKERS = ["MU", "WDC", "STX"]


async def main() -> int:
    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    assert settings.fmp_api_key, "no FMP key"
    fmp = FMPProvider(settings.fmp_api_key)

    print("=" * 100)
    print("FMP /profile — REAL industry/sector/availability (NEVER inferred)")
    print("=" * 100)
    for t in TICKERS:
        await asyncio.sleep(3.0)
        try:
            rows = await fmp._get("/profile", params={"symbol": t}, base=_STABLE_BASE)
        except Exception as e:  # noqa: BLE001
            print(f"\n{t}: /profile FAILED — {type(e).__name__}: {str(e)[:160]}")
            continue
        p = rows[0] if isinstance(rows, list) and rows else (rows or {})
        print(f"\n--- {t} ---")
        print(f"  companyName : {p.get('companyName')}")
        print(f"  industry    : {p.get('industry')!r}")
        print(f"  sector      : {p.get('sector')!r}")
        print(f"  country     : {p.get('country')!r}  currency: {p.get('currency')!r}")
        print(f"  price       : {p.get('price')}  mktCap: {p.get('marketCap')}")
        print(f"  beta        : {p.get('beta')}")
        print(
            f"  isEtf/Fund  : {p.get('isEtf')}/{p.get('isFund')}  isActivelyTrading: {p.get('isActivelyTrading')}"
        )
        desc = (p.get("description") or "")[:300]
        print(f"  desc[:300]  : {desc}")

    print("\n" + "=" * 100)
    print("8-YEAR ANNUAL income + cashflow — the through-cycle window for normalization")
    print("=" * 100)
    for t in HIST_TICKERS:
        await asyncio.sleep(3.0)
        try:
            inc = await fmp._get(
                "/income-statement",
                params={"symbol": t, "period": "annual", "limit": 8},
                base=_STABLE_BASE,
            )
        except Exception as e:  # noqa: BLE001
            print(f"\n{t}: income FAILED — {type(e).__name__}: {str(e)[:160]}")
            continue
        await asyncio.sleep(3.0)
        try:
            cf = await fmp._get(
                "/cash-flow-statement",
                params={"symbol": t, "period": "annual", "limit": 8},
                base=_STABLE_BASE,
            )
        except Exception as e:  # noqa: BLE001
            cf = []
            print(f"{t}: cashflow FAILED — {type(e).__name__}: {str(e)[:160]}")
        cf_by_year = {}
        for r in cf if isinstance(cf, list) else []:
            cf_by_year[str(r.get("calendarYear") or r.get("date", ""))[:4]] = r
        print(f"\n--- {t} : {len(inc) if isinstance(inc, list) else 0} annual years ---")
        print(
            f"  {'FY':>6} {'revenue':>14} {'op_income':>14} {'op_margin':>9} "
            f"{'ebitda':>14} {'ebitda_m':>9} {'net_inc':>14} {'capex':>13} {'capex/rev':>9}"
        )
        rows = inc if isinstance(inc, list) else []
        # newest first from FMP; print oldest→newest for cycle reading
        for r in reversed(rows):
            yr = str(r.get("calendarYear") or r.get("date", ""))[:4]
            rev = r.get("revenue") or 0
            opi = r.get("operatingIncome")
            ebitda = r.get("ebitda")
            ni = r.get("netIncome")
            c = cf_by_year.get(yr, {})
            capex = c.get("capitalExpenditure")
            opm = (opi / rev) if (opi is not None and rev) else None
            ebm = (ebitda / rev) if (ebitda is not None and rev) else None
            cxr = (abs(capex) / rev) if (capex is not None and rev) else None
            print(
                f"  {yr:>6} {rev:>14,.0f} "
                f"{(opi if opi is not None else float('nan')):>14,.0f} "
                f"{(opm if opm is not None else float('nan')):>9.1%} "
                f"{(ebitda if ebitda is not None else float('nan')):>14,.0f} "
                f"{(ebm if ebm is not None else float('nan')):>9.1%} "
                f"{(ni if ni is not None else float('nan')):>14,.0f} "
                f"{(abs(capex) if capex is not None else float('nan')):>13,.0f} "
                f"{(cxr if cxr is not None else float('nan')):>9.1%}"
            )
        # through-cycle averages
        import statistics

        opms = [
            (r.get("operatingIncome") / r.get("revenue"))
            for r in rows
            if r.get("operatingIncome") is not None and r.get("revenue")
        ]
        ebms = [
            (r.get("ebitda") / r.get("revenue"))
            for r in rows
            if r.get("ebitda") is not None and r.get("revenue")
        ]
        if opms:
            print(
                f"  → through-cycle op_margin: mean={statistics.mean(opms):.1%} "
                f"median={statistics.median(opms):.1%}  (last3 median="
                f"{statistics.median(opms[:3]) if len(opms) >= 3 else float('nan'):.1%})"
            )
        if ebms:
            print(
                f"  → through-cycle ebitda_margin: mean={statistics.mean(ebms):.1%} "
                f"median={statistics.median(ebms):.1%}  (last3 median="
                f"{statistics.median(ebms[:3]) if len(ebms) >= 3 else float('nan'):.1%})"
            )

    print("\nDONE_PROFILES")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
